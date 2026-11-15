"""P0-4/P0-5: verified, offline backup before any development update.

Backups are outside the Git checkout. SQLite is copied using its backup API,
not by naively copying an open WAL database. Restoration always targets a NEW,
empty directory; it never modifies the active agent or changes Git revisions.

The backup manifest is a corruption detector, NOT a cryptographic signature:
anyone with write access to backup files can potentially replace the manifest.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import uuid

import agent

MAX_FILES = 5000
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_SINGLE_FILE = 100 * 1024 * 1024
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-fA-F]{40,64}\Z")
SNAPSHOT_RE = re.compile(r"snapshot-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\Z")
DATA_DIRS = ("workspace", "benchmark-results")


def default_backup_root() -> Path:
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA")
        if not base:
            raise ValueError("LOCALAPPDATA missing; backup location cannot be trusted")
        return Path(base) / "AutonomousAgent" / "backups"
    return Path.home() / ".local" / "share" / "AutonomousAgent" / "backups"


def _is_link_or_special(path: Path) -> bool:
    details = path.lstat()
    if path.is_symlink():
        return True
    if os.name == "nt" and details.st_file_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        return True
    return not (stat.S_ISREG(details.st_mode) or stat.S_ISDIR(details.st_mode))


def _check_tree_path(path: Path) -> None:
    if path.is_symlink() or _is_link_or_special(path):
        raise ValueError("links, reparse points and special files cannot be backed up")
    if path.is_file() and path.stat().st_nlink > 1:
        raise ValueError("hard-linked files cannot be backed up")


def _backup_destination(root: Path, repo: Path) -> Path:
    repo = repo.resolve(strict=True)
    # Resolve parent symlinks, including when the backup folder does not exist.
    root = root.expanduser().absolute()
    if root == repo or root.is_relative_to(repo) or root.resolve().is_relative_to(repo):
        raise ValueError("backup destination must be outside the repository")
    for path in (root, *root.parents):
        if path.exists() and _is_link_or_special(path):
            raise ValueError("backup destination path includes a link/reparse point")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _file_sha256(path: Path) -> tuple[str, int]:
    checksum = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_SINGLE_FILE:
                raise ValueError("individual file exceeds backup limit")
            checksum.update(block)
    return checksum.hexdigest(), total


def _snapshot_sqlite(source: Path, dest: Path) -> bool:
    if not source.exists():
        return False
    _check_tree_path(source)
    if not source.is_file():
        raise ValueError("SQLite source must be a regular file")
    if source.stat().st_size > MAX_TOTAL_BYTES:
        raise ValueError("SQLite database exceeds backup limit")
    # Do not create or migrate the source database.
    uri = source.resolve(strict=True).as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=8)) as live, \
         closing(sqlite3.connect(dest, timeout=8)) as backup:
        live.backup(backup, pages=256, sleep=0.01)
        backup.commit()
        check = backup.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise ValueError("SQLite backup failed integrity_check")
    return True


def _copy_tree(source: Path, dest: Path, paths: dict[str, dict[str, object]]) -> None:
    _check_tree_path(source)
    if not source.is_dir():
        raise ValueError("backup source must be a directory")
    dest.mkdir(parents=True, exist_ok=False)
    for folder, dirnames, filenames in os.walk(source, followlinks=False):
        base = Path(folder)
        _check_tree_path(base)
        for name in dirnames + filenames:
            _check_tree_path(base / name)
        for name in dirnames:
            (dest / (base / name).relative_to(source)).mkdir(exist_ok=False)
        for name in filenames:
            current = base / name
            if not current.is_file():
                raise ValueError("nonregular backup source")
            rel = current.relative_to(source)
            destination = dest / rel
            before = current.stat()
            if before.st_size > MAX_SINGLE_FILE:
                raise ValueError("individual file exceeds backup limit")
            shutil.copyfile(current, destination, follow_symlinks=False)
            after = current.stat()
            if ((before.st_size, before.st_mtime_ns, before.st_ino)
                    != (after.st_size, after.st_mtime_ns, after.st_ino)):
                raise ValueError("file changed during backup; refusing inconsistent snapshot")
            digest, size = _file_sha256(destination)
            paths[destination.relative_to(dest.parent).as_posix()] = {"sha256": digest, "bytes": size}
            if len(paths) > MAX_FILES or sum(x["bytes"] for x in paths.values()) > MAX_TOTAL_BYTES:
                raise ValueError("backup exceeds file count or total size limit")


def _manifest_file(snapshot: Path) -> Path:
    return snapshot / "manifest.json"


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("invalid manifest path")
    p = PurePosixPath(name)
    if (p.is_absolute() or not p.parts or
            any(x in ("", ".", "..") for x in p.parts) or
            p.as_posix() != name):
        raise ValueError("manifest contains a traversal or unsafe path")
    if p.parts[0] not in (*DATA_DIRS, "state.sqlite3"):
        raise ValueError("unexpected backup file path")
    if p.parts[0] == "state.sqlite3" and len(p.parts) != 1:
        raise ValueError("unexpected SQLite path")


def verify_snapshot(snapshot: Path) -> dict:
    snapshot = Path(snapshot)
    if not snapshot.is_dir() or _is_link_or_special(snapshot):
        raise ValueError("snapshot directory missing or unsafe")
    manifest_file = _manifest_file(snapshot)
    _check_tree_path(manifest_file)
    if manifest_file.stat().st_size > 2_000_000:
        raise ValueError("manifest exceeds limit")
    metadata = json.loads(manifest_file.read_text(encoding="utf-8"))
    if metadata.get("format") != "autonomous-agent-backup-v1":
        raise ValueError("unsupported backup format")
    expected = metadata.get("files")
    if not isinstance(expected, dict) or len(expected) > MAX_FILES:
        raise ValueError("invalid backup file listing")
    if type(metadata.get("database_present")) is not bool:
        raise ValueError("invalid database presence flag")
    total = 0
    for name, record in expected.items():
        _check_name(name)
        if (not isinstance(record, dict) or
                not isinstance(record.get("sha256"), str) or
                not SHA_RE.fullmatch(record["sha256"]) or
                type(record.get("bytes")) is not int or record["bytes"] < 0):
            raise ValueError("invalid backup manifest entry")
        path = snapshot.joinpath(*PurePosixPath(name).parts)
        _check_tree_path(path)
        if not path.is_file():
            raise ValueError("missing backup file")
        digest, size = _file_sha256(path)
        if digest != record["sha256"] or size != record["bytes"]:
            raise ValueError("backup checksum or size mismatch: " + name)
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("backup exceeds total size limit")
    if metadata["database_present"] != ("state.sqlite3" in expected):
        raise ValueError("SQLite presence mismatch")
    for path in snapshot.rglob("*"):
        _check_tree_path(path)
        if path.is_file() and path.relative_to(snapshot).as_posix() not in set(expected) | {"manifest.json"}:
            raise ValueError("unexpected extra file in backup")
    if metadata["database_present"]:
        # Reopen SQLite read-only and check integrity without mutating backup.
        path = snapshot / "state.sqlite3"
        with closing(sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise ValueError("backup SQLite integrity_check failed")
    return metadata


def create_backup(root: Path, backup_root: Path, revision: str = "") -> Path:
    root = Path(root).resolve(strict=True)
    if revision and not COMMIT_RE.fullmatch(revision):
        raise ValueError("source revision must be a complete Git SHA")
    destination = _backup_destination(Path(backup_root), root)
    # Never trust arbitrary data supplied via other directories.
    import agent
    if root != agent.ROOT.resolve(strict=True):
        raise ValueError("backup requires the active agent installation directory")
    with agent.single_runner():
        snapshot_id = "snapshot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
        draft = destination / (".partial-" + snapshot_id)
        final = destination / snapshot_id
        draft.mkdir(mode=0o700)
        try:
            files: dict[str, dict[str, object]] = {}
            db = root / "state.sqlite3"
            if _snapshot_sqlite(db, draft / "state.sqlite3"):
                digest, size = _file_sha256(draft / "state.sqlite3")
                files["state.sqlite3"] = {"sha256": digest, "bytes": size}
            for name in DATA_DIRS:
                source = root / name
                if source.exists() or source.is_symlink():
                    _copy_tree(source, draft / name, files)
            if len(files) > MAX_FILES or sum(x["bytes"] for x in files.values()) > MAX_TOTAL_BYTES:
                raise ValueError("backup exceeds global safety limits")
            metadata = {
                "format": "autonomous-agent-backup-v1",
                "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_commit": revision.lower() if revision else None,
                "database_present": "state.sqlite3" in files,
                "files": files,
            }
            _manifest_file(draft).write_text(
                json.dumps(metadata, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            verify_snapshot(draft)
            draft.rename(final)
            return final
        except Exception:
            shutil.rmtree(draft, ignore_errors=True)
            raise


def restore_to_new_directory(snapshot: Path, recovery_root: Path, repository: Path) -> Path:
    """Verify then restore to a new directory. Never overwrite active data."""
    metadata = verify_snapshot(snapshot)
    recovery_root = Path(recovery_root).absolute()
    repository = Path(repository).resolve(strict=True)
    if recovery_root.resolve().is_relative_to(repository):
        raise ValueError("recovery destination must be outside the installation")
    if recovery_root.exists() or recovery_root.is_symlink():
        raise ValueError("recovery destination must not already exist")
    for parent in recovery_root.parents:
        if parent.exists() and _is_link_or_special(parent):
            raise ValueError("recovery parent contains a link/reparse point")
    recovery_root.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".recovery-", dir=recovery_root.parent))
    try:
        for name, entry in metadata["files"].items():
            _check_name(name)
            src = Path(snapshot).joinpath(*PurePosixPath(name).parts)
            dest = staged.joinpath(*PurePosixPath(name).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest, follow_symlinks=False)
            digest, size = _file_sha256(dest)
            if digest != entry["sha256"] or size != entry["bytes"]:
                raise ValueError("recovery checksum mismatch")
        staged.rename(recovery_root)
        return recovery_root
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Create/verify/recover agent data without changing active files")
    sub = p.add_subparsers(dest="operation", required=True)
    create = sub.add_parser("create")
    create.add_argument("--revision", default="")
    create.add_argument("--backup-root", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("--snapshot", type=Path, required=True)
    restore = sub.add_parser("recover")
    restore.add_argument("--snapshot", type=Path, required=True)
    restore.add_argument("--into", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.operation == "create":
            result = create_backup(agent.ROOT, args.backup_root or default_backup_root(), args.revision)
            print("BACKUP OK:", result)
        elif args.operation == "verify":
            result = verify_snapshot(args.snapshot)
            print("VERIFIED:", len(result["files"]), "files; source commit:", result["source_commit"])
        else:
            result = restore_to_new_directory(args.snapshot, args.into, agent.ROOT)
            print("RECOVERY COPY OK:", result)
            print("Active SQLite, workspace, and Git checkout were NOT modified.")
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print("BACKUP/RECOVERY REFUSED:", str(exc)[:500], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
