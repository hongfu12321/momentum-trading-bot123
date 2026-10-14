"""Dataset snapshots: inventory, checksums, immutable upload, verified restore. Offline: the "remote" is a local
directory (LocalTransport), and rclone itself is exercised through a fake runner. Nothing contacts Google Drive."""

import gzip
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from momentum_bot import backup as bk
from momentum_bot import cli

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
FILES = {  # relative path -> bytes; includes spaces, CRLF text and binary gzip
    "manifest.json": b'{\n "start_date": "2026-06-03", "end_date": "2026-10-09", "trading_days": ["2026-06-03"],\n'
                     b' "code_sha": "abc", "created_at_utc": "2026-10-13T00:00:00+00:00"\n}\n',
    "breakout_matches.csv": b"symbol,price\r\nA,1.0\r\n",  # CRLF must survive byte for byte
    "report.md": b"# report  \n",
    "cache/sip/2026-06-03_premarket_abc.csv.gz": gzip.compress(b"t,o,h,l,c,v\n", mtime=0),
    "cache/backtest_quotes/A_20260603T090000_090030.jsonl.gz": gzip.compress(b'{"bp": 1}\n', mtime=0),
    "inputs/nasdaqlisted.txt": b"Symbol|Name\n",
    "backtest/in_sample/base_cap50/trades.csv": b"symbol\nA\n",
    "diagnostics/in_sample/base_cap50/trade ledger copy.csv": b"symbol\nA\n",  # a space in the name
    "research/in_sample/my signals.csv": b"x\n",
}
SECRETS = {".env": b"APCA_API_SECRET_KEY=x\n", "api_token.json": b"{}", "rclone.conf": b"[gdrive]\n",
           "credentials.json": b"{}", ".git/config": b"x", "notes.txt": b"not allowlisted", "run.log": b"x",
           "cache/sip/tmp.partial": b"x", "viewer_check.json": b"{}"}


def make_dataset(root: Path, extra: dict[str, bytes] | None = None) -> Path:
    ds = root / "m2_test dataset"
    for rel, data in {**FILES, **(extra or {})}.items():
        (ds / rel).parent.mkdir(parents=True, exist_ok=True)
        (ds / rel).write_bytes(data)
    return ds


@pytest.fixture
def env(tmp_path):  # noqa: ANN001, ANN201
    ds = make_dataset(tmp_path / "src", SECRETS)
    remote = str(tmp_path / "remote" / "trading-research")
    return ds, remote, bk.LocalTransport(), tmp_path


def do_backup(ds, remote, t, sid=None):  # noqa: ANN001, ANN201
    plan = bk.plan_backup(ds, remote, now=NOW, snapshot_id=sid, commit="deadbeef")
    bk.backup(plan, t, log=lambda _: None)
    return plan


def tree(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


# ---------- inventory, manifest, determinism, exclusions ----------

def test_inventory_is_deterministic_and_excludes_secrets(env) -> None:  # noqa: ANN001
    ds, *_ = env
    a, b = bk.inventory(ds), bk.inventory(ds)
    assert a.files == b.files and list(a.files) == sorted(FILES) == list(b.files)
    assert a.excluded == {"hidden": 2, "not_allowlisted": 1, "regenerated_report": 1, "secret_like_name": 3,
                          "temporary_or_log": 2}
    assert a.files["breakout_matches.csv"]["sha256"] == bk.sha256_bytes(FILES["breakout_matches.csv"])  # raw bytes
    assert a.total_bytes == sum(len(v) for v in FILES.values())


def test_snapshot_manifest_records_provenance(env) -> None:  # noqa: ANN001
    ds, remote, *_ = env
    plan = bk.plan_backup(ds, remote, now=NOW, commit="deadbeef")
    m = plan.manifest
    assert m["schema_version"] == 1 and m["hash_policy"] == "sha256-raw-bytes-v1" and m["source_commit"] == "deadbeef"
    assert (m["dataset_name"], m["file_count"], m["total_bytes"]) == ("m2_test dataset", len(FILES), plan.inventory.total_bytes)
    assert m["coverage"]["start_date"] == "2026-06-03" and m["coverage"]["trading_days"] == 1
    assert m["dataset_manifest_sha256"] == bk.sha256_bytes(FILES["manifest.json"])
    assert m["checksums_sha256"] == bk.sha256_bytes(bk._json_bytes(plan.inventory.files))
    assert plan.snapshot_id.startswith("20261014T120000Z-") and len(plan.snapshot_id) == 33
    assert plan.remote_dir == f"{remote}/snapshots/m2_test dataset/{plan.snapshot_id}"
    assert bk.plan_backup(ds, remote, now=NOW).snapshot_id != plan.snapshot_id  # random part: collision-safe


def test_not_a_dataset_is_refused(tmp_path) -> None:  # noqa: ANN001
    with pytest.raises(bk.BackupError, match="no manifest.json"):
        bk.inventory(tmp_path)


# ---------- backup, list, restore, verify ----------

def test_round_trip_restores_exact_bytes_and_only_allowlisted_files(env) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    plan = do_backup(ds, remote, t)
    snaps = bk.list_snapshots(remote, t)
    assert snaps == [{"dataset_name": "m2_test dataset", "snapshot_id": plan.snapshot_id, "complete": True,
                      "files": len(FILES), "bytes": plan.inventory.total_bytes}]
    remote_files = t.list_files(plan.remote_dir)
    assert not any(name in f for f in remote_files for name in ("env", "token", "rclone", "credential", "notes", ".log"))
    dest = tmp / "other mac" / "datasets" / "m2_sip"
    bk.restore(remote, plan.snapshot_id, dest, t, log=lambda _: None)
    restored = tree(dest)
    assert {k: v for k, v in restored.items() if not k.startswith(".snapshot/")} == FILES  # exact bytes, CRLF kept
    assert sorted(k for k in restored if k.startswith(".snapshot/")) == [
        ".snapshot/COMPLETE.json", ".snapshot/checksums.json", ".snapshot/snapshot_manifest.json"]
    assert bk.verify_dataset(dest) == []
    assert not list(dest.parent.glob(".*partial"))  # staging removed after success


def test_backup_never_overwrites_a_snapshot(env) -> None:  # noqa: ANN001
    ds, remote, t, _ = env
    plan = do_backup(ds, remote, t, sid="20261014T120000Z-0000000000000001")
    before = tree(Path(plan.remote_dir))
    with pytest.raises(bk.BackupError, match="already exists remotely"):
        do_backup(ds, remote, t, sid="20261014T120000Z-0000000000000001")
    assert tree(Path(plan.remote_dir)) == before


def test_dataset_changed_after_inventory_is_refused(env) -> None:  # noqa: ANN001
    ds, remote, t, _ = env
    plan = bk.plan_backup(ds, remote, now=NOW, commit="x")
    (ds / "report.md").write_bytes(b"# edited\n")
    with pytest.raises(bk.BackupError, match="dataset changed after its inventory"):
        bk.backup(plan, t, log=lambda _: None)
    assert bk.list_snapshots(remote, t) == []  # nothing uploaded


class Interrupted(bk.LocalTransport):
    """Uploads a few files, then fails (network drop); or corrupts one file in transit."""

    def __init__(self, after: int | None = None, corrupt: str | None = None, drop: str | None = None) -> None:
        self.after, self.corrupt, self.drop = after, corrupt, drop

    def upload_files(self, src, rels, dst):  # noqa: ANN001, ANN201
        for i, r in enumerate(rels):
            if self.after is not None and i == self.after:
                raise bk.BackupError("rclone copy failed (exit 1): connection reset")
            if r == self.drop:
                continue
            super().upload_files(src, [r], dst)
            if r == self.corrupt:
                target = Path(dst).joinpath(*r.split("/"))
                target.write_bytes(target.read_bytes()[:-1] + b"X")


@pytest.mark.parametrize(("transport", "message"), [
    (Interrupted(after=3), "connection reset"),
    (Interrupted(corrupt="cache/sip/2026-06-03_premarket_abc.csv.gz"), r"content differs remotely \(md5\)"),
    (Interrupted(drop="inputs/nasdaqlisted.txt"), "missing remotely: dataset/inputs/nasdaqlisted.txt"),
])
def test_failed_or_interrupted_backup_is_never_complete(env, transport, message) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    with pytest.raises(bk.BackupError, match=message):
        do_backup(ds, remote, transport, sid="20261014T120000Z-00000000000000aa")
    (snap,) = bk.list_snapshots(remote, t)
    assert snap["complete"] is False  # listed as INCOMPLETE, never presented as complete
    with pytest.raises(bk.BackupError, match="no COMPLETE.json"):
        bk.restore(remote, snap["snapshot_id"], tmp / "dest", t, log=lambda _: None)
    assert not (tmp / "dest").exists()
    retry = do_backup(ds, remote, t)  # a retry is a new snapshot; the failed one is kept, never deleted
    assert {s["complete"] for s in bk.list_snapshots(remote, t)} == {True, False}
    assert retry.snapshot_id != snap["snapshot_id"]


def test_remote_without_hashes_cannot_complete(env) -> None:  # noqa: ANN001
    ds, remote, _, _ = env

    class NoHash(bk.LocalTransport):
        def list_files(self, path):  # noqa: ANN001, ANN201
            return {k: {**v, "md5": None} for k, v in super().list_files(path).items()}
    with pytest.raises(bk.BackupError, match="reports no md5"):
        do_backup(ds, remote, NoHash())


@pytest.mark.parametrize(("tamper", "message"), [
    (lambda d: (d / "dataset" / "report.md").write_bytes(b"# tampered\n"), "modified: report.md"),
    (lambda d: (d / "dataset" / "inputs" / "nasdaqlisted.txt").unlink(), "missing: inputs/nasdaqlisted.txt"),
    (lambda d: (d / "dataset" / "extra.csv").write_bytes(b"x"), "unexpected: extra.csv"),
    (lambda d: (d / "dataset" / "notes.txt").write_bytes(b"x"), "unexpected: notes.txt"),
    (lambda d: (d / "checksums.json").write_bytes(b"{}\n"), "checksums.json does not match"),
    (lambda d: (d / "snapshot_manifest.json").write_bytes(b'{"x": 1}\n'), "snapshot_manifest.json does not match"),
])
def test_restore_rejects_a_corrupted_snapshot_and_moves_nothing(env, tamper, message) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    plan = do_backup(ds, remote, t)
    tamper(Path(plan.remote_dir))  # damage after the snapshot completed
    dest = tmp / "dest"
    with pytest.raises(bk.BackupError, match=message):
        bk.restore(remote, plan.snapshot_id, dest, t, log=lambda _: None)
    assert not dest.exists() and list(tmp.glob(".dest.restore-*.partial"))  # staging kept for inspection


def test_path_traversal_in_checksums_is_rejected(env) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    plan = do_backup(ds, remote, t)
    d = Path(plan.remote_dir)
    files = json.loads((d / "checksums.json").read_text())
    files["../../evil.sh"] = files.pop("report.md")
    raw = bk._json_bytes(files)
    (d / "checksums.json").write_bytes(raw)
    m = json.loads((d / "snapshot_manifest.json").read_text())
    m["checksums_sha256"] = bk.sha256_bytes(raw)
    (d / "snapshot_manifest.json").write_bytes(bk._json_bytes(m))
    c = json.loads((d / "COMPLETE.json").read_text())
    c.update(checksums_sha256=bk.sha256_bytes(raw), snapshot_manifest_sha256=bk.sha256_bytes(bk._json_bytes(m)))
    (d / "COMPLETE.json").write_bytes(bk._json_bytes(c))
    with pytest.raises(bk.BackupError, match="unsafe path"):
        bk.restore(remote, plan.snapshot_id, tmp / "dest", t, log=lambda _: None)
    assert not (tmp / "evil.sh").exists() and not (tmp.parent / "evil.sh").exists()


def test_existing_destination_is_never_overwritten(env) -> None:  # noqa: ANN001
    ds, remote, t, _ = env
    plan = do_backup(ds, remote, t)
    before = tree(ds)
    with pytest.raises(bk.BackupError, match="already exists"):
        bk.restore(remote, plan.snapshot_id, ds, t, log=lambda _: None)
    assert tree(ds) == before


def test_interrupted_restore_leaves_no_dataset_and_can_be_retried(env) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    plan = do_backup(ds, remote, t)

    class Dropped(bk.LocalTransport):
        def download_dir(self, src, dst):  # noqa: ANN001, ANN201
            first = next(iter(self.list_files(src)))
            self._copy(Path(src) / first, dst / first)
            raise bk.BackupError("rclone copy failed (exit 1): connection reset")
    dest = tmp / "dest"
    with pytest.raises(bk.BackupError, match="connection reset"):
        bk.restore(remote, plan.snapshot_id, dest, Dropped(), log=lambda _: None)
    assert not dest.exists()  # half a download is never presented as a dataset
    bk.restore(remote, plan.snapshot_id, dest, t, log=lambda _: None)  # the stale staging is cleared and redone
    assert bk.verify_dataset(dest) == []


def test_unknown_or_unsafe_snapshot_ids(env) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    do_backup(ds, remote, t)
    with pytest.raises(bk.BackupError, match="not found"):
        bk.restore(remote, "20990101T000000Z-0000000000000000", tmp / "d", t, log=lambda _: None)
    with pytest.raises(bk.BackupError, match="unsafe path"):
        bk.restore(remote, "../x", tmp / "d", t, log=lambda _: None)


def test_verify_detects_local_changes(env) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    plan = do_backup(ds, remote, t)
    dest = tmp / "dest"
    bk.restore(remote, plan.snapshot_id, dest, t, log=lambda _: None)
    (dest / "report.md").write_bytes(b"# changed\n")
    (dest / "cache" / "sip" / "2026-06-04_premarket_new.csv.gz").write_bytes(b"x")
    (dest / "inputs" / "nasdaqlisted.txt").unlink()
    assert bk.verify_dataset(dest) == ["missing: inputs/nasdaqlisted.txt", "modified: report.md (size 10 vs 11, "
                                       f"sha256 {bk.sha256_bytes(b'# changed' + chr(10).encode())[:12]}… vs "
                                       f"{bk.sha256_bytes(FILES['report.md'])[:12]}…)",
                                       "unexpected: cache/sip/2026-06-04_premarket_new.csv.gz"]
    with pytest.raises(bk.BackupError, match="no checksums"):
        bk.verify_dataset(ds)  # never restored: needs --checksums


# ---------- cross-platform paths ----------

@pytest.mark.parametrize("bad", ["/etc/passwd", "a/../../b", "C:/x", "a\\b", "", "./a", "a//b"])
def test_recorded_paths_must_be_safe_relative_posix(bad) -> None:  # noqa: ANN001
    with pytest.raises(bk.BackupError, match="unsafe path"):
        bk.safe_parts(bad)


def test_checksums_use_posix_paths_that_restore_on_any_os(env) -> None:  # noqa: ANN001
    ds, *_ = env
    inv = bk.inventory(ds)
    assert all("\\" not in k and not k.startswith("/") for k in inv.files)
    assert bk.safe_parts("diagnostics/in_sample/base_cap50/trade ledger copy.csv") == (
        "diagnostics", "in_sample", "base_cap50", "trade ledger copy.csv")  # joined with the local separator on restore


# ---------- rclone transport (fake runner: no network) ----------

class FakeRclone:
    def __init__(self, outputs: dict[str, tuple[int, str, str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.files_from: list[str] = []
        self.outputs = outputs or {}

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        if "--files-from-raw" in cmd:
            self.files_from.append(Path(cmd[cmd.index("--files-from-raw") + 1]).read_text(encoding="utf-8"))
        code, out, err = self.outputs.get(cmd[1], (0, "", ""))
        return subprocess.CompletedProcess(cmd, code, out, err)


def test_rclone_commands_are_copy_only_and_immutable(tmp_path) -> None:  # noqa: ANN001
    fake = FakeRclone({"lsjson": (0, json.dumps([{"Path": "dataset/a b.csv", "Size": 3, "Hashes": {"MD5": "abc"}}]), "")})
    r = bk.RcloneTransport(run=fake)
    r.upload_files(tmp_path, ["a b.csv", "cache/sip/x.csv.gz"], "gdrive:tr/snapshots/d/s/dataset")
    r.upload_file(tmp_path / "checksums.json", "gdrive:tr/snapshots/d/s/checksums.json")
    r.download_dir("gdrive:tr/snapshots/d/s", tmp_path / "staging")
    assert r.list_files("gdrive:tr/snapshots/d/s") == {"dataset/a b.csv": {"size": 3, "md5": "abc"}}
    assert {c[1] for c in fake.calls} <= {"copy", "copyto", "lsf", "lsjson"}
    assert all("--immutable" in c for c in fake.calls if c[1] in ("copy", "copyto"))
    assert not any(w in c for c in fake.calls for w in bk.FORBIDDEN_RCLONE)
    assert fake.files_from == ["a b.csv\ncache/sip/x.csv.gz\n"]  # exact paths, spaces kept
    for verb in ("sync", "delete", "purge", "move", "config"):
        with pytest.raises(bk.BackupError, match="copy-only"):
            r._call(verb, "gdrive:")


def test_rclone_errors_and_missing_directories(tmp_path) -> None:  # noqa: ANN001
    missing = (3, "", "ERROR : : error listing: directory not found")
    r = bk.RcloneTransport(run=FakeRclone({"lsf": missing, "lsjson": missing}))
    assert r.list_dirs("gdrive:tr/snapshots") == [] and r.list_files("gdrive:tr/x") == {}
    r = bk.RcloneTransport(run=FakeRclone({"copy": (1, "", "Failed to copy: googleapi: Error 403: quota")}))
    with pytest.raises(bk.BackupError, match="403"):
        r.download_dir("gdrive:tr/x", tmp_path)
    assert isinstance(bk.transport_for("gdrive:trading-research"), bk.RcloneTransport)
    assert isinstance(bk.transport_for(str(tmp_path)), bk.LocalTransport)


# ---------- CLI ----------

def test_cli_backup_is_a_dry_run_unless_confirmed(env, capsys, monkeypatch) -> None:  # noqa: ANN001
    ds, remote, t, tmp = env
    monkeypatch.setattr(bk, "transport_for", lambda remote: pytest.fail("a dry run must not touch the remote"))
    assert cli.main(["dataset-backup", "--dataset", str(ds), "--remote", "gdrive:trading-research"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert f"{len(FILES)} files" in out and "dry run: nothing uploaded" in out
    monkeypatch.setattr(bk, "transport_for", lambda remote: t)
    assert cli.main(["dataset-backup", "--dataset", str(ds), "--remote", remote, "--confirm"]) == cli.EXIT_OK
    assert cli.main(["dataset-list", "--remote", remote]) == cli.EXIT_OK
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert "COMPLETE" in line and "INCOMPLETE" not in line
    sid = line.split()[-6]
    dest = tmp / "restored"
    assert cli.main(["dataset-restore", "--snapshot", sid, "--remote", remote, "--destination", str(dest)]) == cli.EXIT_OK
    assert cli.main(["dataset-verify", "--dataset", str(dest)]) == cli.EXIT_OK
    (dest / "report.md").write_bytes(b"x")
    assert cli.main(["dataset-verify", "--dataset", str(dest)]) == cli.EXIT_MISMATCH
    assert cli.main(["dataset-restore", "--snapshot", sid, "--remote", remote, "--destination", str(dest)]) == cli.EXIT_PARTIAL
    assert "already exists" in capsys.readouterr().err


def test_restored_dataset_still_passes_the_viewer_hashing(env) -> None:  # noqa: ANN001
    """The viewer's canonical hashes see a restored copy exactly like the original (bytes are identical)."""
    from momentum_bot.diagnostics import sha256_of

    ds, remote, t, tmp = env
    plan = do_backup(ds, remote, t)
    bk.restore(remote, plan.snapshot_id, tmp / "dest", t, log=lambda _: None)
    for rel in FILES:
        assert sha256_of(tmp / "dest" / rel) == sha256_of(ds / rel)
    shutil.rmtree(tmp / "dest")


def test_missing_rclone_is_a_clear_error(capsys, monkeypatch) -> None:  # noqa: ANN001
    r = bk.RcloneTransport(binary="rclone-does-not-exist-here")
    with pytest.raises(bk.BackupError, match="not found; install it"):
        r.list_dirs("gdrive:trading-research")
    # The CLI path, with a binary that cannot exist: never the real rclone, never the network.
    monkeypatch.setattr(bk, "transport_for", lambda remote: bk.RcloneTransport(binary="rclone-does-not-exist-here"))
    assert cli.main(["dataset-list", "--remote", "gdrive:trading-research"]) == cli.EXIT_PARTIAL
    assert "not found; install it" in capsys.readouterr().err


@pytest.fixture(autouse=True)
def _no_real_rclone(monkeypatch):  # noqa: ANN001, ANN202
    """Guard: no test may start the real rclone (it would reach Google Drive)."""
    real = bk.subprocess.run

    def guarded(cmd, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
        if cmd and Path(str(cmd[0])).name == "rclone":
            raise AssertionError(f"a test tried to run the real rclone: {cmd[:2]}")
        return real(cmd, *a, **k)
    monkeypatch.setattr(bk.subprocess, "run", guarded)
