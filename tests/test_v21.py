"""Regression tests for v2.1 snapshots, rollback and batch review."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

class ReviewSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=agent.ROOT,agent.WORKSPACE,agent.DB
        agent.ROOT=Path(self.temp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()
        self.job=agent.make_job('safe edits',require_approval=True)
        self.folder=agent.WORKSPACE/'jobs'/str(self.job)
        self.folder.mkdir(parents=True,exist_ok=True)

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.temp.cleanup()

    def stage(self,name,content):
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                number=agent.stage_change(db,self.job,{
                    'action':'write_file','path':name,
                    'content':content,'reason':'test'})
            agent.update_status(db,self.job,'awaiting_approval','pending')
        return number

    def test_gui_review_and_rollback_methods_exist(self):
        import gui
        for method in ('_show_batch','review_rollback','_choose_rollback'):
            self.assertTrue(callable(getattr(gui.DesktopApp,method)))

    def test_batch_preview_includes_every_file(self):
        a=self.stage('one.md','one')
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                b=agent.stage_change(db,self.job,{
                    'action':'write_file','path':'two.md','content':'two','reason':'test'})
        preview=agent.batch_preview(self.job,[a,b])
        self.assertEqual(len(preview['changes']),2)
        self.assertFalse(preview['truncated'])
        self.assertIn('+one',preview['changes'][0]['diff'])
        self.assertIn('+two',preview['changes'][1]['diff'])

    def test_new_file_rollback_removes_file(self):
        cid=self.stage('new.md','hello')
        agent.resolve_change(self.job,cid,approve=True)
        snapshot=agent.list_snapshots(self.job)[0]['id']
        self.assertEqual((self.folder/'new.md').read_text(),'hello')
        agent.rollback_snapshot(self.job,snapshot)
        self.assertFalse((self.folder/'new.md').exists())

    def test_existing_file_rollback_preserves_original_bytes(self):
        data=b'first\r\nsecond\r\n'
        (self.folder/'one.txt').write_bytes(data)
        cid=self.stage('one.txt','modified')
        agent.resolve_change(self.job,cid,approve=True)
        snapshot=agent.list_snapshots(self.job)[0]['id']
        agent.rollback_snapshot(self.job,snapshot)
        self.assertEqual((self.folder/'one.txt').read_bytes(),data)

    def test_rollback_fails_if_file_changed_again(self):
        cid=self.stage('new.md','hello')
        agent.resolve_change(self.job,cid,approve=True)
        number=agent.list_snapshots(self.job)[0]['id']
        (self.folder/'new.md').write_text('edited by user')
        with self.assertRaisesRegex(ValueError,'changed after approval'):
            agent.rollback_snapshot(self.job,number)
        self.assertEqual((self.folder/'new.md').read_text(),'edited by user')

    def test_secret_candidate_rejected_without_writing(self):
        self.assertTrue(agent.scan_proposed_secrets('password = "this_is_a_long_password"'))
        self.assertTrue(agent.scan_proposed_secrets('-----BEGIN PRIVATE KEY-----'))
        self.assertFalse(agent.scan_proposed_secrets('# Guide to API key security'))
        cid=self.stage('config.py','password = "this_is_a_long_password"')
        with self.assertRaisesRegex(ValueError,'secret'):
            agent.resolve_change(self.job,cid,approve=True)
        self.assertFalse((self.folder/'config.py').exists())

    def test_batch_approval_two_distinct_staged_files(self):
        # Multiple proposals are staged through the API for deterministic
        # evaluation. The interactive agent still pauses at each edit.
        a=self.stage('one.md','one')
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                # Stage second proposal after first was resolved in v2.0
                # only; v2.1 permits multiple pending distinct paths.
                b=agent.stage_change(db,self.job,{
                    'action':'write_file','path':'two.md',
                    'content':'two','reason':'test'})
        result=agent.approve_batch(self.job,[a,b])
        self.assertIn('Approved 2',result)
        self.assertEqual((self.folder/'one.md').read_text(),'one')
        self.assertEqual((self.folder/'two.md').read_text(),'two')
        self.assertEqual(len(agent.list_snapshots(self.job)),2)

    def test_batch_stale_prevalidation_prevents_partial_writes(self):
        a=self.stage('one.md','one')
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                b=agent.stage_change(db,self.job,{
                    'action':'write_file','path':'two.md','content':'two','reason':'test'})
        (self.folder/'two.md').write_text('external')
        with self.assertRaisesRegex(ValueError,'file changed'):
            agent.approve_batch(self.job,[a,b])
        self.assertFalse((self.folder/'one.md').exists())

    def test_batch_compensates_ordinary_execution_error(self):
        a=self.stage('one.md','one')
        with agent.connection() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job,)).fetchone()
            with agent.job_workspace(job):
                b=agent.stage_change(db,self.job,{
                    'action':'write_file','path':'two.md','content':'two','reason':'test'})
        original=agent.execute
        calls=[0]
        def fail_on_second(*args,**kwargs):
            calls[0]+=1
            if calls[0]==2: raise OSError('simulated second write failure')
            return original(*args,**kwargs)
        with patch.object(agent,'execute',side_effect=fail_on_second):
            with self.assertRaisesRegex(OSError,'simulated'):
                agent.approve_batch(self.job,[a,b])
        self.assertFalse((self.folder/'one.md').exists())
        self.assertFalse((self.folder/'two.md').exists())
        self.assertEqual(len(agent.pending_changes(self.job)),2)

if __name__=='__main__':
    unittest.main()
