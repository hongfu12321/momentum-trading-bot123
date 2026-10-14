"""Immutable dataset snapshots on a private rclone remote (e.g. Google Drive), with verified restore.

Remote layout (copy-only; nothing is ever overwritten, synced, moved or deleted)::

    <remote>/snapshots/<dataset name>/<snapshot id>/
        dataset/...               exact bytes of every allowlisted dataset file
        checksums.json            relative path -> size, sha256, md5
        snapshot_manifest.json    coverage, source commit, counts, hashes, schema version
        COMPLETE.json             written last, only after the remote copy was verified

A snapshot without COMPLETE.json is incomplete (a failed or interrupted backup) and is never restored.
Restore downloads into a staging directory next to the destination, verifies every file's size and
sha256 against checksums.json, rejects missing, unexpected or modified files, and only then renames
the staging copy into place. An existing destination is never overwritten.

Only an allowlist of dataset files is included (``INCLUDE``); secrets, hidden files, symlinks, logs and
temporary files are always excluded. Market data is copied as is: nothing is regenerated or fetched.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Protocol

SCHEMA_VERSION = 1
HASH_POLICY = "sha256-raw-bytes-v1"  # exact bytes, no line-ending normalization (unlike diagnostics.HASH_POLICY)
CHECKSUMS, MANIFEST, COMPLETE, PAYLOAD, LOCAL_META = "checksums.json", "snapshot_manifest.json", "COMPLETE.json", \
    "dataset", ".snapshot"

# Research-critical files of a dataset folder, as relative POSIX globs ("*" stays within one path segment).
INCLUDE = (
    "*.json", "*.md", "*.csv", "*.csv.gz",            # manifest, reports, signals, candidates, universe, references
    "inputs/*.txt", "inputs/*.json",                   # directory and corporate-action snapshots
    "cache/sip/*.csv.gz", "cache/iex/*.csv.gz",        # 1-minute OHLCV caches
    "cache/backtest_quotes/*.jsonl.gz",                # historical NBBO quote cache
    "backtest/*/*/*.csv", "backtest/*/*/*/*.csv",      # PR #4 ledgers (baseline and research variants)
    "diagnostics/*/*/*", "diagnostics/*/*/*/*",        # PR #5 ledgers, failure cases, dashboards
    "research/*/*",                                    # research rankings and signal sets
)
# Never included, whatever the allowlist says.
SECRET_PATTERNS = (".env", ".env.*", "*.env", "*secret*", "*token*", "*credential*", "*password*", "rclone.conf",
                   "*.pem", "*.key", "*.p12", "id_rsa*")
JUNK_PATTERNS = ("*.tmp", "*.partial", "*.log", "*~", "*.swp", "Thumbs.db", ".DS_Store")
# Local reports regenerated on every run (m2-viewer-check); backing them up would make every restore "modified".
REGENERATED = ("viewer_check.json",)


class BackupError(RuntimeError):
    """A backup, restore or verification did not complete; nothing is presented as complete."""


# ---------- inventory and checksums ----------

@dataclass(slots=True)
class Inventory:
    files: dict[str, dict[str, object]]  # relative POSIX path -> {"size", "sha256", "md5"}
    excluded: dict[str, int] = field(default_factory=dict)  # reason -> count (names are not recorded)

    @property
    def total_bytes(self) -> int:
        return sum(int(v["size"]) for v in self.files.values())  # type: ignore[call-overload]


def _digests(path: Path) -> tuple[int, str, str]:
    sha, md5, size = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return size, sha.hexdigest(), md5.hexdigest()


def classify(rel: str) -> str | None:
    """Why a relative path is excluded, or None if it is included."""
    parts = PurePosixPath(rel).parts
    name = parts[-1]
    if any(p.startswith(".") for p in parts):
        return "hidden"
    if any(fnmatch.fnmatch(name.lower(), pat) for pat in SECRET_PATTERNS):
        return "secret_like_name"
    if any(fnmatch.fnmatch(name, pat) for pat in JUNK_PATTERNS):
        return "temporary_or_log"
    if rel in REGENERATED:
        return "regenerated_report"
    if not any(fnmatch.fnmatch(rel, pat) and len(PurePosixPath(pat).parts) == len(parts) for pat in INCLUDE):
        return "not_allowlisted"
    return None


def inventory(dataset: Path) -> Inventory:
    """Deterministic inventory (sorted by path) of the allowlisted files, with sizes, sha256 and md5."""
    if not (dataset / "manifest.json").is_file():
        raise BackupError(f"{dataset} has no manifest.json; not a dataset folder")
    files: dict[str, dict[str, object]] = {}
    excluded: Counter[str] = Counter()
    for root, dirs, names in os.walk(dataset, followlinks=False):
        dirs.sort()
        for name in sorted(names):
            path = Path(root) / name
            rel = path.relative_to(dataset).as_posix()
            if path.is_symlink() or not path.is_file():
                excluded["symlink_or_special"] += 1
                continue
            reason = classify(rel)
            if reason:
                excluded[reason] += 1
                continue
            size, sha, md5 = _digests(path)
            files[rel] = {"size": size, "sha256": sha, "md5": md5}
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
    return Inventory(dict(sorted(files.items())), dict(sorted(excluded.items())))


def check_inventory(dataset: Path, files: dict[str, dict[str, object]], *, extra_ok: Iterable[str] = ()) -> list[str]:
    """Problems of a dataset folder against recorded checksums: missing, modified and unexpected files."""
    problems: list[str] = []
    for rel, want in files.items():
        path = dataset.joinpath(*safe_parts(rel))
        if not path.is_file():
            problems.append(f"missing: {rel}")
            continue
        size, sha, _ = _digests(path)
        if size != want["size"] or sha != want["sha256"]:
            problems.append(f"modified: {rel} (size {size} vs {want['size']}, sha256 {sha[:12]}… vs {str(want['sha256'])[:12]}…)")
    allowed = set(files) | set(extra_ok)
    for root, _, names in os.walk(dataset):
        for name in names:
            rel = (Path(root) / name).relative_to(dataset).as_posix()
            if rel not in allowed and classify(rel) is None:
                problems.append(f"unexpected: {rel}")
    return sorted(problems)


def safe_parts(rel: str) -> tuple[str, ...]:
    """Path segments of a recorded relative POSIX path; rejects anything that could escape the destination."""
    p = PurePosixPath(rel)
    if p.as_posix() != rel or p.is_absolute() or not p.parts \
            or any(x in ("", ".", "..") or "\\" in x or ":" in x for x in p.parts):
        raise BackupError(f"unsafe path in snapshot: {rel!r}")
    return p.parts


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(obj: object) -> bytes:
    return (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode("utf-8")


# ---------- transport ----------

class Transport(Protocol):
    """Copy-only remote operations. Paths are "<remote>:<path>" strings for rclone, or local paths."""

    def list_dirs(self, path: str) -> list[str]: ...
    def list_files(self, path: str) -> dict[str, dict[str, object]]: ...  # relative path -> {"size", "md5"}
    def upload_files(self, src: Path, rels: list[str], dst: str) -> None: ...
    def upload_file(self, src: Path, dst: str) -> None: ...
    def download_dir(self, src: str, dst: Path) -> None: ...


FORBIDDEN_RCLONE = frozenset({"sync", "move", "moveto", "delete", "deletefile", "purge", "rmdir", "rmdirs", "cleanup",
                              "dedupe", "link", "settier"})


@dataclass(slots=True)
class RcloneTransport:
    """rclone through subprocess (no shell). Only copy, copyto, lsf and lsjson are ever run; every copy uses
    --immutable, so an existing remote file is never modified."""

    binary: str = "rclone"
    run: Callable[[list[str]], subprocess.CompletedProcess] = field(
        default=lambda cmd: subprocess.run(cmd, capture_output=True, text=True, check=False))

    def _call(self, *args: str) -> str:
        if args[0] in FORBIDDEN_RCLONE or args[0] not in ("copy", "copyto", "lsf", "lsjson"):
            raise BackupError(f"refusing rclone {args[0]}: only copy-only commands are allowed")
        res = self.run([self.binary, *args])
        if res.returncode != 0:
            raise BackupError(f"rclone {args[0]} failed (exit {res.returncode}): {res.stderr.strip()[-500:]}")
        return res.stdout

    def list_dirs(self, path: str) -> list[str]:
        try:
            return [x.rstrip("/") for x in self._call("lsf", "--dirs-only", path).splitlines() if x]
        except BackupError as exc:
            if "directory not found" in str(exc).lower():
                return []
            raise

    def list_files(self, path: str) -> dict[str, dict[str, object]]:
        try:
            rows = json.loads(self._call("lsjson", "-R", "--files-only", "--hash", "--hash-type", "MD5", path) or "[]")
        except BackupError as exc:
            if "directory not found" in str(exc).lower():
                return {}
            raise
        return {r["Path"]: {"size": r["Size"], "md5": {k.lower(): v for k, v in (r.get("Hashes") or {}).items()}.get("md5")}
                for r in rows}

    def upload_files(self, src: Path, rels: list[str], dst: str) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", newline="\n") as fh:
            fh.write("".join(f"{r}\n" for r in rels))
        try:  # --files-from-raw: exact paths, spaces kept, no comment parsing
            self._call("copy", "--immutable", "--no-traverse", "--files-from-raw", fh.name, str(src), dst)
        finally:
            os.unlink(fh.name)

    def upload_file(self, src: Path, dst: str) -> None:
        self._call("copyto", "--immutable", str(src), dst)

    def download_dir(self, src: str, dst: Path) -> None:
        self._call("copy", "--immutable", src, str(dst))


@dataclass(slots=True)
class LocalTransport:
    """A local directory standing in for the remote (tests, or a private external drive). Same contract:
    copy-only, never overwrites, md5 computed from the stored bytes."""

    def list_dirs(self, path: str) -> list[str]:
        p = Path(path)
        return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.is_dir() else []

    def list_files(self, path: str) -> dict[str, dict[str, object]]:
        p = Path(path)
        out: dict[str, dict[str, object]] = {}
        for f in sorted(p.rglob("*")) if p.is_dir() else []:
            if f.is_file():
                size, _, md5 = _digests(f)
                out[f.relative_to(p).as_posix()] = {"size": size, "md5": md5}
        return out

    def _copy(self, src: Path, dst: Path) -> None:
        if dst.exists():
            raise BackupError(f"refusing to overwrite existing remote file {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def upload_files(self, src: Path, rels: list[str], dst: str) -> None:
        for r in rels:
            self._copy(src.joinpath(*safe_parts(r)), Path(dst).joinpath(*safe_parts(r)))

    def upload_file(self, src: Path, dst: str) -> None:
        self._copy(src, Path(dst))

    def download_dir(self, src: str, dst: Path) -> None:
        for rel in self.list_files(src):
            self._copy(Path(src).joinpath(*safe_parts(rel)), dst.joinpath(*safe_parts(rel)))


def join(remote: str, *parts: str) -> str:
    return "/".join([remote.rstrip("/"), *parts])


def transport_for(remote: str) -> Transport:
    """rclone for "<name>:<path>" remotes; a plain local directory otherwise."""
    return RcloneTransport() if ":" in remote.split("/")[0] and not Path(remote).is_absolute() else LocalTransport()


# ---------- backup ----------

def new_snapshot_id(now: datetime) -> str:
    """UTC time plus 64 random bits: sortable, and collision-safe across machines."""
    return f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}"


def source_commit(repo: Path) -> str:
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def snapshot_manifest(dataset: Path, inv: Inventory, snapshot_id: str, created: datetime, commit: str,
                      checksums_sha256: str) -> dict[str, object]:
    from .diagnostics import sha256_of  # canonical (CRLF-normalized) hash, as provenance records use

    m = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    return {
        "schema_version": SCHEMA_VERSION, "snapshot_id": snapshot_id, "dataset_name": dataset.name,
        "coverage": {"start_date": m.get("start_date"), "end_date": m.get("end_date"),
                     "trading_days": len(m.get("trading_days", [])), "chronological_split": m.get("chronological_split"),
                     "feeds": m.get("feeds"), "timeframe": m.get("timeframe")},
        "created_at_utc": created.isoformat(), "source_commit": commit,
        "file_count": len(inv.files), "total_bytes": inv.total_bytes, "hash_policy": HASH_POLICY,
        "checksums_sha256": checksums_sha256, "excluded_counts": inv.excluded,
        "dataset_manifest_sha256": inv.files["manifest.json"]["sha256"],
        "dataset_manifest_sha256_canonical_lf": sha256_of(dataset / "manifest.json"),
        "dataset_manifest_code_sha": m.get("code_sha"), "dataset_manifest_created_at_utc": m.get("created_at_utc"),
    }


@dataclass(slots=True)
class BackupPlan:
    dataset: Path
    snapshot_id: str
    remote_dir: str
    inventory: Inventory
    manifest: dict[str, object]


def plan_backup(dataset: Path, remote: str, *, now: datetime | None = None, snapshot_id: str | None = None,
                commit: str | None = None) -> BackupPlan:
    """Inventory and manifest only: no remote access. Used for dry runs and size estimates."""
    created = now or datetime.now(timezone.utc)
    sid = snapshot_id or new_snapshot_id(created)
    safe_parts(sid)
    inv = inventory(dataset)
    if "manifest.json" not in inv.files:
        raise BackupError("manifest.json was excluded from the inventory")
    manifest = snapshot_manifest(dataset, inv, sid, created, commit or source_commit(Path.cwd()),
                                 sha256_bytes(_json_bytes(inv.files)))
    return BackupPlan(dataset, sid, join(remote, "snapshots", dataset.name, sid), inv, manifest)


def backup(plan: BackupPlan, transport: Transport, log: Callable[[str], None] = print) -> dict[str, object]:
    """Upload a new snapshot and verify it; COMPLETE.json is written only after verification succeeds."""
    parent = plan.remote_dir.rsplit("/", 1)[0]
    if plan.snapshot_id in transport.list_dirs(parent):
        raise BackupError(f"snapshot {plan.snapshot_id} already exists remotely; snapshots are never modified")
    stale = check_inventory(plan.dataset, plan.inventory.files)  # the dataset must not change while it is copied
    if stale:
        raise BackupError("dataset changed after its inventory was taken: " + "; ".join(stale[:5]))
    rels = list(plan.inventory.files)
    log(f"uploading {len(rels)} files ({plan.inventory.total_bytes:,} bytes) to {plan.remote_dir}")
    transport.upload_files(plan.dataset, rels, join(plan.remote_dir, PAYLOAD))
    with tempfile.TemporaryDirectory() as tmp:
        meta = {CHECKSUMS: _json_bytes(plan.inventory.files), MANIFEST: _json_bytes(plan.manifest)}
        for name, data in meta.items():
            (Path(tmp) / name).write_bytes(data)
            transport.upload_file(Path(tmp) / name, join(plan.remote_dir, name))
        log("verifying the remote copy (sizes and server-side md5 of every file)")
        problems = verify_remote(plan.remote_dir, plan.inventory.files, meta, transport)
        if problems:
            raise BackupError(f"remote verification failed for {plan.snapshot_id}; the snapshot is left INCOMPLETE: "
                              + "; ".join(problems[:10]))
        complete = {"snapshot_id": plan.snapshot_id, "verified_at_utc": datetime.now(timezone.utc).isoformat(),
                    "file_count": len(rels), "total_bytes": plan.inventory.total_bytes,
                    "snapshot_manifest_sha256": sha256_bytes(meta[MANIFEST]),
                    "checksums_sha256": sha256_bytes(meta[CHECKSUMS])}
        (Path(tmp) / COMPLETE).write_bytes(_json_bytes(complete))
        transport.upload_file(Path(tmp) / COMPLETE, join(plan.remote_dir, COMPLETE))
    log(f"snapshot {plan.snapshot_id} complete")
    return complete


def verify_remote(remote_dir: str, files: dict[str, dict[str, object]], meta: dict[str, bytes],
                  transport: Transport) -> list[str]:
    """Every expected file present remotely with the same size and md5 (computed by the remote from the stored
    bytes), the metadata files exact, and nothing else in the snapshot."""
    remote = transport.list_files(remote_dir)
    problems = []
    expected = {f"{PAYLOAD}/{rel}": v for rel, v in files.items()}
    expected.update({name: {"size": len(data), "md5": hashlib.md5(data, usedforsecurity=False).hexdigest()}
                     for name, data in meta.items()})
    for rel, want in expected.items():
        got = remote.get(rel)
        if got is None:
            problems.append(f"missing remotely: {rel}")
        elif got["size"] != want["size"]:
            problems.append(f"size differs remotely: {rel}")
        elif not got.get("md5"):
            problems.append(f"remote reports no md5 for {rel}; cannot verify content")
        elif got["md5"] != want["md5"]:
            problems.append(f"content differs remotely (md5): {rel}")
    problems += [f"unexpected remote file: {r}" for r in sorted(remote.keys() - expected.keys() - {COMPLETE})]
    return problems


# ---------- list, restore, verify ----------

def list_snapshots(remote: str, transport: Transport) -> list[dict[str, object]]:
    """Every snapshot under <remote>/snapshots, complete or not (incomplete ones are never restorable)."""
    out = []
    root = join(remote, "snapshots")
    for name in transport.list_dirs(root):
        for sid in transport.list_dirs(join(root, name)):
            files = transport.list_files(join(root, name, sid))
            out.append({"dataset_name": name, "snapshot_id": sid, "complete": COMPLETE in files,
                        "files": sum(1 for f in files if f.startswith(PAYLOAD + "/")),
                        "bytes": sum(int(v["size"]) for f, v in files.items() if f.startswith(PAYLOAD + "/"))})  # type: ignore[call-overload]
    return sorted(out, key=lambda r: (str(r["dataset_name"]), str(r["snapshot_id"])))


def find_snapshot(remote: str, snapshot_id: str, transport: Transport) -> str:
    safe_parts(snapshot_id)
    root = join(remote, "snapshots")
    hits = [join(root, name, snapshot_id) for name in transport.list_dirs(root)
            if snapshot_id in transport.list_dirs(join(root, name))]
    if len(hits) != 1:
        raise BackupError(f"snapshot {snapshot_id} {'not found' if not hits else 'is ambiguous'} under {root}")
    return hits[0]


def verify_snapshot_dir(staged: Path) -> tuple[dict[str, object], dict[str, dict[str, object]], list[str]]:
    """Check a downloaded snapshot: the metadata chain (COMPLETE -> manifest -> checksums) and every file."""
    problems: list[str] = []
    for name in (COMPLETE, MANIFEST, CHECKSUMS):
        if not (staged / name).is_file():
            raise BackupError(f"snapshot is missing {name}" + ("; it never completed (failed or interrupted backup)"
                                                               if name == COMPLETE else ""))
    complete = json.loads((staged / COMPLETE).read_text(encoding="utf-8"))
    raw_manifest, raw_checksums = (staged / MANIFEST).read_bytes(), (staged / CHECKSUMS).read_bytes()
    if sha256_bytes(raw_manifest) != complete.get("snapshot_manifest_sha256"):
        problems.append("snapshot_manifest.json does not match COMPLETE.json")
    manifest, files = json.loads(raw_manifest), json.loads(raw_checksums)
    if sha256_bytes(raw_checksums) != manifest.get("checksums_sha256") or \
            sha256_bytes(raw_checksums) != complete.get("checksums_sha256"):
        problems.append("checksums.json does not match the snapshot manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("hash_policy") != HASH_POLICY:
        problems.append(f"unsupported snapshot schema {manifest.get('schema_version')} / {manifest.get('hash_policy')}")
    if len(files) != manifest.get("file_count") or sum(int(v["size"]) for v in files.values()) != manifest.get("total_bytes"):
        problems.append("checksums.json disagrees with the manifest's file count or total size")
    for rel in files:
        safe_parts(rel)
    if not problems:
        payload = staged / PAYLOAD
        problems += check_inventory(payload, files) if payload.is_dir() else ["the snapshot has no dataset/ folder"]
        if payload.is_dir():  # check_inventory ignores non-allowlisted names; the payload must hold nothing else
            listed = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
            problems += [f"unexpected: {r}" for r in sorted(listed - files.keys()) if f"unexpected: {r}" not in problems]
    return manifest, files, sorted(problems)


def restore(remote: str, snapshot_id: str, destination: Path, transport: Transport,
            log: Callable[[str], None] = print) -> dict[str, object]:
    """Download, verify, then move into place. The destination must not exist; nothing is overwritten."""
    if destination.exists() or destination.is_symlink():
        raise BackupError(f"{destination} already exists; restore never overwrites a dataset (choose a new path)")
    src = find_snapshot(remote, snapshot_id, transport)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.restore-{snapshot_id}.partial"
    if staging.exists():  # left by an interrupted restore of this same snapshot: ours to clear
        shutil.rmtree(staging)
    remote_files = transport.list_files(src)
    if COMPLETE not in remote_files:
        raise BackupError(f"snapshot {snapshot_id} has no COMPLETE.json: it is a failed or interrupted backup and "
                          "is never restored")
    log(f"downloading {src} to {staging}")
    transport.download_dir(src, staging)
    manifest, files, problems = verify_snapshot_dir(staging)
    if problems:
        raise BackupError(f"restore rejected, {len(problems)} problem(s); nothing was moved into {destination} "
                          f"(staging kept at {staging}): " + "; ".join(problems[:10]))
    meta = staging / PAYLOAD / LOCAL_META
    meta.mkdir()
    for name in (CHECKSUMS, MANIFEST, COMPLETE):
        shutil.copyfile(staging / name, meta / name)
    if destination.exists():
        raise BackupError(f"{destination} appeared during the restore; not overwriting it (staging kept at {staging})")
    os.rename(staging / PAYLOAD, destination)  # same filesystem: atomic
    shutil.rmtree(staging)
    log(f"restored snapshot {snapshot_id}: {manifest['file_count']} files, {manifest['total_bytes']:,} bytes, all verified")
    return manifest


def verify_dataset(dataset: Path, checksums: Path | None = None) -> list[str]:
    """Verify a dataset folder against snapshot checksums (default: <dataset>/.snapshot/checksums.json)."""
    path = checksums or dataset / LOCAL_META / CHECKSUMS
    if not path.is_file():
        raise BackupError(f"no checksums at {path}; pass --checksums, or restore the dataset from a snapshot")
    files = json.loads(path.read_text(encoding="utf-8"))
    for rel in files:
        safe_parts(rel)
    return check_inventory(dataset, files)
