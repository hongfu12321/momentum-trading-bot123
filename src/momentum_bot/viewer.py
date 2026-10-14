"""Localhost historical replay viewer (Streamlit). Launch with: momentum-bot m2-viewer

Reads only local outputs of m2-backtest and m2-diagnostics, plus the cached SIP bars, for the baseline
strategy (candle_close_confirmation, frozen base_cap50). Ledgers are validated against their recorded
provenance first, and a sample that fails is refused, not shown. It never reruns a backtest, never calls
a network API and has no order, broker or execution code. Everything it shows is a historical
simulation derived from licensed data: keep it local.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from momentum_bot import charts

st.set_page_config(page_title="M2 historical replay", layout="wide")


def _dataset() -> Path:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="reports/datasets/m2_sip_20260603_20261009")
    return Path(p.parse_known_args(sys.argv[1:])[0].dataset)


DATASET = _dataset()


def tables(path: str) -> charts.ReplayTables:
    """Validated ledgers. The size and mtime of every validated file are checked on each rerun; any change
    reloads and re-validates, so files changed on disk are never shown stale."""
    return _load(path, _stamp(path))


def _stamp(path: str) -> tuple:
    """Size and mtime of every file validation reads; any change reloads and re-validates."""
    ds = Path(path)
    files = [ds / "manifest.json", ds / "breakout_matches.csv", ds / "candidates.csv.gz"]
    for smp in charts.SAMPLES:
        files += [ds / f"backtest_summary_{smp}.json", ds / f"diagnostics_{smp}_{charts.SCENARIO}.json",
                  ds / "backtest" / smp / charts.SCENARIO / "trades.csv", ds / "backtest" / smp / charts.SCENARIO / "attempts.csv",
                  charts.ledger_dir(ds, smp) / "signal_ledger.csv", charts.ledger_dir(ds, smp) / "trade_ledger.csv"]
    return tuple((str(f), f.stat().st_size, f.stat().st_mtime_ns) if f.is_file() else (str(f),) for f in files)


@st.cache_resource(show_spinner="Validating and loading ledgers…", max_entries=2)
def _load(path: str, stamp: tuple) -> charts.ReplayTables:
    return charts.ReplayTables.load(Path(path))


@st.cache_data(show_spinner="Loading the session's 1-minute bars…", max_entries=12)
def session_data(path: str, stamp: tuple, d: str, session: str) -> charts.SessionData | None:
    try:
        return tables(path).session(Path(path), d, session)
    except FileNotFoundError:
        return None


def et(series: pd.Series, ms: bool = False) -> pd.Series:
    """UTC ISO strings -> US Eastern clock times, labelled."""
    return series.map(lambda t: charts.et_time(t, ms) if isinstance(t, str) and t else "")


def pending_selection(table_key: str, rows_key: str) -> dict | None:
    """Row picked in a table on the previous run, applied once before the shared selectors are drawn."""
    sel = st.session_state.get(table_key)
    rows = list(getattr(getattr(sel, "selection", None), "rows", None) or (sel or {}).get("selection", {}).get("rows", []))
    if not rows or st.session_state.get(f"_applied_{table_key}") == rows:
        return None
    st.session_state[f"_applied_{table_key}"] = rows
    picked = st.session_state.get(rows_key, [])
    return picked[rows[0]] if rows[0] < len(picked) else None


try:
    STAMP = _stamp(str(DATASET))
    T = tables(str(DATASET))
except (charts.ReplayDataError, OSError, KeyError, ValueError) as exc:
    st.error(f"Cannot show this dataset: {exc}")
    st.stop()

M = T.manifest
split = M["chronological_split"]

# ---------- header: what this is and which data it covers ----------
st.markdown(
    "<div style='background:#b71c1c;color:#fff;padding:8px 14px;border-radius:6px;font-weight:600;display:inline-block'>"
    "HISTORICAL REPLAY — NOT LIVE · simulated fills on cached SIP data · no orders</div>", unsafe_allow_html=True)
st.markdown(f"### Dataset {M['start_date']} → {M['end_date']} ({len(M['trading_days'])} trading days)")
st.caption(f"In-sample {split['in_sample']['first']} → {split['in_sample']['last']} · embargo "
           f"{split['embargo']['first']} · out-of-sample {split['out_of_sample']['first']} → "
           f"{split['out_of_sample']['last']} (report only; never used for tuning) · strategy "
           "`candle_close_confirmation` with the frozen 50 bps configuration · all times US Eastern (ET)")

for chk in T.checks.values():  # never silently drop a sample: say why it is not shown
    if chk.status == "mismatch":
        st.error(f"**{chk.sample} is not shown**: its ledgers do not match their recorded provenance.\n\n- "
                 + "\n- ".join(chk.problems))
    elif chk.status == "absent":
        st.info(f"{chk.sample}: no diagnostics ledgers, so it is not shown. Run m2-backtest and m2-diagnostics "
                "for it to replay it.")
    for note in chk.notes if chk.status == "ok" else []:
        st.caption(f"{chk.sample}: {note}.")
st.sidebar.caption(f"Dataset folder: {DATASET}")

dates = T.dates()
if not dates:
    st.info("No trading dates with ledgers for this selection.")
    st.stop()

# A row picked in the signals or trades table on the last run moves the shared selection first.
for key in ("signals_table", "trades_table"):
    pick = pending_selection(key, f"{key}_rows")
    if pick:
        st.session_state.update(date=pick["trading_date"], session=pick["session"], symbol=pick["symbol"],
                                focus_signal=pick["signal_available_utc"])
if st.session_state.get("date") not in dates:
    st.session_state["date"] = dates[-1]  # latest historical date, never today

# ---------- shared selectors ----------
c1, c2, c3, c4 = st.columns([2, 2, 3, 3])
d = c1.selectbox("Trading date", dates, key="date", format_func=lambda x: f"{x} ({T.sample_of(x).replace('_', '-')})")
session = c2.radio("Session (ET)", charts.SESSIONS, key="session", horizontal=True,
                   format_func={"premarket": "premarket 04:00–09:30", "afterhours": "after hours 16:00–20:00"}.get)
data = session_data(str(DATASET), STAMP, d, session)
symbols = data.chart_symbols if data else []
if st.session_state.get("symbol") not in symbols:
    st.session_state["symbol"] = symbols[0] if symbols else None
sym = c3.selectbox("Stock", symbols, key="symbol", placeholder="no stocks this session",
                   help="Stocks with a signal first, then scanner candidates.")
sample = T.sample_of(d)
c4.markdown(f"**{d}** · {sample.replace('_', '-')}"
            + (" · <span style='color:#b71c1c'>report-only hold-out</span>" if sample == "out_of_sample" else ""),
            unsafe_allow_html=True)

# ---------- daily summary ----------
day = charts.daily_summary(T, d)
m = st.columns(6)
m[0].metric("Signals", day["signals"])
m[1].metric("Entries", day["entries"])
m[2].metric("Completed trades", day["completed_trades"])
m[3].metric("Incomplete exits", day["incomplete_exits"])
m[4].metric("Simulated net P&L (completed)", f"${day['net_usd_completed']:,.2f}")
mark = day["marked_usd_incomplete"]
m[5].metric("Unrealized mark (incomplete)", "—" if not day["incomplete_exits"] else
            ("unknown" if mark is None else f"${mark:,.2f}"))
st.caption("Whole day, both sessions, Original HOS Breakout (base 50 bps). Outcomes: "
           + (", ".join(f"{k} {v}" for k, v in day["outcomes"].items()) or "none")
           + ". Net P&L counts completed exits only; incomplete exits are never added to it.")

replay, chart_tab, trades_tab, overview = st.tabs(["Scanner replay", "Chart", "Trades", "Overview"])

with replay:
    if data is None:
        st.warning(f"No cached SIP bars for {d} {session}: nothing is shown rather than invented.")
    else:
        for w in charts.session_warnings(data):
            st.warning(w)
        st.markdown("**Signals and decisions** — each row shows only what was known at its signal time; "
                    "*outcome* is the simulated result. Select a row to open its stock everywhere.")
        rows = pd.DataFrame(data.signals)
        if rows.empty:
            st.info("No scanner signals in this session.")
        else:
            rows = rows.sort_values("signal_available_utc", kind="stable").reset_index(drop=True)
            f1, f2 = st.columns(2)
            pick_sym = f1.multiselect("Filter stocks", sorted(rows["symbol"].unique()))
            pick_out = f2.multiselect("Filter outcomes", sorted(rows["outcome"].unique()))
            if pick_sym:
                rows = rows[rows["symbol"].isin(pick_sym)]
            if pick_out:
                rows = rows[rows["outcome"].isin(pick_out)]
            rows = rows.reset_index(drop=True)
            st.session_state["signals_table_rows"] = rows[["trading_date", "session", "symbol",
                                                           "signal_available_utc"]].to_dict("records")
            view = pd.DataFrame({
                "signal known (ET)": et(rows["signal_available_utc"]),
                "trigger bar (ET)": et(rows["signal_bar_start_utc"]).str[:5],
                "stock": rows["symbol"],
                "price": rows.get("price"), "change %": pd.to_numeric(rows.get("change_pct"), errors="coerce"),
                "session volume": pd.to_numeric(rows.get("session_volume"), errors="coerce"),
                "volume ratio": pd.to_numeric(rows.get("volume_ratio"), errors="coerce"),
                "spread bps": pd.to_numeric(rows.get("signal_spread_bps"), errors="coerce"),
                "quote age s": pd.to_numeric(rows.get("signal_quote_age_s"), errors="coerce"),
                "quote state": rows.get("signal_quote_state"), "outcome": rows["outcome"], "reason": rows["reason"]})
            st.dataframe(view, hide_index=True, use_container_width=True, key="signals_table", on_select="rerun",
                         selection_mode="single-row",
                         column_config={"change %": st.column_config.NumberColumn(format="%.1f"),
                                        "session volume": st.column_config.NumberColumn(format="%d"),
                                        "volume ratio": st.column_config.NumberColumn(format="%.2f"),
                                        "spread bps": st.column_config.NumberColumn(format="%.1f"),
                                        "quote age s": st.column_config.NumberColumn(format="%.2f")})
            st.caption("Empty spread or quote fields mean no quote was evaluated (skipped) or none was cached; they "
                       "are never estimated. Outcomes: skipped (risk/portfolio rule), rejected (at signal time), "
                       "unfilled, partial, completed, incomplete_exit.")
        st.markdown("**Scanner candidates** — first completed bar at which each stock met the scan rules "
                    "($1–$20, change ≥ 10% premarket / 5% after hours, session volume ≥ 100k).")
        cand = pd.DataFrame(data.candidates)
        if cand.empty:
            st.info("No scanner candidates in this session.")
        else:
            st.dataframe(pd.DataFrame({
                "qualified bar (ET)": et(cand["bar_start_utc"]).str[:5], "known (ET)": et(cand["observed_at_utc"]),
                "stock": cand["symbol"], "price": pd.to_numeric(cand["price"]),
                "change %": pd.to_numeric(cand["change_vs_ref"]) * 100,
                "session volume": pd.to_numeric(cand["cumulative_volume"])}), hide_index=True,
                use_container_width=True, column_config={"change %": st.column_config.NumberColumn(format="%.1f")})

with chart_tab:
    if data is None:
        st.warning(f"No cached SIP bars for {d} {session}.")
    elif not sym:
        st.info("No stock had a signal or met the scanner rules in this session, so there is nothing to chart.")
    else:
        evs = [e for e in charts.chart_events(data, sym) if e["kind"] in ("signal_failed", "signal_filled", "entry_fill",
                                                                          "scanner_candidate")]
        a, b = st.columns([1, 3])
        view = a.radio("View", ["Full session", "Around an event"], horizontal=True,
                       index=1 if st.session_state.get("focus_signal") and evs else 0)
        focus = None
        if view == "Around an event" and evs:
            pre = st.session_state.get("focus_signal")
            default = next((i for i, e in enumerate(evs) if pre and charts.et_time(e["t"])[:5] ==
                            charts.et_time(pd.Timestamp(pre) - pd.Timedelta(minutes=1))[:5]), 0)
            i = b.selectbox("Event", range(len(evs)), index=default,
                            format_func=lambda j: f"{charts.et_time(evs[j]['t'])} · {str(evs[j]['label'])[:110]}")
            t = pd.Timestamp(evs[i]["t"])
            focus = ((t - pd.Timedelta(minutes=15)).isoformat(), (t + pd.Timedelta(minutes=20)).isoformat())
        st.plotly_chart(charts.figure(data, sym, focus), use_container_width=True)
        with st.expander("Recorded events for this stock (exact ET timestamps)"):
            ev = pd.DataFrame(charts.chart_events(data, sym))
            if not ev.empty:
                ev.insert(0, "time (ET)", et(ev["t"], ms=True))
                st.dataframe(ev.drop(columns=[c for c in ("t", "t_end") if c in ev]), hide_index=True,
                             use_container_width=True)
        if st.button("Export this session's charts to standalone HTML"):
            path = charts.export_session(DATASET, d, session, T)
            st.success(f"Wrote {path} (local only; contains licensed market data).")

with trades_tab:
    trades = pd.DataFrame([t for s in charts.SESSIONS for t in T.trades.get((d, s), [])])
    if trades.empty:
        st.info(f"No simulated entries on {d}. Signals may have been skipped, rejected or unfilled; see Scanner replay.")
    else:
        trades = trades.sort_values("entry_first_fill_utc").reset_index(drop=True)
        st.session_state["trades_table_rows"] = trades[["trading_date", "session", "symbol",
                                                        "signal_available_utc"]].to_dict("records")
        num = lambda c: pd.to_numeric(trades[c], errors="coerce")  # noqa: E731
        st.dataframe(pd.DataFrame({
            "session": trades["session"], "stock": trades["symbol"], "signal known (ET)": et(trades["signal_available_utc"]),
            "entry fill (ET)": et(trades["entry_first_fill_utc"], ms=True), "entry price": num("entry_price"),
            "shares": num("filled_qty"), "exit": trades["exit_reason"], "exit fill (ET)": et(trades["exit_last_fill_utc"], ms=True),
            "exit price": num("exit_price"), "outcome": trades["outcome"], "R": num("r_multiple"),
            "net $ (completed)": num("net_usd"), "unsold shares": num("remaining_qty"), "mark $ (unrealized)": num("marked_usd"),
            "MFE R": num("mfe_r"), "MAE R": num("mae_r"), "spread cost $": num("spread_cost_usd")}),
            hide_index=True, use_container_width=True, key="trades_table", on_select="rerun", selection_mode="single-row",
            column_config={c: st.column_config.NumberColumn(format="%.2f") for c in ("R", "net $ (completed)",
                                                                                  "mark $ (unrealized)", "MFE R",
                                                                                  "MAE R", "spread cost $")})
        st.caption("Select a trade to open it on the Chart tab. Empty R and net $ mark an incomplete exit; its unsold "
                   "shares and unrealized mark are shown apart. MFE/MAE are post-entry diagnostics, not entry filters.")
        on_stock = trades[(trades["symbol"] == sym) & (trades["session"] == session)] if sym else trades.iloc[:0]
        for _, tr in on_stock.iterrows():
            with st.expander(f"{sym} trade, signal {charts.et_time(tr['signal_available_utc'])}: decision trace"):
                trace = [r for r in data.signals if r["symbol"] == sym] if data else []
                st.dataframe(pd.DataFrame([{"signal known (ET)": charts.et_time(r["signal_available_utc"]),
                                            "outcome": r["outcome"], "reason": r["reason"]} for r in trace]),
                             hide_index=True)
                st.json({k: (None if pd.isna(v) else v) for k, v in tr.items()}, expanded=False)

with overview:
    rows = []
    for smp in charts.SAMPLES:
        if T.checks[smp].status != "ok":
            continue
        r = charts.read_json(DATASET / f"backtest_summary_{smp}.json").get("results", {}).get(charts.SCENARIO, {}).get("all")
        if r:
            rows.append({"sample": smp, "signals": r["signals"], "entries": r["entries"], "completed": r["trades"],
                         "incomplete exits": r["incomplete_exits"]["count"], "fill rate": r["fill_rate"],
                         "win rate": r["win_rate"], "avg R": r["expectancy_r"], "net $": r["net_usd"],
                         "profit factor $": r["profit_factor"], "max drawdown $": r["max_drawdown_usd"]})
    st.markdown("**Baseline backtest (frozen base 50 bps), from `backtest_summary_*.json`** — validated samples only")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    for smp in charts.SAMPLES:
        dg = T.checks[smp].diagnostics
        pv = dg.get("provenance", {})
        if T.checks[smp].status == "ok" and pv:
            st.caption(f"{smp}: diagnostics generated by code `{dg.get('code_sha')}` at {dg.get('created_at_utc')} from "
                       f"backtest run `{pv['backtest_run']['code_sha']}` ({pv['backtest_run']['created_at_utc']}); "
                       f"input hashes verified now ({pv.get('hash_policy') or 'legacy raw-bytes hashes'}). Full "
                       f"diagnostics dashboard: {charts.ledger_dir(DATASET, smp) / 'dashboard.html'}")
