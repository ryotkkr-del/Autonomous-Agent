import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

class Version12Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.old=(agent.ROOT,agent.WORKSPACE,agent.DB)
        agent.ROOT=self.root
        agent.WORKSPACE=self.root/'workspace'
        agent.DB=self.root/'state.sqlite3'
        agent.ensure_workspace()

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.tmp.cleanup()

    def test_search_disabled_without_network(self):
        with patch.object(agent,'validate_public_https',side_effect=AssertionError('network must not be touched')):
            self.assertIn('disabled',agent.web_search('python docs'))

    def test_search_query_length(self):
        self.assertIn('invalid',agent.web_search('x'*181,True))

    def test_search_rss_bounded_and_untrusted(self):
        payload=b'<rss><channel><item><title>Docs</title><link>https://example.org/doc</link><description>Useful reference</description></item></channel></rss>'
        with patch.object(agent,'_fetch_public_https',return_value=(200,{},payload)) as fetch:
            result=agent.web_search('learning python',True)
            self.assertIn('https://www.bing.com/search',fetch.call_args.args[0])
        self.assertIn('UNTRUSTED',result)
        self.assertIn('https://example.org/doc',result)

    def test_search_code_finds_line(self):
        (agent.WORKSPACE/'example.py').write_text('def foo():\n    return 42\n')
        self.assertIn('example.py:1:',agent.search_code('def foo'))

    def test_replace_unique_only_and_backup(self):
        target=agent.WORKSPACE/'example.py'
        target.write_text('answer = 1\n')
        action={'action':'replace_in_file','path':'example.py','content':json.dumps({'old':'answer = 1','new':'answer = 2'}),'reason':'fix'}
        self.assertIn('WROTE',agent.execute(action))
        self.assertEqual(target.read_text(),'answer = 2\n')
        self.assertTrue((agent.WORKSPACE/'example.py.agent-backup').exists())
        self.assertIn('ERROR',agent.execute(action))

    def test_replacement_rejects_ambiguous(self):
        (agent.WORKSPACE/'x.py').write_text('a\na\n')
        action={'action':'replace_in_file','path':'x.py','content':json.dumps({'old':'a','new':'b'}),'reason':'fix'}
        self.assertIn('exactly once',agent.execute(action))

    def test_search_permission_persists(self):
        job_id=agent.make_job('hello')
        agent.set_search(job_id,True)
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT allow_search FROM agent_preferences WHERE job_id=?',(job_id,)).fetchone()['allow_search'],1)
        agent.set_search(job_id,False)

    def test_revision_keeps_previous_deliverables_and_task_progress(self):
        jid=agent.make_job('create code')
        old={'tasks':['write code'],'deliverables':['main.py']}
        with agent.connection() as db:
            agent.ensure_plan_tasks(db,jid,old)
            db.execute('UPDATE plan_tasks SET state=? WHERE job_id=? AND idx=1',('done',jid))
            with patch.object(agent,'ollama',return_value={'tasks':['test code','write code'],'deliverables':['test_main.py']}):
                revised=agent.revise_plan(db,jid,'create code',old,'fake','new test failure')
            self.assertEqual(revised['deliverables'],['main.py','test_main.py'])
            self.assertEqual(db.execute('SELECT state FROM plan_tasks WHERE job_id=? AND idx=1',(jid,)).fetchone()['state'],'done')
            self.assertEqual(db.execute('SELECT count(*) FROM plan_revisions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM plan_tasks WHERE job_id=?',(jid,)).fetchone()[0],2)

    def test_revision_rejects_unsafe_output(self):
        jid=agent.make_job('make file')
        old={'tasks':['create'],'deliverables':['safe.txt']}
        with agent.connection() as db:
            with patch.object(agent,'ollama',return_value={'tasks':['revised'],'deliverables':['../bad.txt']}):
                with self.assertRaises(ValueError):agent.revise_plan(db,jid,'make file',old,'fake','test')
            self.assertEqual(db.execute('SELECT count(*) FROM plan_revisions').fetchone()[0],0)

if __name__=='__main__':unittest.main()
