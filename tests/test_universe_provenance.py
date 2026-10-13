import subprocess
from datetime import date
from pathlib import Path

import pytest

from momentum_bot import provenance
from momentum_bot.universe import build_universe, directory_created, parse_directory

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
GAP|Gap Corp - Common Stock|S|N|N|100|N|N
GAPW|Gap Corp - Warrant|S|N|N|100|N|N
QQQ|Invesco QQQ Trust|G|N|N|100|Y|N
ZZZT|Test Issue Corp|S|Y|N|100|N|N
NEW|New Name Inc - Class A Common Stock|S|N|N|100|N|N
SPL|Split Co - Common Stock|S|N|D|100|N|N
File Creation Time: 0308202408:00|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK=B
ABR$D|Arbor Realty 6.375% Series D Preferred|N|ABRpD|N|100|N|ABR-D
File Creation Time: 0308202408:00||||||||
"""
ACTIONS = {
    "cash_mergers": [{"acquiree_symbol": "DEAD", "effective_date": "2024-03-08", "process_date": "2024-03-08"},
                     {"acquiree_symbol": "032CVR011", "process_date": "2024-03-08"}],
    "name_changes": [{"old_symbol": "OLD", "new_symbol": "NEW", "process_date": "2024-03-08"}],
    "reverse_splits": [{"symbol": "SPL", "ex_date": "2024-03-08", "old_rate": 10, "new_rate": 1}],
}


def test_directory_filtering_and_universe_rules() -> None:
    assert directory_created(NASDAQ) == "0308202408:00"
    uni = build_universe(parse_directory(NASDAQ, OTHER), ACTIONS, date(2024, 3, 6))
    assert uni.origin == {
        "GAP": "current_listing", "NEW": "current_listing", "SPL": "current_listing", "BRK.B": "current_listing",
        "DEAD": "delisted:cash_merger@2024-03-08", "OLD": "renamed_to:NEW@2024-03-08",
    }
    # Before the rename only OLD is used (Alpaca maps history onto NEW too); DEAD is gone on its effective date.
    assert uni.symbols_for(date(2024, 3, 7)) == ["BRK.B", "DEAD", "GAP", "OLD", "SPL"]
    assert uni.symbols_for(date(2024, 3, 8)) == ["BRK.B", "GAP", "NEW", "SPL"]
    assert uni.splits[("SPL", date(2024, 3, 8))].price_factor == 10


def test_code_version_reads_git_dir_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text("# pack-refs\nabc1234def5678 refs/heads/main\n")

    def no_git(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert provenance.code_version(tmp_path) == "abc1234-dirty?"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "refs" / "heads" / "main").write_text("fedcba9876543\n")
    assert provenance.code_version(tmp_path) == "fedcba9-dirty?"
    assert provenance.code_version(tmp_path / "missing") == "unknown"


def test_code_version_with_git() -> None:
    sha = provenance.code_version()
    assert sha != "unknown" and len(sha.split("-")[0]) == 7


def test_reused_ticker_is_not_hidden_after_rename() -> None:
    actions = {"name_changes": [{"old_symbol": "GAP", "new_symbol": "NEW", "process_date": "2024-03-08"}]}
    uni = build_universe(parse_directory(NASDAQ, OTHER), actions, date(2024, 3, 6))
    assert uni.origin["GAP"] == "current_listing"  # GAP is listed today by a different issuer
    assert "GAP" in uni.symbols_for(date(2024, 3, 8))
    assert "NEW" not in uni.symbols_for(date(2024, 3, 7))
