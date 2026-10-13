"""M2 prerequisite: is historical SIP quote (NBBO) data available and usable for extended hours?

Samples scanner candidates from a dataset, fetches SIP quotes for a window after each trigger,
and measures availability, density, spreads and fetch cost. This validates inputs for a future
execution simulator; it does not simulate fills or evaluate any strategy.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import random
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Protocol

from .data.market_calendar import session_windows
from .data.provider import AuthenticationError, EntitlementError, ProviderError


class QuoteSource(Protocol):
    request_count: int
    bytes_received: int

    def iter_quotes(self, symbol: str, feed: str, start: datetime, end: datetime) -> Iterator[dict]: ...


@dataclass(slots=True)
class QuoteWindowStats:
    symbol: str
    trading_date: str
    session: str
    sample: str
    window_start_utc: str
    window_end_utc: str
    status: str = "ok"
    error: str | None = None
    quotes: int = 0
    requests: int = 0
    bytes: int = 0
    seconds: float = 0.0
    minutes: int = 0
    minutes_with_quote: int = 0
    two_sided: int = 0
    locked: int = 0
    crossed: int = 0
    one_sided: int = 0
    median_spread_bps: float | None = None
    p90_spread_bps: float | None = None
    time_weighted_spread_bps: float | None = None
    max_gap_seconds: float | None = None


def _ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw)  # Python 3.11+ accepts nanosecond fractions (truncated to µs)


def summarize_quotes(quotes: Iterable[Mapping[str, object]], start: datetime, end: datetime) -> dict[str, object]:
    """Pure statistics for one window. Spread is (ask - bid) / mid in basis points on valid two-sided quotes."""
    spreads: list[float] = []
    weighted = weight = 0.0
    minutes: set[int] = set()
    counts = {"quotes": 0, "two_sided": 0, "locked": 0, "crossed": 0, "one_sided": 0}
    last_t, last_spread, max_gap = start, None, 0.0
    for q in quotes:
        t = _ts(str(q["t"]))
        counts["quotes"] += 1
        minutes.add(int((t - start).total_seconds() // 60))
        max_gap = max(max_gap, (t - last_t).total_seconds())
        if last_spread is not None:
            dt = (t - last_t).total_seconds()
            weighted += last_spread * dt
            weight += dt
        bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)  # type: ignore[arg-type]
        last_spread = None
        if bid <= 0 or ask <= 0:
            counts["one_sided"] += 1
        elif ask < bid:
            counts["crossed"] += 1
        else:
            counts["two_sided"] += 1
            counts["locked"] += ask == bid
            last_spread = (ask - bid) / ((ask + bid) / 2) * 10_000
            spreads.append(last_spread)
        last_t = t
    max_gap = max(max_gap, (end - last_t).total_seconds())
    if last_spread is not None:
        weighted += last_spread * (end - last_t).total_seconds()
        weight += (end - last_t).total_seconds()
    spreads.sort()
    return {
        **counts,
        "minutes": math.ceil((end - start).total_seconds() / 60),
        "minutes_with_quote": len(minutes),
        "median_spread_bps": median(spreads) if spreads else None,
        "p90_spread_bps": spreads[min(len(spreads) - 1, int(0.9 * len(spreads)))] if spreads else None,
        "time_weighted_spread_bps": weighted / weight if weight else None,
        "max_gap_seconds": max_gap,
    }


def sample_candidates(rows: list[dict[str, str]], n: int, seed: int) -> list[dict[str, str]]:
    """Deterministic sample of SIP candidates, split evenly between sessions."""
    pool = sorted((r for r in rows if r["sip_candidate"] == "True"),
                  key=lambda r: (r["session"], r["trading_date"], r["symbol"]))
    rng = random.Random(seed)
    out: list[dict[str, str]] = []
    for session in ("premarket", "afterhours"):
        group = [r for r in pool if r["session"] == session]
        out += rng.sample(group, min(len(group), n // 2))
    return sorted(out, key=lambda r: (r["trading_date"], r["session"], r["symbol"]))


def probe(source: QuoteSource, candidates: list[dict[str, str]], minutes: int, raw_dir: Path) -> list[QuoteWindowStats]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    out: list[QuoteWindowStats] = []
    blocked: str | None = None
    for c in candidates:
        start = datetime.fromisoformat(c["trigger_bar_start_utc"])
        w = session_windows(datetime.fromisoformat(c["trading_date"]).date())[c["session"]]
        end = min(start + timedelta(minutes=minutes), w.end_utc)
        stats = QuoteWindowStats(c["symbol"], c["trading_date"], c["session"], c.get("sample", ""),
                                 start.isoformat(), end.isoformat())
        if blocked:
            stats.status, stats.error = "skipped", blocked
            out.append(stats)
            continue
        r0, b0, t0 = source.request_count, source.bytes_received, time.perf_counter()
        raw_path = raw_dir / f"{c['trading_date']}_{c['session']}_{c['symbol']}_{minutes}m.jsonl.gz"
        try:
            if raw_path.is_file():
                with gzip.open(raw_path, "rt", encoding="utf-8") as fh:
                    rows = [json.loads(line) for line in fh]
                stats.status = "cached"
            else:
                rows = list(source.iter_quotes(c["symbol"], "sip", start, end))
                tmp = raw_path.with_suffix(".tmp")
                with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                    fh.writelines(json.dumps(q, sort_keys=True) + "\n" for q in rows)
                tmp.replace(raw_path)
            for k, v in summarize_quotes(rows, start, end).items():
                setattr(stats, k, v)
        except (EntitlementError, AuthenticationError) as exc:
            blocked = f"{type(exc).__name__}: {exc}"
            stats.status, stats.error = "entitlement_blocked", blocked
        except ProviderError as exc:
            stats.status, stats.error = "error", str(exc)
        stats.requests = source.request_count - r0
        stats.bytes = source.bytes_received - b0
        stats.seconds = round(time.perf_counter() - t0, 3)
        out.append(stats)
    return out


def _q(values: list[float]) -> dict[str, float | None]:
    v = sorted(values)
    if not v:
        return {"n": 0, "median": None, "p10": None, "p90": None}
    return {"n": len(v), "median": median(v), "p10": v[int(0.1 * (len(v) - 1))], "p90": v[int(0.9 * (len(v) - 1))]}


def summarize_probe(stats: list[QuoteWindowStats], total_candidates: int, minutes: int) -> dict[str, object]:
    fetched = [s for s in stats if s.status == "ok"]
    usable = [s for s in stats if s.status in ("ok", "cached")]
    by_session: dict[str, object] = {}
    for session in ("premarket", "afterhours"):
        g = [s for s in usable if s.session == session]
        by_session[session] = {
            "windows": len(g),
            "windows_with_any_quote": sum(1 for s in g if s.quotes),
            "quotes_per_window": _q([float(s.quotes) for s in g]),
            "minute_coverage": _q([s.minutes_with_quote / s.minutes for s in g if s.minutes]),
            "median_spread_bps": _q([s.median_spread_bps for s in g if s.median_spread_bps is not None]),
            "time_weighted_spread_bps": _q([s.time_weighted_spread_bps for s in g if s.time_weighted_spread_bps is not None]),
            "max_gap_seconds": _q([s.max_gap_seconds for s in g if s.max_gap_seconds is not None]),
            "crossed_share": sum(s.crossed for s in g) / max(1, sum(s.quotes for s in g)),
            "locked_share": sum(s.locked for s in g) / max(1, sum(s.quotes for s in g)),
            "one_sided_share": sum(s.one_sided for s in g) / max(1, sum(s.quotes for s in g)),
        }
    mean_q = sum(s.quotes for s in usable) / len(usable) if usable else 0.0
    mean_bytes_per_quote = sum(s.bytes for s in fetched) / max(1, sum(s.quotes for s in fetched))
    sec_per_req = sum(s.seconds for s in fetched) / max(1, sum(s.requests for s in fetched))
    est_requests = total_candidates * max(1.0, mean_q / 10_000)
    return {
        "window_minutes_after_trigger": minutes,
        "status_counts": {k: sum(1 for s in stats if s.status == k) for k in sorted({s.status for s in stats})},
        "errors": sorted({s.error for s in stats if s.error}),
        "by_session": by_session,
        "extrapolation_to_all_candidates": {
            "candidates": total_candidates,
            "mean_quotes_per_window": mean_q,
            "estimated_quotes": round(total_candidates * mean_q),
            "estimated_requests": round(est_requests),
            "estimated_hours_at_measured_rate": round(est_requests * sec_per_req / 3600, 2),
            "estimated_raw_json_gb": round(total_candidates * mean_q * mean_bytes_per_quote / 1e9, 2),
        },
    }


def write_probe(out_dir: Path, stats: list[QuoteWindowStats], summary: dict[str, object], summary_path: Path) -> Path:
    """Per-window rows (licensed, stay local) go to out_dir; the aggregate summary goes to summary_path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "quote_windows.csv").open("w", newline="", encoding="utf-8") as fh:
        rows = [asdict(s) for s in stats]
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return summary_path
