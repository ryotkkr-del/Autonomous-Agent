"""Offline backup/recovery regression tests for P0-4 (works on Windows/Linux)."""
from pathlib import Path
from contextlib import closing
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import agent

S = importlib.util.spec_from_file_location(
    "safety_backup_under_test", Path(__file__).resolve().parents[1] / "safety_backup.py")
backup = importlib.util.module_from_spec(S)
S.loader.exec_module(backup)


class VerifiedBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.old = (agent.ROOT, agent.WORKSPACE, agent.DB)
        agent.ROOT = self.base / "app"
        agent.ROOT.mkdir()
        agent.WORKSPACE = agent.ROOT / "workspace"
        agent.DB = agent.ROOT / "state.sqlite3"
        agent.ensure_workspace()
        self.dest = self.base / "private-backups"

    def tearDown(self):
        agent.ROOT, agent.WORKSPACE, agent.DB = self.old
        self.tmp.cleanup()

    def _build_data(self):
        with agent.connection() as db:
            db.execute("INSERT INTO jobs(goal,status,created,updated) VALUES('important goal','paused','a','b')")
        folder = agent.WORKSPACE / "jobs" / "1"
        folder.mkdir(parents=True)
        (folder / "lesson.md").write_bytes(b"original lesson\r\n")
        return folder

    def test_consistent_wal_sqlite_backup_and_workspace_copy(self):
        folder = self._build_data()
        copied = backup.create_backup(agent.ROOT, self.dest, "f" * 40)
        self.assertTrue(copied.is_dir())
        manifest = backup.verify_snapshot(copied)
        self.assertEqual(manifest["source_commit"], "f" * 40)
        self.assertIn("state.sqlite3", manifest["files"])
        self.assertIn("workspace/jobs/1/lesson.md", manifest["files"])
        self.assertEqual((copied / "workspace/jobs/1/lesson.md").read_bytes(), b"original lesson\r\n")
        with closing(sqlite3.connect(copied / "state.sqlite3")) as db:
            self.assertEqual(db.execute("select goal from jobs limit 1").fetchone()[0], "important goal")
        self.assertEqual((folder / "lesson.md").read_bytes(), b"original lesson\r\n")
        self.assertFalse((agent.ROOT / "state.sqlite3-wal").exists()
                         and (copied / "state.sqlite3-wal").exists())

    def test_recover_is_non_destructive(self):
        folder = self._build_data()
        saved = backup.create_backup(agent.ROOT, self.dest)
        (folder / "lesson.md").write_text("CHANGED IN LIVE APPLICATION", encoding="utf-8")
        with closing(sqlite3.connect(agent.DB)) as db:
            db.execute("UPDATE jobs SET goal='CHANGED' WHERE id=1")
            db.commit()
        restored = backup.restore_to_new_directory(saved, self.base / "recover", agent.ROOT)
        self.assertEqual((restored / "workspace/jobs/1/lesson.md").read_bytes(), b"original lesson\r\n")
        with closing(sqlite3.connect(restored / "state.sqlite3")) as db:
            self.assertEqual(db.execute("select goal from jobs where id=1").fetchone()[0], "important goal")
        self.assertEqual((folder / "lesson.md").read_text(), "CHANGED IN LIVE APPLICATION")
        with sqlite3.connect(agent.DB) as db:
            self.assertEqual(db.execute("select goal from jobs where id=1").fetchone()[0], "CHANGED")
        with self.assertRaisesRegex(ValueError, "not already exist"):
            backup.restore_to_new_directory(saved, self.base / "recover", agent.ROOT)

    def test_checksums_reject_corruption_and_no_recovery_directory(self):
        self._build_data()
        saved = backup.create_backup(agent.ROOT, self.dest)
        (saved / "workspace/jobs/1/lesson.md").write_bytes(b"corrupted!")
        with self.assertRaisesRegex(ValueError, "checksum"):
            backup.verify_snapshot(saved)
        recovery = self.base / "recover"
        with self.assertRaisesRegex(ValueError, "checksum"):
            backup.restore_to_new_directory(saved, recovery, agent.ROOT)
        self.assertFalse(recovery.exists())

    def test_manifest_rejects_path_traversal(self):
        self._build_data()
        saved = backup.create_backup(agent.ROOT, self.dest)
        manifest_file = saved / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        record = next(v for k, v in manifest["files"].items() if k.startswith("workspace/"))
        manifest["files"] = {"workspace/../../../outside": record}
        manifest_file.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "traversal|unsafe"):
            backup.verify_snapshot(saved)

    def test_symlink_is_refused_and_partial_snapshot_removed(self):
        self._build_data()
        outside = self.base / "outside.txt"
        outside.write_text("private")
        try:
            (agent.WORKSPACE / "link.txt").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "links|reparse"):
            backup.create_backup(agent.ROOT, self.dest)
        self.assertFalse(any(p.name.startswith(".partial") for p in self.dest.iterdir()))

    def test_hardlink_is_refused(self):
        outside = self.base / "outside.txt"
        outside.write_text("private")
        try:
            os.link(outside, agent.WORKSPACE / "clone.txt")
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks unavailable")
        with self.assertRaisesRegex(ValueError, "hard-linked"):
            backup.create_backup(agent.ROOT, self.dest)
        self.assertEqual(outside.read_text(), "private")

    def test_oversized_source_fails_closed(self):
        (agent.WORKSPACE / "big.txt").write_bytes(b"x" * 25)
        with patch.object(backup, "MAX_SINGLE_FILE", 10):
            with self.assertRaisesRegex(ValueError, "limit"):
                backup.create_backup(agent.ROOT, self.dest)
        self.assertFalse(any(x.name.startswith("snapshot-") for x in self.dest.iterdir()))

    def test_missing_db_is_recorded_not_fake_restored(self):
        saved = backup.create_backup(agent.ROOT, self.dest)
        info = backup.verify_snapshot(saved)
        self.assertFalse(info["database_present"])
        self.assertNotIn("state.sqlite3", info["files"])
        dest = backup.restore_to_new_directory(saved, self.base / "recover", agent.ROOT)
        self.assertFalse((dest / "state.sqlite3").exists())

    def test_backup_location_inside_checkout_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            backup.create_backup(agent.ROOT, agent.ROOT / "backups")
        self.assertFalse((agent.ROOT / "backups").exists())

    def test_recovery_cannot_overwrite_live_repository(self):
        self._build_data()
        saved = backup.create_backup(agent.ROOT, self.dest)
        with self.assertRaisesRegex(ValueError, "outside"):
            backup.restore_to_new_directory(saved, agent.ROOT / "recovery", agent.ROOT)
        self.assertFalse((agent.ROOT / "recovery").exists())

    def test_empty_or_invalid_revision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA"):
            backup.create_backup(agent.ROOT, self.dest, "main; malicious")

    def test_reject_extra_file_inside_backup(self):
        self._build_data()
        saved = backup.create_backup(agent.ROOT, self.dest)
        (saved / "extra-file.exe").write_bytes(b"junk")
        with self.assertRaisesRegex(ValueError, "unexpected extra"):
            backup.verify_snapshot(saved)


if __name__ == "__main__":
    unittest.main()
