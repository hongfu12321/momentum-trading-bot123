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
from .data.normalize import BAR_LENGTH
from .data.provider import AuthenticationError, EntitlementError, ProviderError

SPREAD_CAP_BPS = 50.0  # docs/DESIGN.md section 5: spread cap 0.5%
MAX_QUOTE_AGE_S = 3.0  # docs/DESIGN.md section 5: quote age <= 3s
EXECUTABLE, LOCKED, CROSSED, ONE_SIDED = "executable", "locked", "crossed", "one_sided"


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
    trigger_bar_start_utc: str
    window_start_utc: str  # when the trigger bar completed, i.e. when the signal became available
    window_end_utc: str
    status: str = "ok"
    error: str | None = None
    quotes: int = 0
    requests: int = 0
    bytes: int = 0
    seconds: float = 0.0
    minutes: int = 0
    minutes_with_quote: int = 0
    executable: int = 0
    locked: int = 0
    crossed: int = 0
    one_sided: int = 0
    median_spread_bps: float | None = None
    p90_spread_bps: float | None = None
    fresh_quote_time_share: float | None = None
    executable_time_share: float | None = None
    time_weighted_spread_bps: float | None = None
    time_share_within_spread_cap: float | None = None
    max_gap_seconds: float | None = None


def _ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw)  # Python 3.11+ accepts nanosecond fractions (truncated to µs)


def quote_state(bid: float, ask: float) -> str:
    """'executable' only for a two-sided quote with ask > bid; locked and crossed quotes are diagnostics."""
    if bid <= 0 or ask <= 0:
        return ONE_SIDED
    if ask < bid:
        return CROSSED
    return LOCKED if ask == bid else EXECUTABLE


def spread_bps(bid: float, ask: float) -> float:
    return (ask - bid) / ((ask + bid) / 2) * 10_000


def clean_quotes(rows: Iterable[Mapping[str, object]], start: datetime, end: datetime) -> list[Mapping[str, object]]:
    """Quotes inside [start, end), in time order, with exact duplicate rows removed."""
    seen: set[tuple] = set()
    out: list[tuple[datetime, Mapping[str, object]]] = []
    for q in rows:
        t = _ts(str(q["t"]))
        key = (t, q.get("bp"), q.get("ap"), q.get("bs"), q.get("as"))
        if start <= t < end and key not in seen:
            seen.add(key)
            out.append((t, q))
    out.sort(key=lambda x: x[0])  # stable: same-timestamp updates keep their feed order
    return [q for _, q in out]


def summarize_quotes(
    quotes: Iterable[Mapping[str, object]], start: datetime, end: datetime,
    spread_cap_bps: float = SPREAD_CAP_BPS, max_quote_age_s: float = MAX_QUOTE_AGE_S,
) -> dict[str, object]:
    """Pure statistics for one window.

    A quote counts as fresh for at most max_quote_age_s after its timestamp. Spread eligibility
    (time-weighted spread, time within the spread cap) uses only fresh *executable* quotes:
    two-sided with ask > bid. Locked, crossed and one-sided quotes are counted separately and
    never make a window eligible. Time before the first quote in the window counts as no quote.
    """
    spreads: list[float] = []
    weighted = fresh_time = exec_time = tight = 0.0
    minutes: set[int] = set()
    counts = {"quotes": 0, EXECUTABLE: 0, LOCKED: 0, CROSSED: 0, ONE_SIDED: 0}
    last_t: datetime = start
    last_spread: float | None = None
    seen_quote = False
    max_gap = 0.0

    def close_interval(t: datetime) -> None:
        nonlocal weighted, fresh_time, exec_time, tight
        if not seen_quote:
            return
        fresh = min((t - last_t).total_seconds(), max_quote_age_s)
        fresh_time += fresh
        if last_spread is not None:
            exec_time += fresh
            weighted += last_spread * fresh
            tight += fresh if last_spread <= spread_cap_bps else 0.0

    for q in clean_quotes(quotes, start, end):
        t = _ts(str(q["t"]))
        counts["quotes"] += 1
        minutes.add(int((t - start).total_seconds() // 60))
        max_gap = max(max_gap, (t - last_t).total_seconds())
        close_interval(t)
        bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)  # type: ignore[arg-type]
        state = quote_state(bid, ask)
        counts[state] += 1
        last_spread = spread_bps(bid, ask) if state == EXECUTABLE else None
        if last_spread is not None:
            spreads.append(last_spread)
        last_t, seen_quote = t, True
    max_gap = max(max_gap, (end - last_t).total_seconds())
    close_interval(end)
    spreads.sort()
    span = (end - start).total_seconds()
    return {
        **counts,
        "minutes": math.ceil(span / 60),
        "minutes_with_quote": len(minutes),
        "median_spread_bps": median(spreads) if spreads else None,
        "p90_spread_bps": spreads[min(len(spreads) - 1, int(0.9 * len(spreads)))] if spreads else None,
        "fresh_quote_time_share": fresh_time / span if span > 0 else None,
        "executable_time_share": exec_time / span if span > 0 else None,
        "time_weighted_spread_bps": weighted / exec_time if exec_time else None,
        "time_share_within_spread_cap": tight / span if span > 0 else None,
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


def signal_available_utc(row: Mapping[str, str]) -> datetime:
    """A trigger is known only once its bar completes; older datasets lack the explicit column."""
    if row.get("trigger_signal_available_utc"):
        return datetime.fromisoformat(row["trigger_signal_available_utc"])
    return datetime.fromisoformat(row["trigger_bar_start_utc"]) + BAR_LENGTH


def probe(source: QuoteSource, candidates: list[dict[str, str]], minutes: int, raw_dir: Path) -> list[QuoteWindowStats]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    out: list[QuoteWindowStats] = []
    blocked: str | None = None
    for c in candidates:
        start = signal_available_utc(c)
        w = session_windows(datetime.fromisoformat(c["trading_date"]).date())[c["session"]]
        end = min(start + timedelta(minutes=minutes), w.end_utc)
        stats = QuoteWindowStats(c["symbol"], c["trading_date"], c["session"], c.get("sample", ""),
                                 c["trigger_bar_start_utc"], start.isoformat(), end.isoformat())
        if blocked:
            stats.status, stats.error = "skipped", blocked
            out.append(stats)
            continue
        r0, b0, t0 = source.request_count, source.bytes_received, time.perf_counter()
        raw_path = raw_dir / f"{c['trading_date']}_{c['session']}_{c['symbol']}_{start:%H%M}_{minutes}m.jsonl.gz"
        cost_path = raw_path.with_name(raw_path.name.replace(".jsonl.gz", ".cost.json"))
        try:
            if raw_path.is_file() and cost_path.is_file():
                with gzip.open(raw_path, "rt", encoding="utf-8") as fh:
                    rows = [json.loads(line) for line in fh]
                stats.status = "cached"
                cost = json.loads(cost_path.read_text(encoding="utf-8"))  # original fetch cost, for extrapolation
            else:
                rows = list(source.iter_quotes(c["symbol"], "sip", start, end))
                tmp = raw_path.with_suffix(".tmp")
                with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                    fh.writelines(json.dumps(q, sort_keys=True) + "\n" for q in rows)
                tmp.replace(raw_path)
                cost = {"requests": source.request_count - r0, "bytes": source.bytes_received - b0,
                        "seconds": round(time.perf_counter() - t0, 3)}
                cost_path.write_text(json.dumps(cost), encoding="utf-8")
            for k, v in {**summarize_quotes(rows, start, end), **cost}.items():
                setattr(stats, k, v)
        except (EntitlementError, AuthenticationError) as exc:
            blocked = f"{type(exc).__name__}: {exc}"
            stats.status, stats.error = "entitlement_blocked", blocked
        except ProviderError as exc:
            stats.status, stats.error = "error", str(exc)
        out.append(stats)
    return out


def _q(values: list[float]) -> dict[str, float | None]:
    v = sorted(values)
    if not v:
        return {"n": 0, "median": None, "p10": None, "p90": None}
    return {"n": len(v), "median": median(v), "p10": v[int(0.1 * (len(v) - 1))], "p90": v[int(0.9 * (len(v) - 1))]}


def summarize_probe(stats: list[QuoteWindowStats], total_candidates: int, minutes: int) -> dict[str, object]:
    usable = [s for s in stats if s.status in ("ok", "cached")]
    fetched = [s for s in usable if s.requests]  # windows with a recorded original fetch cost
    by_session: dict[str, object] = {}
    for session in ("premarket", "afterhours"):
        g = [s for s in usable if s.session == session]
        by_session[session] = {
            "windows": len(g),
            "windows_with_any_quote": sum(1 for s in g if s.quotes),
            "quotes_per_window": _q([float(s.quotes) for s in g]),
            "minute_coverage": _q([s.minutes_with_quote / s.minutes for s in g if s.minutes]),
            "median_spread_bps": _q([s.median_spread_bps for s in g if s.median_spread_bps is not None]),
            "fresh_quote_time_share": _q([s.fresh_quote_time_share for s in g if s.fresh_quote_time_share is not None]),
            "executable_time_share": _q([s.executable_time_share for s in g if s.executable_time_share is not None]),
            "time_weighted_spread_bps": _q([s.time_weighted_spread_bps for s in g if s.time_weighted_spread_bps is not None]),
            "time_share_within_spread_cap": _q([s.time_share_within_spread_cap for s in g
                                                if s.time_share_within_spread_cap is not None]),
            "windows_never_within_spread_cap": sum(1 for s in g if not s.time_share_within_spread_cap),
            "max_gap_seconds": _q([s.max_gap_seconds for s in g if s.max_gap_seconds is not None]),
            "crossed_share": sum(s.crossed for s in g) / max(1, sum(s.quotes for s in g)),
            "locked_share": sum(s.locked for s in g) / max(1, sum(s.quotes for s in g)),
            "one_sided_share": sum(s.one_sided for s in g) / max(1, sum(s.quotes for s in g)),
        }
    mean_q = sum(s.quotes for s in usable) / len(usable) if usable else 0.0
    mean_bytes_per_quote = sum(s.bytes for s in fetched) / max(1, sum(s.quotes for s in fetched))
    sec_per_req = sum(s.seconds for s in fetched) / max(1, sum(s.requests for s in fetched))
    req_per_window = sum(s.requests for s in fetched) / len(fetched) if fetched else 1.0
    est_requests = total_candidates * req_per_window
    return {
        "window_minutes_after_trigger": minutes,
        "spread_cap_bps": SPREAD_CAP_BPS,
        "max_quote_age_seconds": MAX_QUOTE_AGE_S,
        "window_starts_at": "trigger bar completion (signal available), not trigger bar start",
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
