"""P0-5: fail-closed, read-only inspection before manual crash recovery.

This program NEVER creates STOP/agent.lock, opens a writable database,
changes job status, checkpoints WAL, starts the agent, restores files, or
clears crash artifacts. It inspects an installed app only while an existing
STOP and agent single-runner lock are held. The CLI cannot select an
arbitrary app root. The manifest of an optional existing data backup is
verified read-only. "clean" is NOT an authorization to replace active data.

Power loss, OS bugs, and uncooperative processes remain outside its guarantee.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

# Required when the script is run with isolated Python (-I).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_maintenance_guard
import safety_backup

APP_ROOT = Path(__file__).resolve().parent
MAX_DB_BYTES = 500 * 1024 * 1024
MAX_FILES = 5000
MAX_NODES = 10000
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_SINGLE_FILE = 100 * 1024 * 1024
AUX_SUFFIXES = ("-wal", "-shm", "-journal")
DATA_DIRS = ("workspace", "benchmark-results")


def _plain_stat(path: Path) -> os.stat_result:
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or
            getattr(info, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise ValueError("link_or_reparse_detected")
    return info


def _check_workspace(root: Path) -> dict:
    """Bounded metadata-only walk; never follow directory links."""
    files = 0
    nodes = 0
    total = 0
    for name in DATA_DIRS:
        base = root / name
        if not os.path.lexists(base):
            continue
        info = _plain_stat(base)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("data_root_not_directory")
        pending = [base]
        while pending:
            folder = pending.pop()
            with os.scandir(folder) as entries:
                for item in entries:
                    nodes += 1
                    if nodes > MAX_NODES:
                        raise ValueError("data_tree_node_limit")
                    info = _plain_stat(Path(item.path))
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(item.path))
                    elif stat.S_ISREG(info.st_mode):
                        if info.st_nlink != 1:
                            raise ValueError("data_hardlink_detected")
                        files += 1
                        total += info.st_size
                        if info.st_size > MAX_SINGLE_FILE:
                            raise ValueError("data_file_too_large")
                        if files > MAX_FILES or total > MAX_TOTAL_BYTES:
                            raise ValueError("data_tree_limit")
                    else:
                        raise ValueError("data_special_file")
    return {"status": "metadata_checked", "files": files, "bytes": total}


def _check_sqlite(root: Path) -> dict:
    """No WAL is ignored: stop before touching the database if any exists."""
    db = root / "state.sqlite3"
    for suffix in AUX_SUFFIXES:
        if os.path.lexists(str(db) + suffix):
            # A live or orphan WAL is NOT proof of damage. A standalone
            # immutable read would silently miss uncheckpointed transactions.
            return {"status": "needs_manual_review", "reason": "sqlite_auxiliary_files_present"}
    if not os.path.lexists(db):
        return {"status": "not_present"}
    try:
        info = _plain_stat(db)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return {"status": "needs_manual_review", "reason": "database_path_unsafe"}
        if info.st_size > MAX_DB_BYTES:
            return {"status": "needs_manual_review", "reason": "database_size_limit"}
        if info.st_size < 100:
            return {"status": "needs_manual_review", "reason": "database_too_small"}

        # sqlite URI immutable mode prevents sidecar creation/checkpoint and
        # requires the previous absence-of-WAL check. Recheck after inspection
        # as a best effort against other processes that do not obey the lock.
        uri = db.as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                return {"status": "needs_manual_review", "reason": "sqlite_integrity_failed"}
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
            if table is None:
                return {"status": "needs_manual_review", "reason": "jobs_table_missing"}
            # Only counts are returned: never display task content.
            count = int(conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='running'"
            ).fetchone()[0])
        if any(os.path.lexists(str(db) + suffix) for suffix in AUX_SUFFIXES):
            return {"status": "needs_manual_review", "reason": "sqlite_auxiliary_files_appeared"}
        if count is not None and count:
            return {"status": "needs_manual_review", "reason": "stale_running_jobs",
                    "running_job_count": count}
        return {"status": "integrity_checked", "running_job_count": count}
    except (OSError, sqlite3.Error, ValueError):
        return {"status": "needs_manual_review", "reason": "database_could_not_be_verified"}


def audit_data(root: Path) -> dict:
    """Inspect metadata and SQLite without changing the application state.

    Caller MUST hold release_maintenance_guard.hold_stop_lock(root) until this
    result is no longer being relied upon; this method itself is not a lock.
    """
    root = Path(root)
    sqlite_result = _check_sqlite(root)
    try:
        trees = _check_workspace(root)
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "data_tree_unreadable"
        trees = {"status": "needs_manual_review", "reason": reason}
    if (sqlite_result["status"] == "not_present" and
            os.path.lexists(root / "workspace")):
        sqlite_result = {"status": "needs_manual_review",
                         "reason": "workspace_exists_without_database"}
    blocked = (sqlite_result["status"] == "needs_manual_review" or
               trees["status"] == "needs_manual_review")
    return {"status": "needs_manual_review" if blocked else "inspection_clean",
            "sqlite": sqlite_result, "data_folders": trees}


def inspect_recovery(root: Path = APP_ROOT, *, snapshot: Path | None = None) -> dict:
    """Run while stopped, return sanitized categories; NEVER change live data."""
    try:
        with release_maintenance_guard.hold_stop_lock(root):
            active = audit_data(root)
            backup_result = {"status": "not_checked"}
            if snapshot is not None:
                try:
                    verified = safety_backup.verify_snapshot(Path(snapshot))
                    backup_result = {
                        "status": "checksums_and_integrity_verified",
                        "file_count": len(verified["files"]),
                    }
                except (OSError, ValueError, sqlite3.Error, TypeError, KeyError):
                    backup_result = {"status": "needs_manual_review",
                                     "reason": "backup_verification_failed"}
            blocked = (active["status"] != "inspection_clean" or
                       backup_result["status"] == "needs_manual_review")
            return {
                "assessment": "needs_manual_review" if blocked else "read_only_checks_completed",
                "active": active, "backup": backup_result,
                "active_files_modified": False,
                "automatic_restore_performed": False,
                "safe_to_resume_or_replace": False,
                "limits": [
                    "this_does_not_authorize_resuming_jobs_or_replacing_data",
                    "no_automatic_wal_checkpoint_or_running_job_reset",
                    "uncooperative_processes_and_power_loss_not_excluded",
                ],
            }
    except (OSError, ValueError, RuntimeError):
        return {
            "assessment": "refused",
            "reason": "stop_or_exclusive_lock_unavailable_or_unsafe",
            "active_files_modified": False,
            "automatic_restore_performed": False,
            "safe_to_resume_or_replace": False,
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only STOP+lock guarded crash-recovery audit (never restore)")
    parser.add_argument("--check", action="store_true", required=True,
                        help="use existing STOP and agent.lock without modifying them")
    parser.add_argument("--snapshot", type=Path,
                        help="optionally verify existing backup manifest and checksums")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_recovery(snapshot=args.snapshot)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("復旧前の読み取り専用確認:", report["assessment"])
        if "active" in report:
            print("SQLite:", report["active"]["sqlite"]["status"])
            print("Data:", report["active"]["data_folders"]["status"])
            print("Backup:", report["backup"]["status"])
        print("自動復旧・ジョブ再開・SQLiteの書換は行いません。")
    return 0 if report["assessment"] == "read_only_checks_completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
