"""Trial readiness must be informational, offline, non-destructive."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import trial_readiness as readiness


class TrialReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in readiness.REQUIRED:
            (self.root / path).write_text("# synthetic test file\n", encoding="utf-8")
        self.version = SimpleNamespace(major=3, minor=11)

    def check(self, *, available=("git", "ollama", "docker"), tk=True, version=None):
        return readiness.assess(
            self.root, commands=lambda c: "/dummy/" + c if c in available else None,
            tk_available=tk, py_version=version or self.version,
            system_name="Windows",
        )

    def test_all_static_requirements_are_only_a_manual_trial_precheck(self):
        result = self.check()
        self.assertEqual(result["assessment"], "manual_trial_prerequisites_found")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["guarantees"], "none")
        self.assertIn("no_automatic_update_or_release_signature_verified", result["warnings"])
        self.assertIn("active_process_and_agent_lock_ownership_not_checked", result["warnings"])

    def test_existing_user_data_is_untouched_and_contents_not_listed(self):
        db = self.root / "state.sqlite3"
        db.write_bytes(b"private-data")
        workspace = self.root / "workspace"
        workspace.mkdir()
        (workspace / "SECRET-ACCESS-TOKEN.txt").write_text("SENSITIVE", encoding="utf-8")
        before_db = db.read_bytes()
        before_workspace = (workspace / "SECRET-ACCESS-TOKEN.txt").read_bytes()
        result = self.check()
        output = json.dumps(result, ensure_ascii=False)
        self.assertEqual(db.read_bytes(), before_db)
        self.assertEqual((workspace / "SECRET-ACCESS-TOKEN.txt").read_bytes(), before_workspace)
        self.assertNotIn("SENSITIVE", output)
        self.assertNotIn("SECRET-ACCESS-TOKEN", output)
        self.assertEqual(result["observations"]["existing_database"], "present")

    def test_missing_ollama_only_warns_gui_can_still_open(self):
        result = self.check(available=("git", "docker"))
        self.assertEqual(result["blockers"], [])
        self.assertIn("ollama_cli_not_found_ai_work_not_ready", result["warnings"])

    def test_missing_docker_does_not_enable_generated_tests(self):
        result = self.check(available=("git", "ollama"))
        self.assertIn("docker_cli_not_found_generated_tests_must_remain_disabled",
                      result["warnings"])
        self.assertEqual(result["guarantees"], "none")

    def test_python_and_tkinter_fail_closed(self):
        result = self.check(tk=False, version=SimpleNamespace(major=3, minor=10))
        self.assertEqual(result["assessment"], "not_ready")
        self.assertIn("python_3_11_or_later_required", result["blockers"])
        self.assertIn("tkinter_unavailable_for_gui", result["blockers"])

    def test_missing_source_file_blocks(self):
        (self.root / "sandbox_runner.py").unlink()
        result = self.check()
        self.assertEqual(result["assessment"], "not_ready")
        self.assertIn("sandbox_runner.py",
                      result["observations"]["required_files_not_regular"])

    def test_stop_marker_detected_without_removing_it(self):
        stop = self.root / "STOP"
        stop.write_bytes(b"")
        result = self.check()
        self.assertIn("stop_marker_present_tasks_will_not_run", result["warnings"])
        self.assertTrue(stop.exists())

    def test_links_are_not_followed(self):
        target = self.root / "agent.py"
        link = self.root / "sandbox_runner.py"
        link.unlink()
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlink creation unavailable")
        result = self.check()
        self.assertEqual(result["assessment"], "not_ready")
        self.assertIn("required_source_files_missing_or_unsafe", result["blockers"])

    def test_unsafe_database_marker_refused(self):
        (self.root / "state.sqlite3").mkdir()
        result = self.check()
        self.assertIn("existing_database_path_unsafe", result["blockers"])

    def test_cli_isolated_help_runs_without_importing_agent(self):
        script = Path(readiness.__file__).resolve()
        done = subprocess.run(
            [sys.executable, "-I", str(script), "--help"],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--json", done.stdout)


if __name__ == "__main__":
    unittest.main()
