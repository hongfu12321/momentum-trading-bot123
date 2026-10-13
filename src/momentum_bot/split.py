"""Chronological in-sample / out-of-sample split by trading day.

The out-of-sample block is the most recent trading days. An embargo of whole trading days between
the blocks keeps an after-hours setup and the next morning's premarket from straddling the split.
Parameters must be chosen on in-sample days only; out-of-sample results are reported once.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

IN_SAMPLE, EMBARGO, OUT_OF_SAMPLE = "in_sample", "embargo", "out_of_sample"


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    in_sample: tuple[date, ...]
    embargo: tuple[date, ...]
    out_of_sample: tuple[date, ...]

    def sample_of(self, d: date) -> str:
        if d in self.out_of_sample:
            return OUT_OF_SAMPLE
        if d in self.embargo:
            return EMBARGO
        if d in self.in_sample:
            return IN_SAMPLE
        raise KeyError(f"{d} is not in the split")

    def describe(self) -> dict[str, object]:
        return {
            name: {"days": len(block), "first": block[0].isoformat() if block else None,
                   "last": block[-1].isoformat() if block else None}
            for name, block in ((IN_SAMPLE, self.in_sample), (EMBARGO, self.embargo), (OUT_OF_SAMPLE, self.out_of_sample))
        }


def chronological_split(days: Sequence[date], oos_fraction: float = 1 / 3, embargo_days: int = 1) -> ChronologicalSplit:
    ordered = sorted(set(days))
    if not 0 < oos_fraction < 1:
        raise ValueError("oos_fraction must be between 0 and 1")
    n_oos = math.ceil(len(ordered) * oos_fraction)
    n_in = len(ordered) - n_oos - embargo_days
    if n_in < 1 or n_oos < 1:
        raise ValueError(f"{len(ordered)} trading days are too few for this split")
    return ChronologicalSplit(tuple(ordered[:n_in]), tuple(ordered[n_in : n_in + embargo_days]), tuple(ordered[-n_oos:]))
