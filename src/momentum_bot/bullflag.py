"""Bull Flag detector: an initial research hypothesis, fixed before any backtest of it was run. Not tuned.

Separate from the baseline strategy. It only labels completed 1-minute bars; research.py decides
which labelled breakouts become signals for the unchanged backtester. Evaluated at bar i, it reads
bars[: i + 1] only, so appending later candles never changes an earlier decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean

from .data.market_calendar import AFTERHOURS, SessionWindow
from .data.normalize import BAR_LENGTH
from .data.provider import Bar


def _iso(t: datetime) -> str:
    return t.isoformat()


@dataclass(frozen=True, slots=True)
class FlagParams:
    """Initial research hypothesis, fixed before any backtest of it was run. Not tuned."""

    pole_min_gain: float = 0.05
    pole_min_bars: int = 3
    pole_max_bars: int = 10
    flag_min_bars: int = 2
    flag_max_bars: int = 8
    max_pullback: float = 0.50  # share of flagpole height
    breakout_volume_multiple: float = 1.5  # breakout bar volume / consolidation average volume
    exclude_closing_auction_bar: bool = True


FLAG_RULES = ("complete_bars", "flagpole", "consolidation", "pullback", "volume_contraction", "breakout_close",
              "breakout_volume")


def evaluate_flag(hist: list[Bar], vols: list[int], params: FlagParams = FlagParams()) -> dict[str, object]:
    """Judge whether the LAST bar of ``hist`` breaks out of a Bull Flag. Reads nothing beyond it.

    Every (consolidation length, flagpole length) pair is tried; the pair passing the most rules is
    kept, ties going to the shorter consolidation and then the shorter flagpole.
    """
    i = len(hist) - 1
    b = hist[i]
    best: dict[str, object] | None = None
    best_score = -1
    for c in range(params.flag_min_bars, params.flag_max_bars + 1):
        for n in range(params.pole_min_bars, params.pole_max_bars + 1):
            s = i - c - n
            if s < 0:
                break
            pole, flag = hist[s : i - c], hist[i - c : i]
            pole_avg, flag_avg = fmean(vols[s : i - c]), fmean(vols[i - c : i])
            base, top = pole[0].low, pole[-1].high
            flag_high, flag_low = max(x.high for x in flag), min(x.low for x in flag)
            height = top - base
            pullback = (top - flag_low) / height if height > 0 else None
            rules = {
                "complete_bars": b.timestamp_utc - pole[0].timestamp_utc == (c + n) * BAR_LENGTH,  # no missing minutes
                "flagpole": base > 0 and top / base - 1 >= params.pole_min_gain and top >= max(x.high for x in pole),
                "consolidation": flag_high <= top,
                "pullback": pullback is not None and pullback <= params.max_pullback,
                "volume_contraction": flag_avg < pole_avg,
                "breakout_close": b.close > flag_high,
                "breakout_volume": flag_avg > 0 and vols[i] >= params.breakout_volume_multiple * flag_avg,
            }
            score = sum(rules.values())
            if score > best_score:
                best_score = score
                best = {
                    "pole_start_utc": _iso(pole[0].timestamp_utc), "pole_end_utc": _iso(pole[-1].timestamp_utc),
                    "flag_start_utc": _iso(flag[0].timestamp_utc), "flag_end_utc": _iso(flag[-1].timestamp_utc),
                    "pole_bars": n, "flag_bars": c, "pole_base": base, "pole_top": top,
                    "pole_gain_pct": (top / base - 1) * 100 if base > 0 else None,
                    "flag_high": flag_high, "flag_low": flag_low, "resistance": flag_high,
                    "pullback_share": pullback, "pole_avg_volume": pole_avg, "flag_avg_volume": flag_avg,
                    "breakout_volume": vols[i],
                    "breakout_volume_ratio": vols[i] / flag_avg if flag_avg > 0 else None,
                    **{f"rule_{k}": v for k, v in rules.items()},
                }
            if score == len(FLAG_RULES):
                break
        if best_score == len(FLAG_RULES):
            break
    out: dict[str, object] = {"breakout_bar_start_utc": _iso(b.timestamp_utc),
                              "available_utc": _iso(b.timestamp_utc + BAR_LENGTH), "breakout_price": b.close}
    if best is None:
        return {**out, "qualified": False, "reason": "insufficient_history"}
    failed = [k for k in FLAG_RULES if not best[f"rule_{k}"]]
    return {**out, **best, "qualified": not failed, "reason": f"failed_{failed[0]}" if failed else "qualified"}


def session_volumes(bars: list[Bar], window: SessionWindow, exclude_auction: bool = True) -> list[int]:
    """Bar volumes with the after-hours closing-auction bar counted as zero, as in the scanner."""
    skip = exclude_auction and window.name == AFTERHOURS
    return [0 if skip and b.timestamp_utc == window.start_utc else b.volume for b in bars]


def detect_flags(bars: list[Bar], window: SessionWindow, params: FlagParams = FlagParams(),
                 only: list[Bar] | None = None) -> list[dict[str, object]]:
    """Evaluate every breakout attempt (close above the previous bar's high) in one symbol-session.
    ``only`` restricts evaluation to those bars (a speed-up; each evaluation still reads bars[: i + 1])."""
    vols = session_volumes(bars, window, params.exclude_closing_auction_bar)
    keep = None if only is None else {b.timestamp_utc for b in only}
    return [evaluate_flag(bars[: i + 1], vols[: i + 1], params)
            for i in range(1, len(bars)) if bars[i].close > bars[i - 1].high
            and (keep is None or bars[i].timestamp_utc in keep)]


def flag_params_record() -> dict[str, object]:
    return {k: getattr(FlagParams(), k) for k in FlagParams.__slots__}  # type: ignore[attr-defined]
