"""M1-B: multi-day, broad-universe extended-hours dataset with SIP-vs-IEX discovery analysis.

Read-only market data; no orders. Point-in-time rules:
- Premarket reference = previous trading day's official (daily-bar) close, split-adjusted when
  the session date is a split ex-date. After-hours reference = same day's official close.
  Alpaca daily OHLC is regular-session only, so both are known before the session they serve.
- A symbol is fetched for a session only if its reference close exists and is low enough that the
  scan's price cap and minimum change could both be met; this pre-filter loses no candidates.
- Both feeds are scanned against the same SIP reference so differences isolate the intraday feed.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Literal, Protocol

from .compare import Event, ScanParams, match_events, scan_session, summarize_matches
from .data.alpaca_historical import AlpacaHistoricalProvider
from .data.coverage import missing_intervals
from .data.market_calendar import ET, EXTENDED_SESSIONS, PREMARKET, SessionWindow, previous_trading_day, session_windows, trading_days
from .data.normalize import normalize
from .data.provider import AuthenticationError, Bar, BarsRequest, EntitlementError, ProviderError
from .split import EMBARGO, IN_SAMPLE, OUT_OF_SAMPLE, chronological_split
from .universe import (
    CORPORATE_ACTION_TYPES,
    ORIGIN_RANK,
    DIRECTORY_FILES,
    DIRECTORY_URL,
    Universe,
    build_universe,
    directory_created,
    parse_directory,
)

FEEDS = ("sip", "iex")
BAR_FIELDS = ("symbol", "t", "o", "h", "l", "c", "v", "n", "vw")
DUPLICATE_MIN_VOLUME = 1000  # identical daily OHLCV above this is the same series under two symbols
FetchText = Callable[[str], str]


class AssetsReader(Protocol):
    def list_assets(self, status: Literal["active", "inactive"]) -> list[dict]: ...


class FeedBlocked(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    start: date
    end: date
    params: ScanParams = ScanParams()
    symbol_chunk: int = 1000
    delay: timedelta = timedelta(minutes=16)
    bucket_minutes: int = 30
    oos_fraction: float = 1 / 3
    embargo_days: int = 1


@dataclass(slots=True)
class DatasetResult:
    status: str
    manifest: dict[str, object]
    tables: dict[str, list[dict[str, object]]] = field(default_factory=dict)


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def urllib_fetch_text(url: str) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "momentum-bot-research"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def load_assets(inputs_dir: Path, reader: AssetsReader | None, now: datetime) -> tuple[list[dict], dict[str, object]]:
    """Saved /v2/assets snapshot (active + inactive), downloaded once with the read-only paper reader."""
    path = inputs_dir / "alpaca_assets.json"
    if not path.is_file():
        if reader is None:
            return [], {"alpaca_assets": "not used"}
        rows = reader.list_assets("active") + reader.list_assets("inactive")
        path.write_text(json.dumps({"downloaded_at_utc": now.isoformat(), "assets": rows}, sort_keys=True),
                        encoding="utf-8")
    saved = json.loads(path.read_text(encoding="utf-8"))
    counts = Counter(str(a.get("status")) for a in saved["assets"])
    return saved["assets"], {"alpaca_assets_downloaded_at_utc": saved["downloaded_at_utc"],
                             "alpaca_assets_sha256": _sha(path.read_bytes()), "alpaca_assets_counts": dict(counts)}


def load_inputs(
    inputs_dir: Path, provider: AlpacaHistoricalProvider, fetch_text: FetchText, start: date, actions_end: date,
    now: datetime,
) -> tuple[dict[str, str], dict[str, list[dict]], dict[str, object]]:
    """Reuse saved snapshots when present (reproducible reruns); otherwise download and save them."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {}
    texts: dict[str, str] = {}
    for name in DIRECTORY_FILES:
        path = inputs_dir / f"{name}.txt"
        if not path.is_file():
            path.write_text(fetch_text(DIRECTORY_URL.format(name=name)), encoding="utf-8", newline="")
            meta[f"{name}_downloaded_at_utc"] = now.isoformat()
        texts[name] = path.read_text(encoding="utf-8")
        meta[f"{name}_sha256"] = _sha(texts[name])
        meta[f"{name}_file_creation_time"] = directory_created(texts[name])
    ca_path = inputs_dir / "corporate_actions.json"
    if not ca_path.is_file():
        actions = provider.get_corporate_actions(CORPORATE_ACTION_TYPES, start, actions_end)
        ca_path.write_text(json.dumps({"start": start.isoformat(), "end": actions_end.isoformat(),
                                       "downloaded_at_utc": now.isoformat(), "corporate_actions": actions},
                                      indent=1, sort_keys=True), encoding="utf-8")
    saved = json.loads(ca_path.read_text(encoding="utf-8"))
    meta.update(corporate_actions_range=[saved["start"], saved["end"]],
                corporate_actions_downloaded_at_utc=saved["downloaded_at_utc"],
                corporate_actions_sha256=_sha(ca_path.read_bytes()),
                corporate_actions_counts={k: len(v) for k, v in sorted(saved["corporate_actions"].items())})
    return texts, saved["corporate_actions"], meta


def _write_bars(path: Path, bars: list[Bar]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(BAR_FIELDS)
        for b in sorted(bars, key=lambda b: (b.symbol, b.timestamp_utc)):
            w.writerow([b.symbol, b.timestamp_utc.isoformat(), b.open, b.high, b.low, b.close, b.volume,
                        "" if b.trade_count is None else b.trade_count, "" if b.vwap is None else b.vwap])
    tmp.replace(path)


def _read_bars(path: Path, feed: str) -> list[Bar]:
    with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
        return [
            Bar(r["symbol"], feed, datetime.fromisoformat(r["t"]), float(r["o"]), float(r["h"]), float(r["l"]),
                float(r["c"]), int(r["v"]), int(r["n"]) if r["n"] else None, float(r["vw"]) if r["vw"] else None)
            for r in csv.DictReader(fh)
        ]


class _Fetcher:
    def __init__(self, provider: AlpacaHistoricalProvider, cache: Path, chunk: int) -> None:
        self.provider, self.cache, self.chunk = provider, cache, chunk
        self.log: list[dict[str, object]] = []
        self.blocked: dict[str, str] = {}

    def bars(self, label: str, symbols: list[str], feed: str, start: datetime, end: datetime,
             timeframe: str = "1Min") -> list[Bar] | None:
        """Cached fetch keyed by the exact request; None if any chunk failed (never partially cached)."""
        key = _sha(json.dumps([symbols, feed, start.isoformat(), end.isoformat(), timeframe]))[:12]
        path = self.cache / feed / f"{label}_{key}.csv.gz"
        record = {"label": label, "feed": feed, "timeframe": timeframe, "symbols": len(symbols),
                  "start_utc": start.isoformat(), "end_utc": end.isoformat(), "status": "cached", "bars": 0,
                  "http_status": None, "error": None}
        if path.is_file():
            out = _read_bars(path, feed)
            record["bars"] = len(out)
            self.log.append(record)
            return out
        if feed in self.blocked:
            record.update(status="skipped", error=f"feed {self.blocked[feed]} earlier in run")
            self.log.append(record)
            return None
        out: list[Bar] = []
        try:
            for i in range(0, len(symbols), self.chunk):
                out += self.provider.get_bars(BarsRequest(tuple(symbols[i : i + self.chunk]), feed, start, end,  # type: ignore[arg-type]
                                                          timeframe=timeframe))
        except (EntitlementError, AuthenticationError) as exc:
            self.blocked[feed] = "entitlement_blocked" if isinstance(exc, EntitlementError) else "auth_failed"
            record.update(status=self.blocked[feed], http_status=exc.status, error=str(exc))
            self.log.append(record)
            if feed == "sip":
                raise FeedBlocked(str(exc)) from exc
            return None
        except ProviderError as exc:
            record.update(status="error", http_status=exc.status, error=str(exc))
            self.log.append(record)
            return None
        _write_bars(path, out)
        record.update(status="ok", bars=len(out))
        self.log.append(record)
        return out


def _buckets(window: SessionWindow, minutes: int) -> list[tuple[str, datetime, datetime]]:
    out, t = [], window.start_utc
    while t < window.end_utc:
        e = min(t + timedelta(minutes=minutes), window.end_utc)
        out.append((t.astimezone(ET).strftime("%H:%M"), t, e))
        t = e
    return out


def _post_trigger(window: SessionWindow, trigger: datetime, bars: list[Bar]) -> tuple[int, int, int]:
    """(minutes from trigger bar to session end, minutes with bars, longest no-bar run)."""
    sub = SessionWindow(window.name, window.trading_date, trigger, window.end_utc)
    have = [b.timestamp_utc for b in bars if b.timestamp_utc >= trigger]
    gaps = missing_intervals(sub, have)
    return sub.minutes, len(have), max((int((e - s).total_seconds() // 60) for s, e in gaps), default=0)


def build_dataset(
    provider: AlpacaHistoricalProvider,
    cfg: DatasetConfig,
    out_dir: Path,
    *,
    now_utc: datetime | None = None,
    fetch_text: FetchText = urllib_fetch_text,
    code_sha: str = "unknown",
    assets_reader: AssetsReader | None = None,
) -> DatasetResult:
    now_utc = now_utc or datetime.now(timezone.utc)
    days = trading_days(cfg.start, cfg.end)
    if not days:
        raise ValueError(f"no trading days between {cfg.start} and {cfg.end}")
    as_of = now_utc - cfg.delay
    if session_windows(days[-1])[EXTENDED_SESSIONS[-1]].end_utc > as_of:
        raise ValueError(f"{days[-1]} is inside the {cfg.delay} delay window; choose an older end date")
    prev_day = {d: previous_trading_day(d) for d in days}
    first = prev_day[days[0]]

    texts, actions, input_meta = load_inputs(out_dir / "inputs", provider, fetch_text, first,
                                             now_utc.astimezone(ET).date(), now_utc)
    assets, assets_meta = load_assets(out_dir / "inputs", assets_reader, now_utc)
    input_meta.update(assets_meta)
    universe = build_universe(parse_directory(texts["nasdaqlisted"], texts["otherlisted"]), actions, first, assets)
    chrono = chronological_split(days, cfg.oos_fraction, cfg.embargo_days)
    all_syms = sorted(universe.origin)
    fetcher = _Fetcher(provider, out_dir / "cache", cfg.symbol_chunk)
    p = cfg.params
    tables: dict[str, list[dict[str, object]]] = defaultdict(list)
    events: dict[str, dict[str, list[Event]]] = {f: {"candidate": [], "breakout": []} for f in FEEDS}
    split_fp: list[dict[str, object]] = []
    failed_sessions: list[str] = []
    status = "complete"

    try:
        day0 = datetime.combine(first, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
        day1 = datetime.combine(days[-1] + timedelta(days=1), datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
        daily_bars = fetcher.bars("daily", all_syms, "sip", day0, day1, timeframe="1Day")
        if daily_bars is None:
            raise FeedBlocked("daily reference bars could not be fetched")
        # Keep only what is needed (close, and OHLCV for duplicate detection) so long windows stay small.
        ohlcv = {(b.symbol, b.timestamp_utc.astimezone(ET).date()): (b.open, b.high, b.low, b.close, b.volume)
                 for b in daily_bars}
        del daily_bars
        daily = {k: v[3] for k, v in ohlcv.items()}

        # Same series under two symbols (a rename missing from corporate actions): keep the higher-precedence one.
        same: dict[tuple, list[str]] = defaultdict(list)
        for (sym, d), bar_values in ohlcv.items():
            if bar_values[4] >= DUPLICATE_MIN_VOLUME:
                same[(d, *bar_values)].append(sym)
        del ohlcv
        same_by_date: dict[date, list[list[str]]] = defaultdict(list)
        for (d, *_), syms in sorted(same.items()):
            if len(syms) > 1:
                same_by_date[d].append(sorted(syms))
        del same

        for (sym, ex), split in sorted(universe.splits.items()):
            if first < ex <= days[-1]:
                before, after = daily.get((sym, previous_trading_day(ex))), daily.get((sym, ex))
                tables["split_checks"].append({
                    "symbol": sym, "ex_date": ex.isoformat(), "old_rate": split.old_rate, "new_rate": split.new_rate,
                    "expected_price_factor": split.price_factor,
                    "raw_close_before": before, "raw_close_on_ex": after,
                    "observed_factor": after / before if before and after else None,
                })

        for d in days:
            windows = session_windows(d)
            # Only symbols the rename/delisting rules leave visible are compared, so a known rename
            # pair is never dropped twice. Either the session day or the reference day can expose it.
            visible = universe.symbols_for(d)
            vis, hidden = set(visible), set()
            for dx in (prev_day[d], d):
                for group in same_by_date.get(dx, []):
                    g = [s for s in group if s in vis]
                    if len(g) > 1:
                        keep = min(g, key=lambda s: (universe.rank(s), s))
                        hidden |= set(g) - {keep}
                        tables["duplicate_series"].append({"trading_date": d.isoformat(), "detected_on": dx.isoformat(),
                                                           "kept": keep, "dropped": ",".join(sorted(set(g) - {keep}))})
            todays = [s for s in visible if s not in hidden]
            sample = chrono.sample_of(d)
            for session in EXTENDED_SESSIONS:
                w = windows[session]
                min_change = p.premarket_min_change if session == PREMARKET else p.afterhours_min_change
                cap = p.max_price / (1 + min_change)
                refs: dict[str, float] = {}
                raw_refs: dict[str, float] = {}
                for sym in todays:
                    close = daily.get((sym, prev_day[d] if session == PREMARKET else d))
                    if close is None or close <= 0:
                        continue
                    split = universe.splits.get((sym, d)) if session == PREMARKET else None
                    ref = close * (split.price_factor if split else 1.0)
                    if ref <= cap:
                        refs[sym] = ref
                        if split:
                            raw_refs[sym] = close
                eligible = sorted(refs)
                origin_counts = Counter(universe.origin[s].split(":")[0] for s in eligible)
                tables["eligibility"].append({
                    "trading_date": d.isoformat(), "session": session, "sample": sample,
                    "universe_symbols": len(todays), "duplicate_series_hidden": len(hidden), "eligible": len(eligible),
                    **{f"eligible_{k}": origin_counts[k] for k in ORIGIN_RANK},
                    "split_adjusted_refs": len(raw_refs),
                })
                label = f"{d.isoformat()}_{session}"
                fetched = {f: fetcher.bars(label, eligible, f, w.start_utc, w.end_utc) for f in FEEDS}
                if any(v is None for v in fetched.values()):
                    failed_sessions.append(label)
                    status = "partial"
                    continue
                sbars, dropped = normalize([b for f in FEEDS for b in fetched[f] or []], {d: windows}, as_of_utc=as_of)
                by: dict[str, dict[str, list[Bar]]] = {f: defaultdict(list) for f in FEEDS}
                for sb in sbars:
                    if sb.session == session:
                        by[sb.bar.feed][sb.bar.symbol].append(sb.bar)

                # The first after-hours bar holds the closing auction; keep its volume out of coverage shares.
                auction_t = w.start_utc if session != PREMARKET and p.exclude_closing_auction_bar else None
                tables["eligibility"][-1].update({f"{f}_auction_bar_volume": sum(
                    b.volume for rows in by[f].values() for b in rows if b.timestamp_utc == auction_t) for f in FEEDS})
                for name, b0, b1 in _buckets(w, cfg.bucket_minutes):
                    row: dict[str, object] = {"trading_date": d.isoformat(), "session": session, "bucket_et": name,
                                              "eligible": len(eligible)}
                    for f in FEEDS:
                        inside = [b for rows in by[f].values() for b in rows if b0 <= b.timestamp_utc < b1]
                        row[f"{f}_symbols_with_bars"] = len({b.symbol for b in inside})
                        row[f"{f}_bars"] = len(inside)
                        row[f"{f}_volume"] = sum(b.volume for b in inside if b.timestamp_utc != auction_t)
                    tables["coverage_buckets"].append(row)

                for sym in eligible:
                    key = (sym, d, session)
                    found: dict[str, Event | None] = {}
                    for f in FEEDS:
                        cand, brk = scan_session(f, key, by[f].get(sym, []), refs[sym], p, w.start_utc)
                        found[f] = cand
                        if cand:
                            events[f]["candidate"].append(cand)
                        events[f]["breakout"] += brk
                    if sym in raw_refs:
                        unadj, _ = scan_session("sip", key, by["sip"].get(sym, []), raw_refs[sym], p, w.start_utc)
                        if bool(unadj) != bool(found["sip"]):
                            split_fp.append({"symbol": sym, "trading_date": d.isoformat(), "session": session,
                                             "candidate_without_adjustment": bool(unadj),
                                             "candidate_with_adjustment": bool(found["sip"])})
                    trigger = found["sip"] or found["iex"]
                    if trigger is None:
                        continue
                    row = {"symbol": sym, "trading_date": d.isoformat(), "session": session, "sample": sample,
                           "origin": universe.origin[sym], "reference_close": refs[sym],
                           "split_adjusted": sym in raw_refs, "sip_candidate": bool(found["sip"]),
                           "iex_candidate": bool(found["iex"]), "trigger_feed": trigger.feed,
                           "trigger_bar_start_utc": trigger.bar_start_utc.isoformat(),
                           "trigger_signal_available_utc": trigger.observed_at_utc.isoformat(),
                           "trigger_et": trigger.bar_start_utc.astimezone(ET).strftime("%H:%M")}
                    for f in FEEDS:
                        rows = by[f].get(sym, [])
                        span, have, gap = _post_trigger(w, trigger.bar_start_utc, rows)
                        row.update({f"{f}_session_volume": sum(b.volume for b in rows),
                                    f"{f}_post_trigger_minutes": span, f"{f}_post_trigger_bar_minutes": have,
                                    f"{f}_post_trigger_coverage": have / span if span else None,
                                    f"{f}_post_trigger_max_gap_minutes": gap})
                    tables["candidate_detail"].append(row)
                tables["dropped_bars"].append({"label": label, **dict(dropped)})
    except FeedBlocked as exc:
        status = "sip_entitlement_blocked" if fetcher.blocked.get("sip") == "entitlement_blocked" else "blocked"
        failed_sessions.append(f"aborted: {exc}")

    cand_matches = match_events(events["sip"]["candidate"], events["iex"]["candidate"], by_minute=False)
    gated = match_events([e for e in events["sip"]["breakout"] if e.candidate_gate],
                         [e for e in events["iex"]["breakout"] if e.candidate_gate], by_minute=True)
    for row in (*cand_matches, *gated):
        row["sample"] = chrono.sample_of(date.fromisoformat(str(row["trading_date"])))
    tables["candidate_matches"] = cand_matches
    tables["breakout_matches"] = gated
    tables["candidates"] = [e.row() for f in FEEDS for e in events[f]["candidate"]]
    tables["split_candidate_changes"] = split_fp
    tables["fetch_log"] = fetcher.log
    tables["universe"] = [
        {"symbol": s, "origin": universe.origin[s], "name": universe.listings[s].name if s in universe.listings else "",
         "exchange": universe.listings[s].exchange if s in universe.listings else ""}
        for s in all_syms
    ]
    summary = _summarize(tables, cand_matches, gated, events, universe, EXTENDED_SESSIONS)
    manifest: dict[str, object] = {
        "milestone": "M1-B dataset", "status": status, "created_at_utc": now_utc.isoformat(),
        "as_of_utc": as_of.isoformat(), "code_sha": code_sha, "start_date": cfg.start.isoformat(),
        "end_date": cfg.end.isoformat(), "trading_days": [d.isoformat() for d in days],
        "reference_day": first.isoformat(), "feeds": list(FEEDS), "timeframe": "1Min", "adjustment": "raw",
        "reference_close": "SIP 1Day bar close (regular-session official close), split-adjusted on ex-dates",
        "scan_params": asdict(p), "symbol_chunk": cfg.symbol_chunk, "inputs": input_meta,
        "chronological_split": {"oos_fraction": cfg.oos_fraction, "embargo_days": cfg.embargo_days,
                                **chrono.describe()},
        "profitability": "not evaluated: no transaction costs, spreads or non-fills are modelled yet",
        "failed_sessions": failed_sessions, "api_requests_this_run": provider.request_count,
        "cached_fetches_reused": sum(1 for r in fetcher.log if r["status"] == "cached"),
        "summary": summary, "orders_placed": 0,
        "candidate_rows": len(tables["candidate_detail"]),
    }
    return DatasetResult(status, manifest, dict(tables))


def _q(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "median": None, "p25": None, "p75": None}
    v = sorted(values)
    return {"n": len(v), "median": median(v), "p25": v[len(v) // 4], "p75": v[(3 * len(v)) // 4]}


def _summarize(tables, cand_matches, gated, events, universe: Universe, sessions) -> dict[str, object]:  # noqa: ANN001
    out: dict[str, object] = {
        "universe_by_origin": dict(Counter(o.split(":")[0] for o in universe.origin.values())),
        "renames_in_window": len(universe.renames),
    }
    for s in sessions:
        cm = [r for r in cand_matches if r["session"] == s]
        gm = [r for r in gated if r["session"] == s]
        el = [r for r in tables["eligibility"] if r["session"] == s]
        cb = [r for r in tables["coverage_buckets"] if r["session"] == s]
        det = [r for r in tables["candidate_detail"] if r["session"] == s and r["sip_candidate"]]
        sip_vol = sum(int(r["sip_volume"]) for r in cb)
        iex_vol = sum(int(r["iex_volume"]) for r in cb)
        out[s] = {
            "days": len(el),
            "mean_eligible_symbols": sum(int(r["eligible"]) for r in el) / len(el) if el else None,
            "sip_bars": sum(int(r["sip_bars"]) for r in cb),
            "iex_bars": sum(int(r["iex_bars"]) for r in cb),
            "sip_volume": sip_vol, "iex_volume": iex_vol,
            "iex_volume_share": iex_vol / sip_vol if sip_vol else None,
            "candidates": summarize_matches(cm),
            "gated_breakouts": summarize_matches(gm),
            "ungated_breakouts_sip": sum(1 for e in events["sip"]["breakout"] if e.session == s),
            "sip_candidates_non_current_origin": sum(1 for r in det if r["origin"] != "current_listing"),
            "sip_candidates_by_origin": dict(Counter(str(r["origin"]).split(":")[0] for r in det)),
            "by_sample": {
                smp: {"days": len({r["trading_date"] for r in el if r["sample"] == smp}),
                      "candidates": summarize_matches([r for r in cm if r["sample"] == smp]),
                      "gated_breakouts": summarize_matches([r for r in gm if r["sample"] == smp])}
                for smp in (IN_SAMPLE, EMBARGO, OUT_OF_SAMPLE)
            },
            "sip_candidates_split_adjusted": sum(1 for r in det if r["split_adjusted"]),
            "sip_candidate_post_trigger_sip_coverage": _q([float(r["sip_post_trigger_coverage"]) for r in det
                                                          if r["sip_post_trigger_coverage"] is not None]),
            "sip_candidate_post_trigger_iex_coverage": _q([float(r["iex_post_trigger_coverage"]) for r in det
                                                          if r["iex_post_trigger_coverage"] is not None]),
            "sip_candidate_post_trigger_max_gap_minutes": _q([float(r["sip_post_trigger_max_gap_minutes"]) for r in det]),
        }
    return out

