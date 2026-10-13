"""Command line entry point. M1 only: historical market data; this tool never places orders."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
    if args.command == "m1-dataset":
        return _dataset(args)
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
        cfg = DatasetConfig(args.start, args.end, delay=timedelta(minutes=args.delay_minutes))
        result = build_dataset(provider, cfg, Path(args.out_dir), code_sha=code_version())
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


if __name__ == "__main__":
    raise SystemExit(main())
