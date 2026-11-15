import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import agent


class Version14Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = agent.ROOT, agent.WORKSPACE, agent.DB
        agent.ROOT = Path(self.tmp.name)
        agent.WORKSPACE = agent.ROOT / "workspace"
        agent.DB = agent.ROOT / "state.sqlite3"
        agent.ensure_workspace()
        self.job = agent.make_job("Write a report")

    def tearDown(self):
        agent.ROOT, agent.WORKSPACE, agent.DB = self.previous
        self.tmp.cleanup()

    def test_acceptance_requires_file_and_exact_text(self):
        agent.set_criteria(self.job, ["report.md"], ["report.md::Summary"])
        with agent.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (self.job,)).fetchone()
            with agent.job_workspace(row):
                ok, _ = agent.acceptance_check(db, self.job)
                self.assertFalse(ok)
                (agent.WORKSPACE / "report.md").write_text("Introduction", encoding="utf-8")
                ok, _ = agent.acceptance_check(db, self.job)
                self.assertFalse(ok)
                (agent.WORKSPACE / "report.md").write_text("Summary", encoding="utf-8")
                ok, _ = agent.acceptance_check(db, self.job)
                self.assertTrue(ok)

    def test_acceptance_rejects_outside_path(self):
        with self.assertRaises(ValueError):
            agent.set_criteria(self.job, ["../secrets.txt"])

    def test_completion_gate_runs_before_model_review(self):
        plan = {"tasks": ["write report"], "deliverables": ["report.md"]}
        with agent.connection() as db:
            db.execute("UPDATE jobs SET plan=? WHERE id=?", (json.dumps(plan), self.job))
        agent.set_criteria(self.job, ["report.md"], ["report.md::Summary"])
        with patch.object(agent, "decide", return_value={
            "action": "finish", "path": "", "content": "", "reason": "done"
        }), patch.object(agent, "review", side_effect=AssertionError("should not review")):
            agent.run(self.job, "unused", budget=1)
        with agent.connection() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (self.job,)).fetchone()
            events = list(db.execute("SELECT result FROM events WHERE job_id=?", (self.job,)))
        self.assertNotEqual(row["status"], "done")
        self.assertTrue(any("REVIEW FAILED" in x["result"] for x in events))

    def test_stall_recovery_is_bounded_and_persistent(self):
        plan = {"tasks": ["a"], "deliverables": ["out.md"]}
        with patch.object(agent, "revise_plan", return_value=plan) as replanner:
            with agent.connection() as db:
                for _ in range(agent.MAX_STALL_RECOVERIES):
                    self.assertEqual(agent.recover_stall(db, self.job, "goal", plan, "model", "repeat"), plan)
                self.assertIsNone(agent.recover_stall(db, self.job, "goal", plan, "model", "repeat"))
                count = db.execute("SELECT stall_recoveries FROM job_controls WHERE job_id=?", (self.job,)).fetchone()[0]
        self.assertEqual(count, agent.MAX_STALL_RECOVERIES)
        self.assertEqual(replanner.call_count, agent.MAX_STALL_RECOVERIES)

    def test_retry_backoff_survives_reopening_database(self):
        with agent.connection() as db:
            agent.note_run_failure(db, self.job)
        with agent.connection() as db:
            row = db.execute("SELECT failures,retry_after FROM job_controls WHERE job_id=?", (self.job,)).fetchone()
            self.assertEqual(row["failures"], 1)
            self.assertGreater(datetime.fromisoformat(row["retry_after"]), datetime.now(timezone.utc))
            agent.clear_run_failure(db, self.job)
        with agent.connection() as db:
            row = db.execute("SELECT failures,retry_after FROM job_controls WHERE job_id=?", (self.job,)).fetchone()
            self.assertEqual((row["failures"],row["retry_after"]), (0, ""))

    def test_tick_skips_job_during_cooldown(self):
        with agent.connection() as db:
            agent.note_run_failure(db, self.job)
        with patch.object(agent, "run", side_effect=AssertionError("must not run")):
            agent.tick("unused",steps=1)


if __name__ == "__main__":
    unittest.main()
