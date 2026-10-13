"""Command line entry point. M1 only: historical market data; this tool never places orders."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .data.alpaca_historical import AlpacaHistoricalProvider
from .data.market_calendar import CalendarCoverageError
from .data.provider import AuthenticationError
from .pipeline import run_m1
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


def _code_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "") if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
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
                        delay=timedelta(minutes=args.delay_minutes), code_sha=_code_sha())
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


if __name__ == "__main__":
    raise SystemExit(main())
