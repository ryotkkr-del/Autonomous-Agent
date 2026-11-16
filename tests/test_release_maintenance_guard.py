"""Cross-platform P0-4 maintenance guard tests; only synthetic temp roots."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import release_maintenance_guard as guard


class MaintenanceGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aa-maintenance-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "agent.lock").write_bytes(b"0")
        (self.root / "STOP").write_bytes(b"")
        (self.root / "state.sqlite3").write_bytes(b"dummy SQLite bytes, not opened")
        (self.root / "workspace").mkdir()
        (self.root / "workspace" / "note.txt").write_bytes(b"unchanged")

    def test_success_is_read_only_and_valid_only_in_context(self):
        before = (self.root / "agent.lock").read_bytes()
        with guard.hold_stop_lock(self.root) as result:
            self.assertEqual(result["status"], "held_test_only")
            self.assertFalse(result["application_changes"])
            # Windows byte-range locks also block reads from another handle.
            # Verify metadata while held and compare bytes only after unlock.
            self.assertEqual((self.root / "agent.lock").stat().st_size, len(before))
        self.assertEqual((self.root / "agent.lock").read_bytes(), before)
        self.assertEqual((self.root / "STOP").read_bytes(), b"")
        self.assertEqual((self.root / "state.sqlite3").read_bytes(),
                         b"dummy SQLite bytes, not opened")
        self.assertEqual((self.root / "workspace" / "note.txt").read_bytes(), b"unchanged")
        self.assertEqual(set(p.name for p in self.root.iterdir()),
                         {"STOP", "agent.lock", "state.sqlite3", "workspace"})

    def test_missing_stop_is_fail_closed(self):
        (self.root / "STOP").unlink()
        with self.assertRaises(FileNotFoundError):
            with guard.hold_stop_lock(self.root):
                self.fail("must not yield without STOP")
        self.assertEqual((self.root / "agent.lock").read_bytes(), b"0")

    def test_missing_or_empty_lock_is_fail_closed_without_creation(self):
        (self.root / "agent.lock").unlink()
        with self.assertRaises(FileNotFoundError):
            with guard.hold_stop_lock(self.root):
                self.fail("must not create a new lock")
        self.assertFalse((self.root / "agent.lock").exists())
        (self.root / "agent.lock").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "nonempty"):
            with guard.hold_stop_lock(self.root):
                self.fail("must not use empty lock")

    def test_oversized_control_files_fail_closed(self):
        (self.root / "STOP").write_bytes(b"X" * 129)
        with self.assertRaisesRegex(ValueError, "STOP marker"):
            with guard.hold_stop_lock(self.root):
                self.fail("oversized STOP")
        (self.root / "STOP").write_bytes(b"")
        (self.root / "agent.lock").write_bytes(b"X" * 4097)
        with self.assertRaisesRegex(ValueError, "lock must"):
            with guard.hold_stop_lock(self.root):
                self.fail("oversized lock")

    def test_revoked_stop_is_detected_before_context_exit(self):
        with self.assertRaises(FileNotFoundError):
            with guard.hold_stop_lock(self.root):
                (self.root / "STOP").unlink()
        self.assertEqual((self.root / "agent.lock").read_bytes(), b"0")

    def _in_child(self, body: str):
        script = (
            "from pathlib import Path\n"
            "import sys\n"
            f"sys.path.insert(0, {str(Path(guard.__file__).resolve().parent)!r})\n"
            + body
        )
        return subprocess.run(
            [sys.executable, "-I", "-c", script, str(self.root)],
            capture_output=True, text=True, timeout=15
        )

    def test_competing_maintenance_process_cannot_enter(self):
        program = (
            "import release_maintenance_guard as m\n"
            "try:\n"
            "    with m.hold_stop_lock(Path(sys.argv[1])): pass\n"
            "except (OSError, RuntimeError, ValueError):\n"
            "    sys.exit(7)\n"
            "sys.exit(0)\n"
        )
        with guard.hold_stop_lock(self.root):
            result = self._in_child(program)
            self.assertEqual(result.returncode, 7, result.stderr)

    def test_agent_single_runner_cannot_enter_maintenance_lock(self):
        # Exercise the ACTUAL agent.single_runner lock implementation in a
        # separate process with its ROOT redirected to a disposable directory.
        program = (
            "import agent\n"
            "agent.ROOT = Path(sys.argv[1])\n"
            "try:\n"
            "    with agent.single_runner(): pass\n"
            "except (OSError, RuntimeError):\n"
            "    sys.exit(7)\n"
            "sys.exit(0)\n"
        )
        with guard.hold_stop_lock(self.root):
            result = self._in_child(program)
            self.assertEqual(result.returncode, 7, result.stderr)

    def test_linked_stop_and_lock_rejected(self):
        marker = self.root / "STOP"
        marker.unlink()
        try:
            marker.symlink_to(self.root / "state.sqlite3")
        except OSError:
            self.skipTest("Windows runner does not permit symlinks")
        with self.assertRaisesRegex(ValueError, "symlink|reparse"):
            with guard.hold_stop_lock(self.root):
                self.fail("linked STOP")
        marker.unlink()
        marker.write_bytes(b"")
        lock = self.root / "agent.lock"
        lock.unlink()
        lock.symlink_to(self.root / "state.sqlite3")
        with self.assertRaisesRegex(ValueError, "symlink|reparse"):
            with guard.hold_stop_lock(self.root):
                self.fail("linked lock")

    def test_root_symlink_rejected(self):
        alias = self.root.parent / (self.root.name + "-alias")
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink unavailable")
        try:
            with self.assertRaisesRegex(ValueError, "symlink|reparse"):
                with guard.hold_stop_lock(alias):
                    self.fail("linked root")
        finally:
            alias.unlink()

    def test_isolated_python_help_still_works(self):
        script = Path(guard.__file__).resolve()
        result = subprocess.run([sys.executable, "-I", str(script), "--help"],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--check", result.stdout)


if __name__ == "__main__":
    unittest.main()
