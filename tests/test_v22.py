"""v2.2 virtual multi-file drafts must never write host files before approval."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent
import gui


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=agent.ROOT,agent.WORKSPACE,agent.DB
        agent.ROOT=Path(self.temp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()
        self.job=agent.make_job('two files',require_approval=True,draft_mode=True)
        self.folder=agent.WORKSPACE/'jobs'/str(self.job)

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.temp.cleanup()

    def action(self,db,a):
        return agent.draft_action(db,self.job,a)

    def test_draft_edits_read_back_without_host_writes(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                self.assertIn('DRAFT SAVED',self.action(db,{'action':'write_file','path':'one.md','content':'before','reason':'x'}))
                self.assertEqual(self.action(db,{'action':'read_file','path':'one.md','content':'','reason':''}),'before')
                self.assertIn('one.md',self.action(db,{'action':'list_files','path':'','content':'','reason':''}))
                self.assertIn('DRAFT SAVED',self.action(db,{'action':'replace_in_file','path':'one.md',
                    'content':json.dumps({'old':'before','new':'after'}),'reason':'replace'}))
                self.assertEqual(self.action(db,{'action':'read_file','path':'one.md','content':'','reason':''}),'after')
        self.assertFalse((self.folder/'one.md').exists())
        self.assertEqual(len(agent.pending_changes(self.job)),1)
        self.assertIn('+after',agent.change_preview(self.job,agent.pending_changes(self.job)[0]['id'])['diff'])

    def test_unchanged_draft_write_is_explicitly_idempotent(self):
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                first=self.action(db,{'action':'write_file','path':'one.md','content':'same','reason':'first'})
                repeated=self.action(db,{'action':'write_file','path':'one.md','content':'same','reason':'again'})
        self.assertIn('DRAFT SAVED',first)
        self.assertIn('DRAFT UNCHANGED',repeated)
        self.assertEqual(len(agent.pending_changes(self.job)),1)
        self.assertFalse((self.folder/'one.md').exists())

    def test_decision_prompt_explains_draft_completion(self):
        captured=[]
        def fake_ollama(messages,*unused):
            captured.extend(messages)
            return {'action':'finish','path':'','content':'','reason':'done'}
        with patch.object(agent,'ollama',side_effect=fake_ollama):
            agent.decide('goal',{'tasks':['write'],'deliverables':['one.md']},[],'dummy',draft=True)
        self.assertIn('DRAFT SAVED',captured[-1]['content'])
        self.assertIn('必ず finish',captured[-1]['content'])

    def test_real_agent_iterates_then_stops_for_batch_review(self):
        plan={'tasks':['write two files'],'deliverables':['one.md','two.md']}
        actions=iter([
            {'action':'write_file','path':'one.md','content':'one','reason':'a'},
            {'action':'write_file','path':'two.md','content':'two','reason':'b'},
            {'action':'finish','path':'','content':'','reason':'done'},
        ])
        with patch.object(agent,'make_plan',return_value=plan), \
             patch.object(agent,'decide',side_effect=lambda *a,**k:next(actions)):
            agent.run(self.job,'unused',budget=3)
        self.assertFalse((self.folder/'one.md').exists())
        self.assertFalse((self.folder/'two.md').exists())
        pending=agent.pending_changes(self.job)
        self.assertEqual(len(pending),2)
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(self.job,)).fetchone()['status'],'awaiting_approval')
        self.assertIn('Approved 2',agent.approve_batch(self.job,[p['id'] for p in pending]))
        self.assertEqual((self.folder/'one.md').read_text(),'one')
        self.assertEqual((self.folder/'two.md').read_text(),'two')

    def test_budget_resume_keeps_virtual_drafts(self):
        plan={'tasks':['write two files'],'deliverables':['one.md','two.md']}
        with patch.object(agent,'make_plan',return_value=plan), \
             patch.object(agent,'decide',return_value={'action':'write_file','path':'one.md','content':'one','reason':'a'}):
            agent.run(self.job,'unused',budget=1)
        self.assertFalse((self.folder/'one.md').exists())
        with patch.object(agent,'decide',side_effect=[
             {'action':'write_file','path':'two.md','content':'two','reason':'b'},
             {'action':'finish','path':'','content':'','reason':'done'}]):
            agent.run(self.job,'unused',budget=2)
        self.assertEqual(len(agent.pending_changes(self.job)),2)
        self.assertFalse((self.folder/'two.md').exists())

    def test_draft_python_syntax_checks_overlay(self):
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                self.action(db,{'action':'write_file','path':'x.py','content':'x = 42','reason':'a'})
                result=self.action(db,{'action':'check_python','path':'x.py','content':'','reason':''})
                self.assertTrue(result.startswith('CHECK PASS'))
        self.assertFalse((self.folder/'x.py').exists())

    def test_draft_tests_use_docker_runner_only(self):
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                self.action(db,{'action':'write_file','path':'tests/test_one.py','content':'import unittest','reason':'a'})
                with patch('sandbox_runner.run_tests',return_value='TEST PASS [sandbox]') as tested:
                    output=agent.draft_action(db,self.job,{'action':'run_tests','path':'','content':'','reason':''},allow_tests=True)
                self.assertIn('TEST PASS',output)
                tested.assert_called_once()
        self.assertFalse((self.folder/'tests'/'test_one.py').exists())

    def test_draft_uses_approval_and_is_default_for_cli(self):
        self.assertTrue(callable(gui.DesktopApp.enable_virtual_draft))
        with agent.connection() as db:
            self.assertTrue(agent.draft_enabled(db,self.job))
        other=agent.make_job('legacy',require_approval=True)
        with agent.connection() as db:
            self.assertFalse(agent.draft_enabled(db,other))
        agent.enable_draft(other)
        with agent.connection() as db:
            self.assertTrue(agent.draft_enabled(db,other))


if __name__=='__main__':
    unittest.main()
