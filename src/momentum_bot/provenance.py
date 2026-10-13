"""Code version for run manifests, with or without a git executable on PATH."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_PATHS = ("src", "pyproject.toml")  # generated reports in the repo do not make the code dirty


def _from_git_dir(root: Path) -> str | None:
    """Resolve HEAD by reading .git directly (loose ref or packed-refs)."""
    git_dir = root / ".git"
    if git_dir.is_file():  # worktree/submodule: "gitdir: <path>"
        git_dir = (root / git_dir.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return None
    head = head_file.read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head or None
    ref = head.split(":", 1)[1].strip()
    loose = git_dir / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


def code_version(root: Path = REPO_ROOT) -> str:
    """Short commit SHA plus "-dirty" for uncommitted changes under CODE_PATHS.

    Without a git executable the SHA is read from .git and the suffix is "-dirty?" because the
    working tree cannot be checked. Returns "unknown" only when no repository is found.
    """
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        if sha.returncode == 0 and sha.stdout.strip():
            status = subprocess.run(["git", "status", "--porcelain", "--", *CODE_PATHS], cwd=root, capture_output=True, text=True, timeout=5)
            dirty = "-dirty" if status.returncode == 0 and status.stdout.strip() else ""
            return sha.stdout.strip() + dirty
    except (OSError, subprocess.SubprocessError):
        pass
    full = _from_git_dir(root)
    return f"{full[:7]}-dirty?" if full else "unknown"
