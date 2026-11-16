"""Windows/Linux isolated fault-injection regression tests; no real updater."""
from contextlib import closing
import sqlite3
import unittest

from release_switch_trial import Trial, SimulatedInterruption


class SwitchTrialTests(unittest.TestCase):
    def setUp(self):
        self.trial = Trial()
        self.addCleanup(self.trial.close)
        self.original_db = (self.trial.data / "state.sqlite3").read_bytes()
        self.original_note = (self.trial.data / "workspace" / "note.txt").read_bytes()

    def assert_data_unchanged(self):
        self.assertEqual((self.trial.data / "state.sqlite3").read_bytes(), self.original_db)
        self.assertEqual((self.trial.data / "workspace" / "note.txt").read_bytes(), self.original_note)
        with closing(sqlite3.connect(self.trial.data / "state.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT value FROM progress").fetchone()[0], "keep me")

    def test_successful_pointer_switch_preserves_old_and_data(self):
        self.trial.switch()
        self.assertEqual(self.trial.current(), "new")
        self.assertEqual(self.trial.recover(), "new")
        self.assertTrue((self.trial.root / "versions" / "old" / "agent.py").exists())
        self.assertFalse((self.trial.root / "transaction.json").exists())
        self.assert_data_unchanged()

    def test_interruption_at_each_phase_recovers_old_code_without_data_loss(self):
        for phase in ("after_prepare", "after_pointer", "after_verify"):
            with self.subTest(phase=phase), Trial() as trial:
                with self.assertRaises(SimulatedInterruption):
                    trial.switch(fail_at=phase)
                self.assertEqual(trial.recover(), "old")
                self.assertFalse((trial.root / "transaction.json").exists())
                self.assertTrue((trial.root / "versions" / "new" / "agent.py").exists())
                with closing(sqlite3.connect(trial.data / "state.sqlite3")) as db:
                    self.assertEqual(db.execute("SELECT value FROM progress").fetchone()[0], "keep me")

    def test_mutated_new_code_blocks_switch(self):
        (self.trial.root / "versions" / "new" / "agent.py").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.trial.switch()
        self.assertEqual(self.trial.current(), "old")
        self.assertFalse((self.trial.root / "transaction.json").exists())
        self.assert_data_unchanged()

    def test_mutated_new_code_after_interruption_does_not_block_old_recovery(self):
        with self.assertRaises(SimulatedInterruption):
            self.trial.switch(fail_at="after_pointer")
        (self.trial.root / "versions" / "new" / "agent.py").write_bytes(b"corrupted")
        self.assertEqual(self.trial.recover(), "old")
        self.assert_data_unchanged()

    def test_invalid_journal_does_not_overwrite_pointer(self):
        with self.assertRaises(SimulatedInterruption):
            self.trial.switch(fail_at="after_pointer")
        (self.trial.root / "transaction.json").write_text('{"phase":"bad"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid journal"):
            self.trial.recover()
        self.assertEqual(self.trial.current(), "new")
        self.assert_data_unchanged()

    def test_repeated_switch_with_unfinished_journal_fails_closed(self):
        with self.assertRaises(SimulatedInterruption):
            self.trial.switch(fail_at="after_prepare")
        with self.assertRaisesRegex(ValueError, "pending journal"):
            self.trial.switch()
        self.assertEqual(self.trial.recover(), "old")
        self.assert_data_unchanged()

    def test_unexpected_code_file_rejected(self):
        (self.trial.root / "versions" / "new" / "cmd.bat").write_text("echo unsafe", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "added or missing"):
            self.trial.switch()
        self.assertEqual(self.trial.current(), "old")

    def test_new_version_symlink_rejected(self):
        path = self.trial.root / "versions" / "new" / "agent.py"
        path.unlink()
        try:
            path.symlink_to(self.trial.root / "versions" / "old" / "agent.py")
        except OSError:
            self.skipTest("symlinks require privileges on this Windows runner")
        with self.assertRaisesRegex(ValueError, "link"):
            self.trial.switch()
        self.assertEqual(self.trial.current(), "old")

    def test_bad_generation_and_reused_trial_are_rejected(self):
        self.trial.switch()
        with self.assertRaisesRegex(ValueError, "old generation"):
            self.trial.switch()
        self.assert_data_unchanged()

    def test_recovery_after_simulated_verified_commit_retains_new(self):
        with self.assertRaises(SimulatedInterruption):
            self.trial.switch(fail_at="after_pointer")
        self.trial._atomic_json("transaction.json", {"before": "old", "after": "new", "phase": "verified"})
        self.assertEqual(self.trial.recover(), "new")
        self.assert_data_unchanged()


if __name__ == "__main__":
    unittest.main()