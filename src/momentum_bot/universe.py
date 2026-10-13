"""Approximate point-in-time symbol universe.

There is no free point-in-time US listing history, so the universe is reconstructed:

1. Base: a dated snapshot of the Nasdaq Trader symbol directories (all US exchange listings
   *today*), filtered to common-stock-like issues.
2. Add back symbols that disappeared since the window start, from Alpaca corporate actions
   (cash/stock-merger acquirees, worthless removals, pre-rename symbols).
3. Renames: Alpaca serves a renamed ticker's whole history under the new symbol, so on each
   date exactly one of (old, new) is used: old before the rename's process date, new on/after.

Residual bias: exchange delistings with no corporate action (e.g. compliance delistings to OTC)
are not recoverable from these sources and are missing. Classification uses today's names.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

NON_COMMON = re.compile(
    r"\b(warrants?|rights?|units?|preferred|preference|notes?|debentures?|bonds?|trust preferred|"
    r"depositary shares? representing|percent|%|subordinated|when issued|contingent value)\b",
    re.IGNORECASE,
)
DIRECTORY_FILES = ("nasdaqlisted", "otherlisted")
DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/{name}.txt"
DELISTING_TYPES = ("cash_mergers", "stock_mergers", "worthless_removals")
SPLIT_TYPES = ("forward_splits", "reverse_splits")
CORPORATE_ACTION_TYPES = "cash_merger,stock_merger,worthless_removal,name_change,forward_split,reverse_split"


@dataclass(frozen=True, slots=True)
class Listing:
    symbol: str
    name: str
    exchange: str
    is_etf: bool
    is_test: bool

    @property
    def common_like(self) -> bool:
        return not self.is_etf and not self.is_test and not NON_COMMON.search(self.name)


def _rows(text: str) -> list[dict[str, str]]:
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    header = lines[0].split("|")
    return [dict(zip(header, ln.split("|"))) for ln in lines[1:]]


def directory_created(text: str) -> str:
    """The 'File Creation Time' footer, e.g. '1013202612:11' (MMDDYYYYHH:MM)."""
    last = text.strip().splitlines()[-1]
    return last.split(":", 1)[1].split("|")[0].strip() if last.startswith("File Creation Time") else "unknown"


def parse_directory(nasdaq_listed: str, other_listed: str) -> list[Listing]:
    out = [
        Listing(r["Symbol"], r["Security Name"], "NASDAQ", r["ETF"] == "Y", r["Test Issue"] == "Y")
        for r in _rows(nasdaq_listed)
    ]
    out += [
        Listing(r["ACT Symbol"], r["Security Name"], r["Exchange"], r["ETF"] == "Y", r["Test Issue"] == "Y")
        for r in _rows(other_listed)
    ]
    return out


def _plain(symbol: str) -> bool:
    """Exchange-style ticker (letters, optional .class); excludes CUSIP-like and preferred ($) forms."""
    return bool(re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", symbol or ""))


@dataclass(frozen=True, slots=True)
class Split:
    symbol: str
    ex_date: date
    old_rate: float
    new_rate: float

    @property
    def price_factor(self) -> float:
        """Multiply a pre-split raw price by this to compare it with post-split raw prices."""
        return self.old_rate / self.new_rate


@dataclass(slots=True)
class Universe:
    origin: dict[str, str]  # symbol -> current_listing | delisted:<type>@date | renamed_to:<new>@date
    listings: dict[str, Listing]
    delisted_on: dict[str, date] = field(default_factory=dict)
    renames: list[tuple[str, str, date]] = field(default_factory=list)  # (old, new, process_date)
    splits: dict[tuple[str, date], Split] = field(default_factory=dict)

    def symbols_for(self, d: date) -> list[str]:
        hidden = {new for old, new, p in self.renames if d < p and old in self.origin}
        # A pre-rename ticker that is listed again today belongs to a different issuer: keep it.
        hidden |= {old for old, new, p in self.renames if d >= p and self.origin[old].startswith("renamed_to")}
        hidden |= {s for s, p in self.delisted_on.items() if d >= p}
        return sorted(s for s in self.origin if s not in hidden)


def build_universe(listings: Iterable[Listing], actions: Mapping[str, list[dict]], start: date) -> Universe:
    listed = {x.symbol: x for x in listings if x.common_like and _plain(x.symbol)}
    origin = {s: "current_listing" for s in listed}
    uni = Universe(origin, listed)
    for kind in DELISTING_TYPES:
        for a in actions.get(kind, []):
            sym = a.get("acquiree_symbol") or a.get("symbol") or ""
            p = date.fromisoformat(a.get("effective_date") or a["process_date"])
            if _plain(sym) and p > start and sym not in listed:
                origin.setdefault(sym, f"delisted:{kind.rstrip('s')}@{p}")
                uni.delisted_on[sym] = min(p, uni.delisted_on.get(sym, p))
    for a in actions.get("name_changes", []):
        old, new, p = a.get("old_symbol", ""), a.get("new_symbol", ""), date.fromisoformat(a["process_date"])
        if _plain(old) and _plain(new) and old != new and p > start and (new in origin):
            origin.setdefault(old, f"renamed_to:{new}@{p}")
            uni.renames.append((old, new, p))
    for kind in SPLIT_TYPES:
        for a in actions.get(kind, []):
            if a.get("symbol") in origin and a.get("old_rate") and a.get("new_rate"):
                ex = date.fromisoformat(a["ex_date"])
                uni.splits[(a["symbol"], ex)] = Split(a["symbol"], ex, float(a["old_rate"]), float(a["new_rate"]))
    uni.renames.sort()
    return uni
