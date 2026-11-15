"""Approval boundaries: no AI-proposed host write before explicit human consent."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent
import gui

class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=agent.ROOT,agent.WORKSPACE,agent.DB
        agent.ROOT=Path(self.tmp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()
        self.job=agent.make_job('Create a lesson',require_approval=True)
        self.folder=agent.WORKSPACE/'jobs'/str(self.job)

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.tmp.cleanup()

    def make_pending(self,action=None):
        action=action or {'action':'write_file','path':'lesson.md','content':'new lesson\n','reason':'write'}
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                cid=agent.stage_change(db,self.job,action)
            agent.update_status(db,self.job,'awaiting_approval','review')
        return cid

    def test_pending_does_not_write_until_human_approval(self):
        cid=self.make_pending()
        self.assertFalse((self.folder/'lesson.md').exists())
        self.assertIn('new lesson',agent.change_preview(self.job,cid)['diff'])
        result=agent.resolve_change(self.job,cid,approve=True)
        self.assertIn('Approved',result)
        self.assertEqual((self.folder/'lesson.md').read_text(),'new lesson\n')

    def test_rejection_does_not_write(self):
        cid=self.make_pending()
        self.assertIn('Rejected',agent.resolve_change(self.job,cid,approve=False))
        self.assertFalse((self.folder/'lesson.md').exists())
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(self.job,)).fetchone()['status'],'paused')

    def test_stale_approval_fails_closed(self):
        cid=self.make_pending()
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/'lesson.md').write_text('changed externally')
        with self.assertRaisesRegex(ValueError,'modified since proposal'):
            agent.resolve_change(self.job,cid,approve=True)
        self.assertEqual((self.folder/'lesson.md').read_text(),'changed externally')

    def test_replace_staged_not_applied(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/'lesson.md').write_text('before')
        action={'action':'replace_in_file','path':'lesson.md',
                'content':json.dumps({'old':'before','new':'after'}),'reason':'replace'}
        cid=self.make_pending(action)
        self.assertEqual((self.folder/'lesson.md').read_text(),'before')
        self.assertIn('+after',agent.change_preview(self.job,cid)['diff'])
        agent.resolve_change(self.job,cid,approve=True)
        self.assertEqual((self.folder/'lesson.md').read_text(),'after')

    def test_run_stops_before_writing(self):
        plan={'tasks':['create'],'deliverables':['lesson.md']}
        action={'action':'write_file','path':'lesson.md','content':'hello','reason':'write'}
        with patch.object(agent,'make_plan',return_value=plan),patch.object(agent,'decide',return_value=action):
            agent.run(self.job,'unused',budget=2)
        self.assertFalse((self.folder/'lesson.md').exists())
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(self.job,)).fetchone()['status'],'awaiting_approval')
        self.assertEqual(len(agent.pending_changes(self.job)),1)

    def test_resume_stays_paused_before_review(self):
        cid=self.make_pending()
        with patch.object(agent,'decide',side_effect=AssertionError('must not decide')):
            agent.run(self.job,'unused',budget=2)
        self.assertFalse((self.folder/'lesson.md').exists())
        self.assertEqual(agent.pending_changes(self.job)[0]['id'],cid)

    def test_cannot_apply_without_awaiting_status(self):
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                cid=agent.stage_change(db,self.job,{'action':'write_file','path':'a.py','content':'x=1','reason':'a'})
        with self.assertRaisesRegex(ValueError,'not awaiting'):
            agent.resolve_change(self.job,cid,approve=True)
        self.assertFalse((self.folder/'a.py').exists())

    def test_legacy_job_explicit_protection(self):
        legacy=agent.make_job('Old')
        with agent.connection() as db:
            self.assertFalse(agent.approval_enabled(db,legacy))
        agent.protect_job(legacy)
        with agent.connection() as db:
            self.assertTrue(agent.approval_enabled(db,legacy))

    def test_gui_has_review_actions(self):
        self.assertTrue(callable(gui.DesktopApp.review_pending_change))
        self.assertTrue(callable(gui.DesktopApp._show_change))
        self.assertTrue(callable(gui.DesktopApp.protect_legacy_job))

if __name__=='__main__':
    unittest.main()
