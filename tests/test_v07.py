"""Regression coverage for persistent repair experiments (no external AI)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agent

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patches=[patch.object(agent,'ROOT',self.root),patch.object(agent,'WORKSPACE',self.root/'workspace'),patch.object(agent,'DB',self.root/'state.sqlite3')]
        for p in self.patches:p.start()
        agent.ensure_workspace()
        self.job=agent.make_job('repair the code')
        self.folder=self.root/'workspace'/'jobs'/str(self.job)
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/'main.py').write_text('answer=1\n')
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def test_repair_success_and_persistence(self):
        with agent.connection() as db, agent.job_workspace(db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()):
            before=agent.workspace_fingerprint()
            agent.record(db,self.job,{'action':'run_tests','path':'','content':'','reason':''},'ERROR: tests failed: assertion wrong')
            (self.folder/'main.py').write_text('answer=2\n')
            after=agent.workspace_fingerprint()
            agent.register_repair(db,self.job,{'path':'main.py','reason':'value should be 2'},before,after)
            self.assertEqual(agent.repair_context(db,self.job)[0]['status'],'pending')
            agent.resolve_repairs(db,self.job,'TEST PASS\nRan 1 test',after)
        with agent.connection() as db:
            history=agent.repair_context(db,self.job)
            self.assertEqual(history[0]['status'],'success')
            self.assertEqual(history[0]['hypothesis'],'value should be 2')
    def test_repeated_failure_is_not_success(self):
        with agent.connection() as db, agent.job_workspace(db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()):
            before=agent.workspace_fingerprint()
            fail='ERROR: tests failed: no expected item'
            agent.record(db,self.job,{'action':'run_tests','path':'','content':'','reason':''},fail)
            (self.folder/'main.py').write_text('answer=3\n')
            after=agent.workspace_fingerprint()
            agent.register_repair(db,self.job,{'path':'main.py','reason':'adjust value'},before,after)
            agent.resolve_repairs(db,self.job,fail,after)
            self.assertEqual(agent.repair_context(db,self.job)[0]['status'],'repeated_failure')
    def test_no_change_does_not_create_experiment(self):
        with agent.connection() as db, agent.job_workspace(db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()):
            fp=agent.workspace_fingerprint()
            agent.record(db,self.job,{'action':'run_tests','path':'','content':'','reason':''},'ERROR: tests failed')
            agent.register_repair(db,self.job,{'path':'main.py','reason':'noop'},fp,fp)
            self.assertEqual(agent.repair_context(db,self.job),[])
    def test_unrelated_test_result_does_not_create_experiment(self):
        with agent.connection() as db, agent.job_workspace(db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()):
            before=agent.workspace_fingerprint()
            (self.folder/'main.py').write_text('answer=4\n')
            agent.register_repair(db,self.job,{'path':'main.py','reason':'new feature'},before,agent.workspace_fingerprint())
            self.assertEqual(agent.repair_context(db,self.job),[])
    def test_signatures_ignore_temp_path(self):
        a='ERROR: File "/tmp/a/test.py", line 20\nAssertionError: wrong'
        b='ERROR: File "C:/Temp/b/test.py", line 26\nAssertionError: wrong'
        self.assertEqual(agent.failure_signature(a), agent.failure_signature(b))
    def test_repairs_command(self):
        with patch('builtins.print') as out:
            agent.show_repairs(self.job)
        out.assert_called_once()
