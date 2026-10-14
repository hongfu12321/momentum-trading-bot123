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
    if args.command == "m2-backtest":
        return _backtest(args)
    if args.command == "m2-diagnostics":
        return _diagnostics(args)
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
    try:
        provider = AlpacaHistoricalProvider.from_env()
    except AuthenticationError as exc:
        print(f"error: {exc}. See .env.example.", file=sys.stderr)
        return EXIT_USAGE
    sample = research.IN_SAMPLE  # exploratory variants never touch the inspected hold-out
    if not args.skip_build:
        print(research.build(dataset, sample, log=print))
    cache = dataset / "cache" / "backtest_quotes"
    try:
        results = research.run_backtests(dataset, backtest.QuoteStore(provider, cache),
                                         backtest.QuoteStore(diagnostics.CacheOnlySource(), cache), sample)  # type: ignore[arg-type]
    except (EntitlementError, AuthenticationError) as exc:
        print(f"error: SIP quotes blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    for k in research.STRATEGIES[1:]:
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
                  "quote_api_requests": provider.request_count, **research.compare(dataset, results, sample)}
    stem = f"research_comparison_{sample}"
    (dataset / f"{stem}.json").write_text(json.dumps(comparison, indent=2, default=str) + "\n", encoding="utf-8")
    (dataset / f"{stem}.md").write_text(research.render_comparison(comparison), encoding="utf-8")
    for k, v in comparison["strategies"].items():  # type: ignore[union-attr]
        r = v["results"]["all"]
        print(f"{k}: {r['trades']} trades, expectancy {r['expectancy_r']} R, net ${r['net_usd']:.2f}")
    print(f"comparison: {dataset / (stem + '.md')} ({provider.request_count} quote API requests, 0 orders)")
    return EXIT_OK


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
    stem = f"diagnostics_{args.sample}_{args.scenario}"
    (dataset / f"{stem}.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    (dataset / f"{stem}.md").write_text(diagnostics.render_report(summary), encoding="utf-8")
    print(f"{summary['trades']} trades diagnosed; aggregate report: {dataset / (stem + '.md')}")
    print(f"local ledgers and dashboard: {dataset / 'diagnostics' / args.sample / args.scenario}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
