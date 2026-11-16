"""P0-5: offline, synthetic crash-recovery audit regression tests."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent
import recovery_audit as audit


class RecoveryAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-recovery-audit-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "app"
        self.root.mkdir()
        (self.root / "STOP").write_bytes(b"")
        (self.root / "agent.lock").write_bytes(b"0")
        self.db = self.root / "state.sqlite3"

    def database(self, status="paused"):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT, goal TEXT)")
            conn.execute("INSERT INTO jobs VALUES (1, ?, 'DO_NOT_LEAK')", (status,))
            conn.commit()

    def invoke(self, snapshot=None):
        return audit.inspect_recovery(self.root, snapshot=snapshot)

    def test_clean_sqlite_is_read_without_writes_or_sidecars(self):
        self.database()
        contents = self.db.read_bytes()
        before = self.db.stat().st_mtime_ns
        names_before = {p.name for p in self.root.iterdir()}
        report = self.invoke()
        self.assertEqual(report["assessment"], "read_only_checks_completed")
        self.assertEqual(report["active"]["sqlite"]["running_job_count"], 0)
        self.assertFalse(report["active_files_modified"])
        self.assertFalse(report["automatic_restore_performed"])
        self.assertFalse(report["safe_to_resume_or_replace"])
        self.assertEqual(contents, self.db.read_bytes())
        self.assertEqual(before, self.db.stat().st_mtime_ns)
        self.assertEqual(names_before, {p.name for p in self.root.iterdir()})
        self.assertNotIn("DO_NOT_LEAK", json.dumps(report))

    def test_stale_running_job_fails_closed_without_resetting_status(self):
        self.database(status="running")
        before = self.db.read_bytes()
        report = self.invoke()
        self.assertEqual(report["assessment"], "needs_manual_review")
        self.assertEqual(report["active"]["sqlite"]["reason"], "stale_running_jobs")
        self.assertEqual(report["active"]["sqlite"]["running_job_count"], 1)
        self.assertEqual(self.db.read_bytes(), before)

    def test_corrupt_database_rejected_without_creating_other_files(self):
        self.db.write_bytes(b"NOT A SQLITE DATABASE" * 8)
        result = self.invoke()
        self.assertEqual(result["assessment"], "needs_manual_review")
        self.assertEqual(result["active"]["sqlite"]["reason"],
                         "database_could_not_be_verified")
        self.assertEqual(self.db.read_bytes(), b"NOT A SQLITE DATABASE" * 8)
        self.assertFalse((self.root / "state.sqlite3-wal").exists())

    def test_missing_database_and_existing_workspace_requires_review(self):
        (self.root / "workspace").mkdir()
        result = self.invoke()
        self.assertEqual(result["assessment"], "needs_manual_review")
        self.assertEqual(result["active"]["sqlite"]["reason"],
                         "workspace_exists_without_database")
        self.assertFalse(self.db.exists())

    def test_existing_wal_blocks_immutable_main_db_inspection(self):
        self.database(status="paused")
        (self.root / "state.sqlite3-wal").write_bytes(b"uncheckpointed")
        before = (self.root / "state.sqlite3-wal").read_bytes()
        result = self.invoke()
        self.assertEqual(result["active"]["sqlite"]["reason"],
                         "sqlite_auxiliary_files_present")
        self.assertEqual((self.root / "state.sqlite3-wal").read_bytes(), before)
        self.assertTrue(self.db.exists())

    def test_orphan_wal_refused(self):
        (self.root / "state.sqlite3-wal").write_bytes(b"orphan")
        report = self.invoke()
        self.assertEqual(report["assessment"], "needs_manual_review")
        self.assertEqual(report["active"]["sqlite"]["reason"],
                         "sqlite_auxiliary_files_present")
        self.assertFalse(self.db.exists())

    def test_abrupt_process_exit_with_uncheckpointed_wal_is_not_ignored(self):
        script = (
            "import os,sqlite3,sys\n"
            "db=sqlite3.connect(sys.argv[1]);db.execute('PRAGMA journal_mode=WAL');"
            "db.execute('CREATE TABLE jobs (id INT, status TEXT)');"
            "db.execute(\"INSERT INTO jobs VALUES (1,'running')\");db.commit();"
            "os._exit(29)\n"
        )
        result = subprocess.run([sys.executable, "-c", script, str(self.db)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 29, result.stderr)
        wal = self.root / "state.sqlite3-wal"
        self.assertTrue(wal.exists())
        before = wal.read_bytes()
        report = self.invoke()
        self.assertEqual(report["assessment"], "needs_manual_review")
        self.assertEqual(report["active"]["sqlite"]["reason"],
                         "sqlite_auxiliary_files_present")
        self.assertEqual(wal.read_bytes(), before)

    def test_symlink_in_data_is_refused_without_reading_target(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        external = self.base / "SECRET-OUTSIDE"
        external.write_bytes(b"PRIVATE")
        try:
            (workspace / "linked").symlink_to(external)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        report = self.invoke()
        self.assertEqual(report["assessment"], "needs_manual_review")
        self.assertEqual(report["active"]["data_folders"]["reason"],
                         "link_or_reparse_detected")
        self.assertEqual(external.read_bytes(), b"PRIVATE")
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_hardlink_in_data_is_refused(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        outside = self.base / "outside"
        outside.write_bytes(b"unchanged")
        try:
            os.link(outside, workspace / "hardlink")
        except OSError:
            self.skipTest("hardlinks unavailable")
        report = self.invoke()
        self.assertEqual(report["active"]["data_folders"]["reason"],
                         "data_hardlink_detected")
        self.assertEqual(outside.read_bytes(), b"unchanged")

    def test_empty_stop_marker_is_required_and_not_created(self):
        stop = self.root / "STOP"
        stop.unlink()
        report = self.invoke()
        self.assertEqual(report["assessment"], "refused")
        self.assertFalse(stop.exists())
        self.assertFalse(report["safe_to_resume_or_replace"])

    def test_existing_lock_required_and_not_created(self):
        lock = self.root / "agent.lock"
        lock.unlink()
        report = self.invoke()
        self.assertEqual(report["assessment"], "refused")
        self.assertFalse(lock.exists())

    def test_lock_conflict_rejected_without_database_read(self):
        self.database()
        old_root = agent.ROOT
        agent.ROOT = self.root
        try:
            with agent.single_runner():
                report = self.invoke()
        finally:
            agent.ROOT = old_root
        self.assertEqual(report["assessment"], "refused")
        self.assertNotIn("active", report)

    def make_snapshot(self):
        target = self.base / "snapshot"
        target.mkdir()
        copied = target / "state.sqlite3"
        shutil.copyfile(self.db, copied)
        digest = hashlib.sha256(copied.read_bytes()).hexdigest()
        metadata = {
            "format": "autonomous-agent-backup-v1",
            "created_utc": "2026-11-16T00:00:00+00:00",
            "source_commit": None,
            "database_present": True,
            "files": {"state.sqlite3": {"sha256": digest, "bytes": copied.stat().st_size}},
        }
        (target / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
        return target

    def test_valid_backup_is_verified_but_not_restored(self):
        self.database()
        target = self.make_snapshot()
        contents = self.db.read_bytes()
        report = self.invoke(snapshot=target)
        self.assertEqual(report["backup"]["status"], "checksums_and_integrity_verified")
        self.assertEqual(report["backup"]["file_count"], 1)
        self.assertEqual(self.db.read_bytes(), contents)
        self.assertFalse(report["automatic_restore_performed"])

    def test_corrupt_snapshot_does_not_replace_the_active_database(self):
        self.database()
        target = self.make_snapshot()
        before = self.db.read_bytes()
        (target / "state.sqlite3").write_bytes(b"tampered")
        report = self.invoke(snapshot=target)
        self.assertEqual(report["assessment"], "needs_manual_review")
        self.assertEqual(report["backup"]["reason"], "backup_verification_failed")
        self.assertEqual(self.db.read_bytes(), before)

    def test_help_and_missing_opt_in_flag_do_not_open_app_database(self):
        script = Path(audit.__file__).resolve()
        for args, code in ((["--help"], 0), ([], 2)):
            with self.subTest(args=args):
                completed = subprocess.run([sys.executable, "-I", str(script), *args],
                                           capture_output=True, text=True, timeout=20)
                self.assertEqual(completed.returncode, code)
                self.assertFalse(self.db.exists())
                self.assertFalse((self.root / "workspace").exists())


if __name__ == "__main__":
    unittest.main()
