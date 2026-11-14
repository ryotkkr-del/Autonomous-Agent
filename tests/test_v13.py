import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

class Version13Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.previous=agent.ROOT,agent.WORKSPACE,agent.DB
        agent.ROOT=Path(self.tmp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.previous
        self.tmp.cleanup()

    def test_replace_in_file_invalidates_previous_successful_tests(self):
        (agent.WORKSPACE/'app.py').write_text('x = 2\n')
        h=[{'action':'auto_tests','result':'TEST PASS'},
           {'action':'replace_in_file','result':'WROTE app.py'}]
        with patch.object(agent,'ollama',side_effect=AssertionError('must not approve')):
            ok,reason=agent.review('code',{'tasks':['build'],'deliverables':['app.py']},h,'unused')
        self.assertFalse(ok)
        self.assertIn('再テスト',reason)

    def test_python_job_with_test_permission_cannot_finish_without_tests(self):
        job_id=agent.make_job('build Python file with tests')
        with agent.connection() as db:
            db.execute('UPDATE jobs SET allow_tests=1,plan=? WHERE id=?',
                (json.dumps({'tasks':['build'], 'deliverables':['app.py']}),job_id))
        with patch.object(agent,'decide',return_value={'action':'finish','path':'','content':'','reason':'done'}), \
             patch.object(agent,'review',side_effect=AssertionError('review must not run')):
            agent.run(job_id,'unused',budget=1)
        with agent.connection() as db:
            row=db.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()
            actions=[dict(r) for r in db.execute('SELECT action,result FROM events WHERE job_id=?',(job_id,))]
        self.assertNotEqual(row['status'],'done')
        self.assertTrue(any('テストがありません' in a['result'] for a in actions))

if __name__=='__main__': unittest.main()
