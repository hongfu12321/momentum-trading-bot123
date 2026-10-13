"""M1 run: fetch matched SIP and IEX 1m bars, normalize, compare. Read-only market data; no orders."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

from .compare import (
    Event,
    ScanParams,
    compare_session,
    group_bars,
    match_events,
    missing_interval_rows,
    reference_close,
    regular_closes,
    scan_session,
    summarize_matches,
)
from .data.market_calendar import ET, EXTENDED_SESSIONS, previous_trading_day, session_windows, trading_days
from .data.normalize import normalize
from .data.provider import AuthenticationError, Bar, BarsProvider, BarsRequest, EntitlementError, ProviderError

FEEDS = ("sip", "iex")
DEFAULT_DELAY = timedelta(minutes=16)  # Alpaca Basic: SIP history must be older than 15 minutes

LIMITATIONS = (
    "IEX is a single exchange; its volume is a small fraction of consolidated (SIP) volume and must not be read as market volume.",
    "A missing 1m bar means no qualifying trade on that feed in that minute; it cannot be distinguished from a vendor outage.",
    "Reference close is the last regular-session 1m bar close from the same feed, not the official closing-auction print.",
    "Prices are unadjusted (adjustment=raw); a split or reverse split between the reference close and the session distorts change %.",
    "The symbol list is supplied by the user: no point-in-time universe, delisted names only if supplied; results carry selection and survivorship bias.",
    "Holiday and early-close calendar is a static table for 2023-2026; after-hours on early-close days is modelled as 13:00-17:00 ET.",
    "Float, spread, quotes and news are not used; the scanner and breakout rules are research hypotheses, not a strategy.",
    "Differences reflect both venue coverage and the vendor's bar-construction rules (trade-condition filtering).",
    "Nothing here measures or implies strategy profitability. No orders are placed.",
)


@dataclass(slots=True)
class M1Result:
    status: str
    manifest: dict[str, object]
    tables: dict[str, list[dict[str, object]]] = field(default_factory=dict)


def _chunks(items: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _overall_status(feed_status: dict[str, str]) -> str:
    states = set(feed_status.values())
    if "auth_failed" in states:
        return "auth_failed"
    blocked = [f for f in FEEDS if feed_status[f] == "entitlement_blocked"]
    if len(blocked) == 2:
        return "entitlement_blocked"
    if blocked:
        return f"{blocked[0]}_entitlement_blocked"
    if states & {"partial", "error"}:
        return "partial"
    return "complete"


def run_m1(
    provider: BarsProvider,
    symbols: list[str],
    start: date,
    end: date,
    *,
    now_utc: datetime | None = None,
    delay: timedelta = DEFAULT_DELAY,
    params: ScanParams = ScanParams(),
    adjustment: str = "raw",
    symbol_chunk: int = 100,
    code_sha: str = "unknown",
) -> M1Result:
    now_utc = now_utc or datetime.now(timezone.utc)
    syms = tuple(sorted({s.strip().upper() for s in symbols if s.strip()}))
    if not syms:
        raise ValueError("no symbols given")
    days = trading_days(start, end)
    if not days:
        raise ValueError(f"no trading days between {start} and {end}")
    as_of = now_utc - delay
    last_end = session_windows(days[-1])[EXTENDED_SESSIONS[-1]].end_utc
    if last_end > as_of:
        raise ValueError(
            f"{days[-1]} after-hours ends {last_end.isoformat()}, inside the {delay} delay window before now; "
            "choose an older end date"
        )
    prev_day = {d: previous_trading_day(d) for d in days}
    fetch_days = sorted({prev_day[days[0]], *days})
    windows = {d: session_windows(d) for d in fetch_days}

    raw: list[Bar] = []
    fetch_log: list[dict[str, object]] = []
    feed_status: dict[str, str] = {}
    ok_days: dict[str, set[date]] = {f: set() for f in FEEDS}
    for feed in FEEDS:
        stop: str | None = None
        errors = 0
        for d in fetch_days:
            day_ok = True
            for chunk in _chunks(syms, symbol_chunk):
                w = windows[d]
                req = BarsRequest(chunk, feed, w[EXTENDED_SESSIONS[0]].start_utc, w[EXTENDED_SESSIONS[-1]].end_utc,
                                  adjustment=adjustment)  # type: ignore[arg-type]
                record = {"feed": feed, "trading_date": d.isoformat(), "symbols": ",".join(chunk),
                          "start_utc": req.start_utc.isoformat(), "end_utc": req.end_utc.isoformat(),
                          "status": "skipped", "bars": 0, "http_status": None, "error": None}
                if stop:
                    record["error"] = f"not requested after earlier {stop}"
                    fetch_log.append(record)
                    day_ok = False
                    continue
                try:
                    got = provider.get_bars(req)
                    raw.extend(got)
                    record.update(status="ok", bars=len(got))
                except (EntitlementError, AuthenticationError) as exc:
                    stop = "entitlement_blocked" if isinstance(exc, EntitlementError) else "auth_failed"
                    record.update(status=stop, http_status=exc.status, error=str(exc))
                    day_ok = False
                except ProviderError as exc:
                    errors += 1
                    record.update(status="error", http_status=exc.status, error=str(exc))
                    day_ok = False
                fetch_log.append(record)
            if day_ok:
                ok_days[feed].add(d)
        if stop:
            feed_status[feed] = stop
        elif errors:
            feed_status[feed] = "error" if not ok_days[feed] else "partial"
        else:
            feed_status[feed] = "ok"

    bars, dropped = normalize(raw, windows, as_of_utc=as_of)
    grouped = group_bars(bars)
    status = _overall_status(feed_status)
    compare_days = [d for d in days if all(d in ok_days[f] for f in FEEDS)]

    session_rows: list[dict[str, object]] = []
    missing_rows: list[dict[str, object]] = []
    events: dict[str, dict[str, list[Event]]] = {f: {"candidate": [], "breakout": []} for f in FEEDS}
    for feed in FEEDS:
        per_feed = grouped.get(feed, {})
        closes = regular_closes(per_feed)
        for d in sorted(ok_days[feed] & set(days)):
            for session in EXTENDED_SESSIONS:
                for sym in syms:
                    rows = per_feed.get((sym, d, session), [])
                    missing_rows += missing_interval_rows(windows[d][session], sym, feed, rows)
                    ref = reference_close(sym, d, session, closes, prev_day)
                    cand, brk = scan_session(feed, (sym, d, session), rows, ref, params, windows[d][session].start_utc)
                    if cand and d in compare_days:
                        events[feed]["candidate"].append(cand)
                    if d in compare_days:
                        events[feed]["breakout"] += brk
    for d in compare_days:
        for session in EXTENDED_SESSIONS:
            for sym in syms:
                key = (sym, d, session)
                session_rows.append(compare_session(windows[d][session], sym, grouped.get("sip", {}).get(key, []),
                                                    grouped.get("iex", {}).get(key, [])))

    candidate_matches = match_events(events["sip"]["candidate"], events["iex"]["candidate"], by_minute=False)
    breakout_matches = match_events(events["sip"]["breakout"], events["iex"]["breakout"], by_minute=True)
    gated_breakout_matches = match_events(
        [e for e in events["sip"]["breakout"] if e.candidate_gate],
        [e for e in events["iex"]["breakout"] if e.candidate_gate],
        by_minute=True,
    )

    def totals(session: str) -> dict[str, object]:
        rows = [r for r in session_rows if r["session"] == session]
        keys = ("expected_minutes", "sip_bar_minutes", "iex_bar_minutes", "iex_only_minutes", "sip_volume", "iex_volume")
        out: dict[str, object] = {"symbol_sessions": len(rows)}
        out.update({k: sum(int(r[k]) for r in rows) for k in keys})  # type: ignore[call-overload]
        sip_v, iex_v = int(out["sip_volume"]), int(out["iex_volume"])  # type: ignore[call-overload]
        out["iex_volume_share"] = iex_v / sip_v if sip_v else None
        return out

    summary = {
        "sessions": {s: totals(s) for s in EXTENDED_SESSIONS},
        "candidates": summarize_matches(candidate_matches),
        "breakouts": summarize_matches(breakout_matches),
        "gated_breakouts": summarize_matches(gated_breakout_matches),
        "bars_by_feed": dict(Counter(sb.bar.feed for sb in bars)),
        "dropped_bars": dict(dropped),
    }
    manifest: dict[str, object] = {
        "milestone": "M1",
        "status": status,
        "feed_status": feed_status,
        "created_at_utc": now_utc.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "delay_minutes": delay.total_seconds() / 60,
        "code_sha": code_sha,
        "provider": getattr(provider, "name", type(provider).__name__),
        "symbols": list(syms),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "trading_days": [d.isoformat() for d in days],
        "reference_day_fetched": prev_day[days[0]].isoformat(),
        "compared_days": [d.isoformat() for d in compare_days],
        "timeframe": "1Min",
        "adjustment": adjustment,
        "timezone": str(ET),
        "sessions": {"premarket": "04:00-09:30 ET", "afterhours": "16:00-20:00 ET (13:00-17:00 on early closes)"},
        "scan_params": asdict(params),
        "failures": [r for r in fetch_log if r["status"] not in ("ok",)],
        "summary": summary,
        "limitations": list(LIMITATIONS),
        "orders_placed": 0,
    }
    bar_rows = [
        {
            "symbol": sb.bar.symbol,
            "feed": sb.bar.feed,
            "timestamp_utc": sb.bar.timestamp_utc.isoformat(),
            "timestamp_et": sb.bar.timestamp_utc.astimezone(ET).isoformat(),
            "trading_date": sb.trading_date.isoformat(),
            "session": sb.session,
            "open": sb.bar.open,
            "high": sb.bar.high,
            "low": sb.bar.low,
            "close": sb.bar.close,
            "volume": sb.bar.volume,
            "trade_count": sb.bar.trade_count,
            "vwap": sb.bar.vwap,
            "adjustment": adjustment,
        }
        for sb in bars
    ]
    tables = {
        "fetch_log": fetch_log,
        "bars": bar_rows,
        "session_comparison": session_rows,
        "missing_intervals": missing_rows,
        "candidates": [e.row() for f in FEEDS for e in events[f]["candidate"]],
        "candidate_matches": candidate_matches,
        "breakouts": [e.row() for f in FEEDS for e in events[f]["breakout"]],
        "breakout_matches": breakout_matches,
    }
    return M1Result(status, manifest, tables)
