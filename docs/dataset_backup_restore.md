# Dataset backup and restore (Google Drive via rclone)

Back up a dataset folder as an **immutable, checksummed snapshot** in a private Google Drive folder, and restore an identical copy on another machine. rclone is the only transport; there is no cloud SDK, database or sync service.

```
gdrive:trading-research/snapshots/<dataset name>/<snapshot id>/
    dataset/                 exact bytes of every allowlisted file
    checksums.json           relative path -> size, sha256, md5
    snapshot_manifest.json   coverage, created time, source commit, file count, total size, hashes, schema version
    COMPLETE.json            written last, only after the remote copy was verified
```

- **Immutable:** every backup is a new snapshot `YYYYMMDDTHHMMSSZ-<16 random hex>`. Existing snapshots are never modified, and every copy runs with `rclone --immutable`.
- **Copy-only:** the tool runs only `rclone copy`, `copyto`, `lsf` and `lsjson`. It refuses `sync`, `move`, `delete`, `purge` and similar commands, and it never deletes anything remotely.
- **Never presented as complete unless verified:** after upload, every file's size and Google's server-computed MD5 are compared with the local inventory. Only then is `COMPLETE.json` written. A failed or interrupted backup stays `INCOMPLETE` in `dataset-list` and can never be restored.
- **Verified restore:** the snapshot downloads into a hidden staging folder next to the destination. The tool checks the metadata chain (`COMPLETE.json` → manifest → checksums), every file's size and SHA-256, and that nothing is missing or extra. Only then is the folder renamed into place. An existing destination is never overwritten.
- **Exact bytes:** files are copied as is (`sha256-raw-bytes-v1`, no line-ending changes) and nothing is regenerated or fetched from Alpaca.

## What is included

An allowlist (`backup.INCLUDE`) covers:

- the dataset manifest, reports and summaries (`*.json`, `*.md`);
- the signal, candidate, universe and reference tables (`*.csv`, `*.csv.gz`);
- `inputs/` (directory and corporate-action snapshots);
- the SIP and IEX 1-minute caches (`cache/sip`, `cache/iex`) and the NBBO quote cache (`cache/backtest_quotes`);
- the backtest ledgers (`backtest/`), the diagnostics ledgers (`diagnostics/`) and research outputs (`research/`).

Always excluded:

- hidden files and folders (`.env`, `.git`, `.snapshot`);
- secret-like names (`*token*`, `*secret*`, `*credential*`, `rclone.conf`, `*.key`, `*.pem`);
- temporary files and logs;
- symlinks;
- the regenerated `viewer_check.json`;
- anything else not on the allowlist.

`dataset-backup` prints the excluded counts by reason.

For the current M2 dataset that is **2,563 files, 250.2 MB**:

| Part | Size |
|---|---:|
| NBBO quotes (`cache/backtest_quotes`) | 111 MB |
| SIP bars (`cache/sip`) | 108 MB |
| Inputs | 16 MB |
| Everything else | about 15 MB |

## 1. Install rclone (macOS)

```zsh
brew install rclone
rclone version
```

## 2. Configure a private Google Drive remote

```zsh
rclone config
```

Answer the prompts as follows:

1. `n` for a new remote, and name it `gdrive`.
2. Storage: `drive` (Google Drive).
3. `client_id` / `client_secret`: blank works. Your own Google OAuth client is better for rate limits ([rclone docs](https://rclone.org/drive/#making-your-own-client-id)).
4. Scope: **`drive.file`**. rclone can then see only the files it creates, not the rest of your Drive.
5. `root_folder_id` and `service_account_file`: blank.
6. Advanced config: `n`. Auto config: `y`. A browser opens; sign in and allow access.
7. Shared drive: `n`. Then `y` to keep the remote.

Optionally, set a config password from the `s)` menu of `rclone config`, so the stored token is encrypted on disk.

Check it, then create the private folder:

```zsh
rclone lsd gdrive:
rclone mkdir gdrive:trading-research
```

Folders created this way are private: they are not shared unless you share them in Drive. Never share this folder or create a link to it.

The OAuth token lives in `~/.config/rclone/rclone.conf`, outside the repository. Never commit or copy that file into the repo.

## 3. Back up

From the repository root:

```zsh
.venv/bin/momentum-bot dataset-backup --dataset reports/datasets/m2_sip_20260603_20261009 --remote gdrive:trading-research
```

Without `--confirm` this is a **dry run**. It prints the snapshot id, the file count, the size, what was excluded and the destination, and uploads nothing. To upload:

```zsh
.venv/bin/momentum-bot dataset-backup --dataset reports/datasets/m2_sip_20260603_20261009 --remote gdrive:trading-research --confirm
```

- **Duration:** expect roughly 10–25 minutes for about 2,600 files. Drive limits how fast files can be created, so the file count matters more than the size.
- **What happens:**
  1. The dataset is inventoried and hashed.
  2. The tool checks that no file changed in the meantime.
  3. The files and `checksums.json` / `snapshot_manifest.json` are uploaded.
  4. Every remote size and MD5 is checked.
  5. Only then is `COMPLETE.json` written.
- **Exit codes:** 0 on success, 1 on any failure.
- **Storage:** every snapshot is a full copy (about 250 MB for M2). A free 15 GB Drive holds roughly 50 snapshots alongside other files.

## 4. List snapshots

```zsh
.venv/bin/momentum-bot dataset-list --remote gdrive:trading-research
```

The output looks like this:

```
m2_sip_20260603_20261009  20261014T071116Z-1087298f59babfbc  COMPLETE  2563 files  250.2 MB
```

## 5. Restore on another Mac

```zsh
git clone https://github.com/hongfu12321/momentum-trading-bot123.git
cd momentum-trading-bot123
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,viewer]"
brew install rclone
rclone config                       # same steps as above, signing in to the same Google account
.venv/bin/momentum-bot dataset-list --remote gdrive:trading-research
.venv/bin/momentum-bot dataset-restore --remote gdrive:trading-research \
  --snapshot 20261014T071116Z-1087298f59babfbc \
  --destination reports/datasets/m2_sip_20260603_20261009
```

The destination must not exist yet. The restored folder also holds `.snapshot/` (`checksums.json`, `snapshot_manifest.json`, `COMPLETE.json`), which `dataset-verify` uses.

## 6. Verify a restored dataset

```zsh
.venv/bin/momentum-bot dataset-verify --dataset reports/datasets/m2_sip_20260603_20261009
.venv/bin/momentum-bot m2-viewer-check --dataset reports/datasets/m2_sip_20260603_20261009
```

- `dataset-verify` is offline. It reports every missing, modified or unexpected file. Exit code 0 means everything matches; 4 means differences were found.
- To check a dataset that was never restored, against a snapshot's checksums, pass `--checksums path/to/checksums.json`.
- `m2-viewer-check` then reconciles the backtest results and chart markers, also offline.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `rclone: command not found` | `brew install rclone`. |
| `refusing rclone …: only copy-only commands are allowed` | Intended: the tool never syncs, moves or deletes. |
| Backup fails with `error 403` / `rateLimitExceeded` / connection reset | Drive throttling or a network drop. The snapshot stays `INCOMPLETE`; run the backup again, which creates a new snapshot. You may delete the incomplete folder by hand in Drive; the tool never deletes. |
| `remote verification failed … content differs remotely` | A file was corrupted in transit or changed during upload. The snapshot stays `INCOMPLETE`; back up again. |
| `snapshot … has no COMPLETE.json` | That backup never finished; restore a `COMPLETE` snapshot instead. |
| `restore rejected … (staging kept at …)` | A downloaded file failed verification. Nothing was moved into place. Inspect, then delete the staging folder and retry. |
| `… already exists; restore never overwrites` | Choose a new destination, or move the old folder away yourself first. |
| `dataset changed after its inventory was taken` | Something wrote to the dataset during the backup; wait for it to finish and retry. |

## Security and licensing

- **Credentials:** keep them in `~/.config/rclone/rclone.conf` and `.env`, both outside git. The backup never includes `.env`, hidden files or secret-like names, and the code contains no tokens.
- **Privacy:** use the `drive.file` scope and an unshared folder. Do not publish snapshots or share their links.
- **Licensing, unresolved:** the caches hold Alpaca/SIP market data licensed for your own use. Alpaca's public pages do not say whether keeping a private cloud copy and using it on a second device you own is allowed. Exchange data agreements for non-professional subscribers typically allow personal use only and forbid giving others access. Alpaca's Business plan is priced per device. **Confirm with Alpaca support, or in your subscription agreement, before the first real upload.** In the meantime, `dataset-backup` stays a dry run unless you pass `--confirm`.

## Tests

`tests/test_backup.py` uses a local directory as the remote and a fake rclone runner, and never contacts Google Drive. It covers:

- manifest creation and deterministic checksums;
- secret exclusion;
- missing, corrupted and unexpected files;
- interrupted uploads and restores;
- duplicate snapshot ids and existing-destination protection;
- tampered metadata and path traversal;
- paths with spaces and CRLF bytes;
- POSIX paths that restore on any OS;
- the copy-only rclone command set.
