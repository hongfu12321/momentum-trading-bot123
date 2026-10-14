"""Command line entry point. Historical market data and offline simulation only; this tool never places orders."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import backtest, diagnostics, quotes, research
from .data.alpaca_assets import AlpacaPaperAssets
from .data.alpaca_historical import AlpacaHistoricalProvider
from .data.market_calendar import CalendarCoverageError
from .data.provider import AuthenticationError, EntitlementError
from .dataset import DatasetConfig, build_dataset
from .dataset_report import write_dataset
from .pipeline import run_m1
from .provenance import code_version
from .report import write_outputs

EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, EXIT_BLOCKED = 0, 1, 2, 3
EXIT_MISMATCH = 4  # m2-viewer-check: the viewer would show something the ledgers do not support


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal KEY=VALUE loader; existing environment variables take precedence."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _symbols(args: argparse.Namespace) -> list[str]:
    syms = [s for s in (args.symbols or "").split(",") if s.strip()]
    if args.symbols_file:
        text = Path(args.symbols_file).read_text(encoding="utf-8")
        syms += [s for s in text.replace(",", "\n").split() if not s.startswith("#")]
    return syms


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="momentum-bot", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    m1 = sub.add_parser("m1-validate", help="Fetch historical SIP and IEX 1m bars and write a comparison report.")
    m1.add_argument("--symbols", help="Comma-separated tickers, e.g. AAPL,SOUN,MARA")
    m1.add_argument("--symbols-file", help="File of tickers (whitespace/comma separated, # comments)")
    m1.add_argument("--start", required=True, type=date.fromisoformat, help="First date, YYYY-MM-DD (ET)")
    m1.add_argument("--end", required=True, type=date.fromisoformat, help="Last date, YYYY-MM-DD (ET)")
    m1.add_argument("--out-dir", default="reports/runs", help="Parent directory for the run folder")
    m1.add_argument("--delay-minutes", type=float, default=16.0, help="Required age of the newest bar (SIP delay window)")
    ds = sub.add_parser("m1-dataset", help="Build a multi-day broad-universe SIP/IEX extended-hours dataset.")
    ds.add_argument("--start", required=True, type=date.fromisoformat, help="First date, YYYY-MM-DD (ET)")
    ds.add_argument("--end", required=True, type=date.fromisoformat, help="Last date, YYYY-MM-DD (ET)")
    ds.add_argument("--out-dir", required=True, help="Dataset folder; rerunning on the same folder reuses its inputs and cache")
    ds.add_argument("--delay-minutes", type=float, default=16.0, help="Required age of the newest bar (SIP delay window)")
    ds.add_argument("--no-alpaca-assets", action="store_true",
                    help="Skip the read-only paper /v2/assets lookup of inactive and OTC symbols")
    ds.add_argument("--oos-fraction", type=float, default=1 / 3, help="Most recent share of trading days held out")
    ds.add_argument("--embargo-days", type=int, default=1, help="Trading days dropped between in- and out-of-sample")
    qp = sub.add_parser("m2-quote-probe", help="Validate historical SIP quote availability on sampled candidates.")
    qp.add_argument("--dataset", required=True, help="Dataset folder built by m1-dataset")
    qp.add_argument("--sample", type=int, default=60, help="Candidates to sample, split evenly by session")
    qp.add_argument("--minutes", type=int, default=30, help="Quote window after each trigger bar")
    qp.add_argument("--seed", type=int, default=20261013, help="Sampling seed")
    rs = sub.add_parser("m2-research", help="Top 5 (cached universe) variant vs the baseline, in-sample only (no orders).")
    rs.add_argument("--dataset", required=True, help="Dataset folder built by m1-dataset, with references.csv.gz")
    rs.add_argument("--skip-build", action="store_true", help="Reuse research/in_sample rankings and signal sets")
    rs.add_argument("--fetch-missing-quotes", action="store_true",
                    help="Allow SIP quote downloads for variant signals not in the quote cache (default: cache only)")
    bi = sub.add_parser("m2-bullflag-intrabar",
                        help="Bull Flag intrabar breakout research, in-sample, cache-only, read-only (no orders).")
    bi.add_argument("--dataset", required=True, help="Dataset folder with references.csv.gz")
    bi.add_argument("--out-dir", default="research_out/bull_flag_intrabar",
                    help="Per-setup and per-trade outputs (local, git-ignored); never inside the dataset")
    bi.add_argument("--summary", default="reports/research_program/bull_flag_intrabar_summary.json",
                    help="Aggregate, symbol-free summary (committed)")
    bt = sub.add_parser("m2-backtest", help="Simulate the breakout strategy against historical SIP quotes (no orders).")
    bt.add_argument("--dataset", required=True, help="Dataset folder built by m1-dataset")
    bt.add_argument("--sample", choices=("in_sample", "out_of_sample"), default="in_sample")
    bt.add_argument("--scenarios", default="idealized,base,stress", help=f"Comma-separated: {','.join(backtest.SCENARIOS)}")
    bt.add_argument("--spread-caps", default="50",
                    help="Comma-separated entry spread caps in bps; each capped scenario runs once per cap")
    dg = sub.add_parser("m2-diagnostics", help="Per-signal/per-trade diagnostics of a backtest run (cache only, no network).")
    dg.add_argument("--dataset", required=True, help="Dataset folder with backtest/ outputs")
    dg.add_argument("--sample", choices=("in_sample", "out_of_sample"), default="in_sample")
    dg.add_argument("--scenario", default="base_cap50", help="Backtest scenario folder, e.g. base_cap50 (the frozen configuration)")
    dg.add_argument("--confirm-out-of-sample", action="store_true",
                    help="Required for out_of_sample: report only, never use it to choose filters or parameters")
    bt.add_argument("--confirm-out-of-sample", action="store_true",
                    help="Required for --sample out_of_sample: the hold-out should be evaluated once, with frozen configs")
    ch = sub.add_parser("m2-chart", help="Export one session's annotated baseline replay charts to a standalone local HTML file.")
    ch.add_argument("--dataset", required=True, help="Dataset folder with m2-diagnostics outputs")
    ch.add_argument("--date", required=True, help="Trading date, YYYY-MM-DD")
    ch.add_argument("--session", choices=("premarket", "afterhours"), default="premarket")
    vc = sub.add_parser("m2-viewer-check", help="Audit what the replay viewer shows against the backtest ledgers (offline).")
    vc.add_argument("--dataset", default="reports/datasets/m2_sip_20260603_20261009", help="Dataset folder")
    bk = sub.add_parser("dataset-backup", help="Snapshot a dataset to a private rclone remote (dry run unless --confirm).")
    bk.add_argument("--dataset", required=True, help="Dataset folder, e.g. reports/datasets/m2_sip_20260603_20261009")
    bk.add_argument("--remote", required=True, help="rclone remote and folder, e.g. gdrive:trading-research")
    bk.add_argument("--confirm", action="store_true", help="Upload. Without it, only the plan and size are printed")
    rt = sub.add_parser("dataset-restore", help="Download and verify a snapshot into a new folder (never overwrites).")
    rt.add_argument("--snapshot", required=True, help="Snapshot id from dataset-list")
    rt.add_argument("--remote", required=True, help="rclone remote and folder, e.g. gdrive:trading-research")
    rt.add_argument("--destination", required=True, help="New dataset folder; must not exist")
    ls = sub.add_parser("dataset-list", help="List dataset snapshots on a remote, complete or not.")
    ls.add_argument("--remote", required=True, help="rclone remote and folder, e.g. gdrive:trading-research")
    vf = sub.add_parser("dataset-verify", help="Verify a dataset folder against snapshot checksums (offline).")
    vf.add_argument("--dataset", required=True, help="Dataset folder")
    vf.add_argument("--checksums", help="checksums.json; default <dataset>/.snapshot/checksums.json")
    vw = sub.add_parser("m2-viewer", help="Launch the localhost historical replay viewer (Streamlit, 127.0.0.1 only).")
    vw.add_argument("--dataset", default="reports/datasets/m2_sip_20260603_20261009", help="Dataset folder")
    vw.add_argument("--port", type=int, default=8501)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
    if args.command == "m1-dataset":
        return _dataset(args)
    if args.command == "m2-quote-probe":
        return _quote_probe(args)
    if args.command == "m2-research":
        return _research(args)
    if args.command == "m2-bullflag-intrabar":
        return _bullflag_intrabar(args)
    if args.command == "m2-backtest":
        return _backtest(args)
    if args.command == "m2-diagnostics":
        return _diagnostics(args)
    if args.command == "m2-chart":
        return _chart(args)
    if args.command == "m2-viewer":
        return _viewer(args)
    if args.command == "m2-viewer-check":
        return _viewer_check(args)
    if args.command.startswith("dataset-"):
        return _dataset_snapshot(args)
    symbols = _symbols(args)
    if not symbols:
        print("error: provide --symbols or --symbols-file", file=sys.stderr)
        return EXIT_USAGE
    try:
        provider = AlpacaHistoricalProvider.from_env()
    except AuthenticationError as exc:
        print(f"error: {exc}. See .env.example.", file=sys.stderr)
        return EXIT_USAGE
    now = datetime.now(timezone.utc)
    try:
        result = run_m1(provider, symbols, args.start, args.end, now_utc=now,
                        delay=timedelta(minutes=args.delay_minutes), code_sha=code_version())
    except (ValueError, CalendarCoverageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    out_dir = Path(args.out_dir) / f"m1_{now.strftime('%Y%m%dT%H%M%SZ')}"
    report = write_outputs(result, out_dir)
    print(f"status: {result.status} ({provider.request_count} API requests, 0 orders)")
    print(f"report: {report}")
    if result.status == "complete":
        return EXIT_OK
    if result.status == "partial":
        return EXIT_PARTIAL
    return EXIT_BLOCKED


def _dataset(args: argparse.Namespace) -> int:
    try:
        provider = AlpacaHistoricalProvider.from_env()
        assets = None if args.no_alpaca_assets else AlpacaPaperAssets.from_env()
        cfg = DatasetConfig(args.start, args.end, delay=timedelta(minutes=args.delay_minutes),
                            oos_fraction=args.oos_fraction, embargo_days=args.embargo_days)
        result = build_dataset(provider, cfg, Path(args.out_dir), code_sha=code_version(), assets_reader=assets)
    except AuthenticationError as exc:
        print(f"error: {exc}. See .env.example.", file=sys.stderr)
        return EXIT_USAGE
    except (ValueError, CalendarCoverageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    report = write_dataset(result, Path(args.out_dir))
    print(f"status: {result.status} ({provider.request_count} API requests, 0 orders)")
    print(f"report: {report}")
    return {"complete": EXIT_OK, "partial": EXIT_PARTIAL}.get(result.status, EXIT_BLOCKED)


def _quote_probe(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    detail = dataset / "candidate_detail.csv"
    if not detail.is_file():
        print(f"error: {detail} not found; build the dataset first", file=sys.stderr)
        return EXIT_USAGE
    try:
        provider = AlpacaHistoricalProvider.from_env()
    except AuthenticationError as exc:
        print(f"error: {exc}. See .env.example.", file=sys.stderr)
        return EXIT_USAGE
    with detail.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    picked = quotes.sample_candidates(rows, args.sample, args.seed)
    stats = quotes.probe(provider, picked, args.minutes, dataset / "cache" / "quotes")
    total = sum(1 for r in rows if r["sip_candidate"] == "True")
    summary = {"dataset": str(dataset), "sample": args.sample, "seed": args.seed, "code_sha": code_version(),
               "created_at_utc": datetime.now(timezone.utc).isoformat(), "feed": "sip", "orders_placed": 0,
               **quotes.summarize_probe(stats, total, args.minutes)}
    path = quotes.write_probe(dataset / "quote_probe", stats, summary, dataset / "quote_probe_summary.json")
    status = summary["status_counts"]
    print(f"quote windows: {status} ({provider.request_count} API requests, 0 orders)")
    print(f"summary: {path}")
    return EXIT_BLOCKED if "entitlement_blocked" in status else EXIT_OK  # type: ignore[operator]


def _research(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    if not (dataset / "references.csv.gz").is_file():
        print(f"error: {dataset / 'references.csv.gz'} not found; rerun m1-dataset (cache only) to write it",
              file=sys.stderr)
        return EXIT_USAGE
    provider = diagnostics.CacheOnlySource()  # default: no network; a cache miss fails the run explicitly
    if args.fetch_missing_quotes:
        try:
            provider = AlpacaHistoricalProvider.from_env()
        except AuthenticationError as exc:
            print(f"error: {exc}. See .env.example.", file=sys.stderr)
            return EXIT_USAGE
    sample = research.IN_SAMPLE  # exploratory variants never touch the inspected hold-out
    if not args.skip_build:
        print(research.build(dataset, sample, log=print))
    cache = dataset / "cache" / "backtest_quotes"
    blocked: dict[str, dict[str, int]] = {}
    try:
        results = research.run_backtests(dataset, backtest.QuoteStore(provider, cache),  # type: ignore[arg-type]
                                         backtest.QuoteStore(diagnostics.CacheOnlySource(), cache), sample,
                                         blocked=blocked)
    except (EntitlementError, AuthenticationError) as exc:
        print(f"error: SIP quotes blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except diagnostics.CacheMiss as exc:
        print(f"error: {exc}; rerun with --fetch-missing-quotes to download them (network)", file=sys.stderr)
        return EXIT_BLOCKED
    for k, cov in blocked.items():
        print(f"{k}: not backtested; quotes for {cov['missing']} of {cov['signals']} signals are not cached "
              "(rerun with --fetch-missing-quotes to download them)")
    for k in [k for k in research.STRATEGIES[1:] if k in results]:
        summary = {"dataset": str(dataset), "code_sha": code_version(), "orders_placed": 0, "network_requests": 0,
                   "created_at_utc": datetime.now(timezone.utc).isoformat(),
                   "provenance_variant": research.variant_provenance(dataset, sample, k),
                   **diagnostics.run(dataset, sample, research.SCENARIO, k)}
        stem = f"diagnostics_{sample}_{k}_{research.SCENARIO}"
        (dataset / f"{stem}.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        (dataset / f"{stem}.md").write_text(diagnostics.render_report(summary), encoding="utf-8")
    research.write_table(dataset / "research" / sample / "decisions.csv.gz", research.decisions(dataset, sample))
    comparison = {"dataset": str(dataset), "code_sha": code_version(),
                  "created_at_utc": datetime.now(timezone.utc).isoformat(),
                  "quote_api_requests": provider.request_count, **research.compare(dataset, results, sample, blocked)}
    stem = f"research_comparison_{sample}"
    (dataset / f"{stem}.json").write_text(json.dumps(comparison, indent=2, default=str) + "\n", encoding="utf-8")
    (dataset / f"{stem}.md").write_text(research.render_comparison(comparison), encoding="utf-8")
    for k, v in comparison["strategies"].items():  # type: ignore[union-attr]
        if "results" not in v:
            continue
        r = v["results"]["all"]
        print(f"{k}: {r['trades']} trades, expectancy {r['expectancy_r']} R, net ${r['net_usd']:.2f}")
    print(f"comparison: {dataset / (stem + '.md')} ({provider.request_count} quote API requests, 0 orders)")
    return EXIT_OK


def _bullflag_intrabar(args: argparse.Namespace) -> int:
    from . import bullflag_intrabar

    dataset, out = Path(args.dataset).resolve(), Path(args.out_dir).resolve()
    if dataset == out or dataset in out.parents:
        print("error: --out-dir must be outside the dataset folder (the dataset is read-only)", file=sys.stderr)
        return EXIT_USAGE
    if not (dataset / "references.csv.gz").is_file():
        print(f"error: {dataset / 'references.csv.gz'} not found", file=sys.stderr)
        return EXIT_USAGE
    result = {"dataset": Path(args.dataset).as_posix(), "code_sha": code_version(),
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              **bullflag_intrabar.run_research(dataset, out)}
    path = Path(args.summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    for k, v in result["strategies"].items():  # type: ignore[union-attr]
        b = v["base"]
        print(f"{k}: {b['setups_detected']} setups, {b['entries']} entries, {b['completed_trades']} completed, "
              f"net ${b['net_usd']:.2f}, NBBO-covered setups {v['quote_coverage']['nbbo_covered']}")
    print(f"summary: {path} (inputs unchanged: {result['inputs_unchanged']}; 0 network requests, 0 orders)")
    return EXIT_OK if result["inputs_unchanged"] else EXIT_MISMATCH


def _backtest(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    matches = dataset / "breakout_matches.csv"
    if not matches.is_file():
        print(f"error: {matches} not found; build the dataset first", file=sys.stderr)
        return EXIT_USAGE
    if args.sample == "out_of_sample" and not args.confirm_out_of_sample:
        print("error: out-of-sample runs need --confirm-out-of-sample (evaluate the hold-out once)", file=sys.stderr)
        return EXIT_USAGE
    try:
        caps = [float(c) for c in args.spread_caps.split(",")]
        scenarios = backtest.with_spread_caps([backtest.SCENARIOS[n] for n in args.scenarios.split(",")], caps)
        provider = AlpacaHistoricalProvider.from_env()
    except (KeyError, ValueError) as exc:
        print(f"error: bad --scenarios or --spread-caps: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except AuthenticationError as exc:
        print(f"error: {exc}. See .env.example.", file=sys.stderr)
        return EXIT_USAGE
    with matches.open(newline="", encoding="utf-8") as fh:
        signals = backtest.signals_from_breakouts(csv.DictReader(fh), {args.sample})
    store = backtest.QuoteStore(provider, dataset / "cache" / "backtest_quotes")
    strat, risk = backtest.StrategyConfig(), backtest.RiskConfig()
    summary: dict[str, object] = {
        "dataset": str(dataset), "sample": args.sample, "code_sha": code_version(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "feed": "sip", "orders_placed": 0,
        "signals": len(signals), "config": backtest.config_record(strat, risk, scenarios), "results": {},
        "caveats": "Simulated fills against historical SIP NBBO; not evidence of live or paper fill quality. "
                   "No queue position, hidden liquidity, halts or venue rules. Survivorship bias as in the dataset report.",
    }
    try:
        for cfg in scenarios:
            res = backtest.run_backtest(signals, store, cfg, strat, risk)
            out = dataset / "backtest" / args.sample / cfg.name  # per-trade rows are licensed-data derived: local only
            backtest.write_rows(out / "trades.csv", res.trades)
            backtest.write_rows(out / "attempts.csv", res.attempts)
            summary["results"][cfg.name] = backtest.summarize(res)  # type: ignore[index]
            s = summary["results"][cfg.name]["all"]  # type: ignore[index]
            print(f"{cfg.name}: {s['trades']} trades, fill rate {s['fill_rate']}, net ${s['net_usd']:.2f}")
    except (EntitlementError, AuthenticationError) as exc:
        print(f"error: SIP quotes blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    if args.sample == "in_sample":
        summary["spread_cap_selection"] = backtest.select_spread_cap(summary["results"], caps)  # type: ignore[arg-type]
        print(f"selected spread cap (in-sample rule): {summary['spread_cap_selection']}")
    path = dataset / f"backtest_summary_{args.sample}.json"
    path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"summary: {path} ({provider.request_count} API requests, 0 orders)")
    return EXIT_OK


def _diagnostics(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    if args.sample == "out_of_sample" and not args.confirm_out_of_sample:
        print("error: out-of-sample diagnostics need --confirm-out-of-sample (report only; no tuning)", file=sys.stderr)
        return EXIT_USAGE
    try:  # refuse stale, edited or mismatched inputs before producing any report
        provenance = diagnostics.validate_inputs(dataset, args.sample, args.scenario)
    except diagnostics.InputMismatch as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    summary = {"dataset": dataset.as_posix(), "code_sha": code_version(), "orders_placed": 0, "network_requests": 0,
               "created_at_utc": datetime.now(timezone.utc).isoformat(), "provenance": provenance,
               **diagnostics.run(dataset, args.sample, args.scenario)}
    ledgers = dataset / "diagnostics" / args.sample / args.scenario  # hashed so the replay viewer refuses edited ledgers
    summary["ledgers_sha256"] = {n: diagnostics.sha256_of(ledgers / n) for n in ("signal_ledger.csv", "trade_ledger.csv")}
    stem = f"diagnostics_{args.sample}_{args.scenario}"
    (dataset / f"{stem}.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    (dataset / f"{stem}.md").write_text(diagnostics.render_report(summary), encoding="utf-8")
    print(f"{summary['trades']} trades diagnosed; aggregate report: {dataset / (stem + '.md')}")
    print(f"local ledgers and dashboard: {dataset / 'diagnostics' / args.sample / args.scenario}")
    return EXIT_OK


def _chart(args: argparse.Namespace) -> int:
    from . import charts  # plotly is an optional dependency: pip install -e ".[viewer]"

    try:
        path = charts.export_session(Path(args.dataset), args.date, args.session)
    except (FileNotFoundError, ValueError) as exc:  # includes charts.ReplayDataError (refused provenance)
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"charts: {path} (local only: contains licensed market data; do not commit or publish)")
    return EXIT_OK


def _viewer_check(args: argparse.Namespace) -> int:
    from . import charts

    dataset = Path(args.dataset)
    try:
        tables = charts.ReplayTables.load(dataset)
        report = charts.audit(dataset, tables)
    except (FileNotFoundError, ValueError) as exc:  # refused provenance, ambiguous or edited bar files
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    for smp, chk in tables.checks.items():
        print(f"{smp}: {chk.status}" + "".join(f"\n  problem: {x}" for x in chk.problems)
              + "".join(f"\n  warning: {x}" for x in chk.warnings) + "".join(f"\n  note: {x}" for x in chk.notes))
    for smp, r in report["samples"].items():  # type: ignore[union-attr]
        if r["status"] == "ok":
            v = r["viewer_ledgers"]
            print(f"{smp}: {r['dates']} dates; signals {v['signals']}, entries {v['entries']}, completed {v['completed']}, "
                  f"incomplete {v['incomplete']}, net (completed) ${v['net_usd_completed']:.2f}, realized (incomplete) "
                  f"${v['realized_usd_incomplete']:.2f}, marked (incomplete) ${v['marked_usd_incomplete']:.2f}")
    print(f"sessions {report['sessions']}; markers checked {report['markers_checked']} {report['markers']}")
    print(f"mismatches: {report['mismatch_count']}" + "".join(f"\n  {x}" for x in report["mismatches"]))  # type: ignore[union-attr]
    path = dataset / "viewer_check.json"  # names symbols in mismatches: local, git-ignored with the dataset folder
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"report: {path} (0 network requests, 0 orders)")
    return EXIT_OK if not report["mismatch_count"] else EXIT_MISMATCH


def _viewer(args: argparse.Namespace) -> int:
    import subprocess

    app = Path(__file__).with_name("viewer.py")
    cmd = [sys.executable, "-m", "streamlit", "run", str(app), "--server.address", "127.0.0.1",
           "--server.port", str(args.port), "--browser.gatherUsageStats", "false", "--", "--dataset", args.dataset]
    return subprocess.call(cmd)


def _dataset_snapshot(args: argparse.Namespace) -> int:
    from . import backup as bk

    try:
        if args.command == "dataset-verify":
            problems = bk.verify_dataset(Path(args.dataset), Path(args.checksums) if args.checksums else None)
            print("\n".join(problems) if problems else f"{args.dataset}: every file matches the snapshot checksums")
            return EXIT_OK if not problems else EXIT_MISMATCH
        if args.command == "dataset-list":
            for r in bk.list_snapshots(args.remote, bk.transport_for(args.remote)):
                print(f"{r['dataset_name']}  {r['snapshot_id']}  {'COMPLETE' if r['complete'] else 'INCOMPLETE'}  "
                      f"{r['files']} files  {int(r['bytes']) / 1e6:,.1f} MB")
            return EXIT_OK
        if args.command == "dataset-restore":
            bk.restore(args.remote, args.snapshot, Path(args.destination), bk.transport_for(args.remote))
            return EXIT_OK
        plan = bk.plan_backup(Path(args.dataset), args.remote, commit=bk.source_commit(Path(__file__).parents[2]))
        print(f"snapshot {plan.snapshot_id}: {plan.manifest['file_count']} files, "
              f"{plan.inventory.total_bytes / 1e6:,.1f} MB -> {plan.remote_dir}")
        print(f"excluded: {plan.inventory.excluded or 'nothing'}; source commit {plan.manifest['source_commit']}")
        if not args.confirm:
            print("dry run: nothing uploaded. Re-run with --confirm to upload this snapshot.")
            return EXIT_OK
        bk.backup(plan, bk.transport_for(args.remote))
        return EXIT_OK
    except bk.BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PARTIAL


if __name__ == "__main__":
    raise SystemExit(main())
