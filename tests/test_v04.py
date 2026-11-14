import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

class V04Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.ps=[patch.object(agent,'ROOT',self.root),patch.object(agent,'WORKSPACE',self.root/'workspace'),patch.object(agent,'DB',self.root/'state.sqlite3')]
        for p in self.ps:p.start()
        agent.ensure_workspace()
    def tearDown(self):
        for p in reversed(self.ps):p.stop()
        self.tmp.cleanup()

    def test_new_jobs_isolated(self):
        j1=agent.make_job('a'); j2=agent.make_job('b')
        with agent.connection() as db:
            row1=db.execute('SELECT * FROM jobs WHERE id=?',(j1,)).fetchone()
            row2=db.execute('SELECT * FROM jobs WHERE id=?',(j2,)).fetchone()
            with agent.job_workspace(row1):
                agent.execute({'action':'write_file','path':'x.txt','content':'private'})
            with agent.job_workspace(row2):
                self.assertEqual(agent.files_list(),[])
        self.assertTrue((agent.WORKSPACE/f'jobs/{j1}/x.txt').exists())
        self.assertFalse((agent.WORKSPACE/f'jobs/{j2}/x.txt').exists())

    def test_legacy_job_retains_shared_workspace(self):
        with agent.connection() as db:
            db.execute("INSERT INTO jobs(goal,status,created,updated) VALUES('legacy','paused','x','x')")
            legacy=db.execute('SELECT * FROM jobs').fetchone()
            with agent.job_workspace(legacy):
                self.assertEqual(agent.WORKSPACE,self.root/'workspace')

    def test_review_checks_real_content(self):
        (agent.WORKSPACE/'note.txt').write_text('Verified content',encoding='utf-8')
        with patch.object(agent,'ollama',return_value={'complete':True,'reason':'good','missing':[]}) as call:
            self.assertTrue(agent.review('note',{'tasks':['write'],'deliverables':['note.txt']},[],'dummy')[0])
            self.assertIn('Verified content',str(call.call_args))

    def test_zero_length_cannot_finish(self):
        (agent.WORKSPACE/'empty.txt').touch()
        with patch.object(agent,'ollama') as call:
            ok,_=agent.review('note',{'tasks':['write'],'deliverables':['empty.txt']},[],'dummy')
            self.assertFalse(ok);call.assert_not_called()

    def test_failed_tests_block_finish(self):
        (agent.WORKSPACE/'note.txt').write_text('content')
        plan={'tasks':['create'],'deliverables':['note.txt']}
        hist=[{'action':'run_tests','result':'ERROR: tests failed (exit=1)'}]
        with patch.object(agent,'ollama') as call:
            self.assertFalse(agent.review('note',plan,hist,'dummy')[0]);call.assert_not_called()

    def test_modified_after_test_must_retest(self):
        (agent.WORKSPACE/'note.txt').write_text('content')
        plan={'tasks':['create'],'deliverables':['note.txt']}
        hist=[{'action':'run_tests','result':'TEST PASS'},{'action':'write_file','result':'WROTE note.txt'}]
        with patch.object(agent,'ollama') as call:
            self.assertFalse(agent.review('note',plan,hist,'dummy')[0]);call.assert_not_called()

    def test_workspace_symlink_forbidden(self):
        j=agent.make_job('x'); outside=self.root/'outside';outside.mkdir()
        jobs=agent.WORKSPACE/'jobs'
        try:jobs.symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError): self.skipTest('symlinks unavailable')
        with agent.connection() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(j,)).fetchone()
            with self.assertRaises(ValueError):
                with agent.job_workspace(row):pass

if __name__=='__main__':unittest.main()
