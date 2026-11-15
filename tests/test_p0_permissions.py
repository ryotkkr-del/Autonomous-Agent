"""P0-3: permissions and STOP must be rechecked after slow model inference.

No Ollama, network, Git or Docker activity is required by these tests.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

def action(name,path=''):
    return {'action':name,'path':path,'content':'','reason':'permission-boundary test'}

class PermissionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=agent.ROOT,agent.WORKSPACE,agent.DB
        agent.ROOT=Path(self.temp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()
        self.plan={'tasks':['check permissions'],'deliverables':['dummy.txt']}

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.temp.cleanup()

    def last_result(self,jobid):
        with agent.connection() as db:
            row=db.execute('SELECT result FROM events WHERE job_id=? ORDER BY id DESC LIMIT 1',
                           (jobid,)).fetchone()
            return row['result'] if row else ''

    def run_one(self,jobid,decider):
        with patch.object(agent,'make_plan',return_value=self.plan), \
             patch.object(agent,'decide',side_effect=decider):
            agent.run(jobid,'fake',budget=1)

    def test_search_revocation_while_model_is_deciding(self):
        jobid=agent.make_job('search',require_approval=True,draft_mode=True)
        agent.set_search(jobid,True)
        def decide_and_revoke(*unused,**kwargs):
            agent.set_search(jobid,False)
            return action('web_search','an interesting query')
        with patch.object(agent,'_fetch_public_https',side_effect=AssertionError('network attempted')):
            self.run_one(jobid,decide_and_revoke)
        self.assertIn('disabled',self.last_result(jobid).lower())

    def test_exact_url_revocation_while_model_is_deciding(self):
        jobid=agent.make_job('lookup',require_approval=True,draft_mode=True)
        url='https://example.org/doc'
        with patch.object(agent,'validate_public_https',return_value=url):
            agent.approve_url(jobid,url)
        def decide_and_revoke(*unused,**kwargs):
            agent.revoke_url(jobid,url)
            return action('read_url',url)
        with patch.object(agent,'_fetch_public_https',side_effect=AssertionError('network attempted')):
            self.run_one(jobid,decide_and_revoke)
        self.assertIn('not approved',self.last_result(jobid).lower())

    def test_test_permission_revocation_prevents_docker_execution(self):
        jobid=agent.make_job('tests',require_approval=True,draft_mode=True)
        agent.set_tests(jobid,True)
        def decide_and_revoke(*unused,**kwargs):
            agent.set_tests(jobid,False)
            return action('run_tests')
        with patch('sandbox_runner.run_tests',side_effect=AssertionError('Docker executed')):
            self.run_one(jobid,decide_and_revoke)
        self.assertIn('disabled',self.last_result(jobid).lower())

    def test_git_permission_revocation_before_command(self):
        jobid=agent.make_job('old compatible task')
        agent.set_git(jobid,True)
        def decide_and_revoke(*unused,**kwargs):
            agent.set_git(jobid,False)
            return action('git_status')
        with patch.object(agent,'git_status',side_effect=AssertionError('Git executed')):
            self.run_one(jobid,decide_and_revoke)
        self.assertIn('disabled',self.last_result(jobid).lower())

    def test_stop_file_created_during_inference_prevents_action(self):
        jobid=agent.make_job('stop',require_approval=True,draft_mode=True)
        def decide_and_stop(*unused,**kwargs):
            (agent.ROOT/'STOP').write_text('stop')
            return {'action':'write_file','path':'new.txt','content':'write','reason':'new'}
        with patch.object(agent,'draft_action',side_effect=AssertionError('action executed')):
            self.run_one(jobid,decide_and_stop)
        self.assertFalse((agent.WORKSPACE/'jobs'/str(jobid)/'new.txt').exists())
        self.assertEqual(agent.pending_changes(jobid),[])
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(jobid,)).fetchone()['status'],'paused')

    def test_external_pause_during_inference_prevents_action(self):
        jobid=agent.make_job('pause',require_approval=True,draft_mode=True)
        def decide_and_pause(*unused,**kwargs):
            with agent.connection() as db:
                agent.update_status(db,jobid,'paused','user requested pause')
            return {'action':'write_file','path':'new.txt','content':'write','reason':'new'}
        with patch.object(agent,'draft_action',side_effect=AssertionError('action executed')):
            self.run_one(jobid,decide_and_pause)
        self.assertEqual(agent.pending_changes(jobid),[])
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(jobid,)).fetchone()['status'],'paused')

    def test_permissions_fresh_connection_reads_committed_changes(self):
        jobid=agent.make_job('inspect',require_approval=True)
        agent.set_search(jobid,True)
        snapshot=agent.current_run_permissions(jobid)
        self.assertTrue(snapshot['allow_search'])
        agent.set_search(jobid,False)
        self.assertFalse(agent.current_run_permissions(jobid)['allow_search'])
        self.assertFalse(agent.current_run_permissions(jobid)['allow_git'])
