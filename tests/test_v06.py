"""v0.6 deterministic completion tests; no external LLM or executable untrusted code."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class TestV06(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.p1=patch.object(agent,'ROOT',self.root)
        self.p2=patch.object(agent,'WORKSPACE',self.root/'workspace')
        self.p3=patch.object(agent,'DB',self.root/'state.sqlite3')
        for p in (self.p1,self.p2,self.p3):p.start()
        agent.ensure_workspace()
    def tearDown(self):
        for p in (self.p3,self.p2,self.p1):p.stop()
        self.temp.cleanup()

    def initialize(self, script, test_text=''):
        job_id=agent.make_job('build a tiny python module')
        with agent.connection() as db:
            db.execute('UPDATE jobs SET allow_tests=1 WHERE id=?',(job_id,))
        plan={'tasks':['write function and tests'],'deliverables':['main.py']}
        def fake_plan(*args):return plan
        return job_id,fake_plan

    def test_detect_test_files_and_zero_test(self):
        tests=agent.WORKSPACE/'tests'; tests.mkdir()
        (tests/'test_dummy.py').write_text('# no tests\n')
        self.assertTrue(agent.tests_exist())
        self.assertTrue(agent.run_workspace_tests(True).startswith('ERROR:'))

    def test_fingerprint_changes_when_source_changes(self):
        p=agent.WORKSPACE/'main.py'; p.write_text('x=1\n')
        before=agent.workspace_fingerprint()
        p.write_text('x=2\n')
        self.assertNotEqual(before,agent.workspace_fingerprint())

    def test_tests_run_automatically_when_model_requests_finish(self):
        job_id,plan=self.initialize('')
        def decision(*args,**kwargs):
            return {'action':'finish','path':'','content':'','reason':'done'}
        with agent.connection() as db:
            db.execute('UPDATE jobs SET plan=? WHERE id=?',(json.dumps(plan()),job_id))
        folder=agent.WORKSPACE/'jobs'/str(job_id)
        (folder/'tests').mkdir(parents=True)
        (folder/'main.py').write_text('answer=42\n')
        (folder/'tests'/'test_example.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertEqual(42,42)\n')
        with patch.object(agent,'decide',side_effect=decision), patch.object(agent,'review',return_value=(True,'verified')), patch.object(agent,'run_workspace_tests',return_value='TEST PASS [mocked Docker sandbox]\nRan 1 test in 0.01s'):
            agent.run(job_id,'test',budget=1)
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()['status'],'done')
            log=agent.history(db,job_id)
            self.assertTrue(any(e['action']=='auto_tests' and e['result'].startswith('TEST PASS') for e in log))

    def test_failed_tests_block_completion_and_remain_in_log(self):
        job_id,plan=self.initialize('')
        with agent.connection() as db:
            db.execute('UPDATE jobs SET plan=? WHERE id=?',(json.dumps(plan()),job_id))
        folder=agent.WORKSPACE/'jobs'/str(job_id)
        (folder/'tests').mkdir(parents=True)
        (folder/'main.py').write_text('answer=42\n')
        (folder/'tests'/'test_example.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_no(self): self.fail("intended failure")\n')
        with patch.object(agent,'decide',return_value={'action':'finish','path':'','content':'','reason':'done'}),patch.object(agent,'review',return_value=(True,'should not run')) as review, patch.object(agent,'run_workspace_tests',return_value='ERROR: sandbox test failed\nFAIL: intended failure'):
            agent.run(job_id,'test',budget=1)
        review.assert_not_called()
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()['status'],'paused')
            self.assertIn('ERROR:',agent.history(db,job_id)[-2]['result'])

    def test_no_test_permission_means_no_auto_execution(self):
        job_id,plan=self.initialize('')
        with agent.connection() as db:
            db.execute('UPDATE jobs SET plan=?,allow_tests=0 WHERE id=?',(json.dumps(plan()),job_id))
        folder=agent.WORKSPACE/'jobs'/str(job_id)
        (folder/'tests').mkdir(parents=True)
        (folder/'main.py').write_text('answer=42\n')
        (folder/'tests'/'test_example.py').write_text('raise RuntimeError("should not execute")\n')
        with patch.object(agent,'decide',return_value={'action':'finish','path':'','content':'','reason':'done'}), patch.object(agent,'review',return_value=(True,'verified')),patch.object(agent,'run_workspace_tests') as runner:
            agent.run(job_id,'test',budget=1)
        runner.assert_not_called()
