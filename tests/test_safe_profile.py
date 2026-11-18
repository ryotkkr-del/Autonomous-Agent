"""The safe/free profile must refuse every optional external capability."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent


class SafeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=agent.ROOT,agent.WORKSPACE,agent.DB
        agent.ROOT=Path(self.temp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.temp.cleanup()

    def test_safe_new_creates_protected_virtual_draft(self):
        job=agent.safe_new_job('write a note')
        with agent.connection() as db:
            row=db.execute('SELECT approval_required,draft_mode FROM job_controls WHERE job_id=?',(job,)).fetchone()
        self.assertEqual(tuple(row),(1,1))

    def test_safe_run_only_dispatches_least_privilege_job(self):
        job=agent.safe_new_job('write a note')
        with patch.object(agent,'run') as runner:
            agent.safe_run(job,'local-model',steps=2)
        runner.assert_called_once_with(job,'local-model',2,codex=False)

    def test_safe_run_rejects_unprotected_or_expanded_permissions(self):
        unprotected=agent.make_job('legacy')
        with self.assertRaisesRegex(ValueError,'protected virtual-draft'):
            agent.safe_run(unprotected)
        job=agent.safe_new_job('write a note')
        with agent.connection() as db:
            db.execute('UPDATE jobs SET allow_tests=1 WHERE id=?',(job,))
        with self.assertRaisesRegex(ValueError,'remain disabled'):
            agent.safe_run(job)

    def test_safe_run_has_small_explicit_step_cap(self):
        job=agent.safe_new_job('write a note')
        with self.assertRaisesRegex(ValueError,'1-4'):
            agent.safe_run(job,steps=agent.SAFE_FREE_MAX_STEPS+1)


if __name__=='__main__':
    unittest.main()
