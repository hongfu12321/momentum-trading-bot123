"""Command line entry point. M1 only: historical market data; this tool never places orders."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import quotes
from .data.alpaca_assets import AlpacaPaperAssets
from .data.alpaca_historical import AlpacaHistoricalProvider
from .data.market_calendar import CalendarCoverageError
from .data.provider import AuthenticationError
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
    if args.command == "m1-dataset":
        return _dataset(args)
    if args.command == "m2-quote-probe":
        return _quote_probe(args)
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


if __name__ == "__main__":
    raise SystemExit(main())
