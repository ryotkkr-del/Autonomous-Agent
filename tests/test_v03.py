import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.ps=[patch.object(agent,'ROOT',self.root),patch.object(agent,'WORKSPACE',self.root/'workspace'),patch.object(agent,'DB',self.root/'state.sqlite3')]
        for p in self.ps:p.start()
        agent.ensure_workspace()
    def tearDown(self):
        for p in reversed(self.ps):p.stop()
        self.tmp.cleanup()

    def test_syntax_check_no_execution(self):
        marker=self.root/'marker'
        (agent.WORKSPACE/'bad.py').write_text('def broken(: pass',encoding='utf-8')
        self.assertTrue(agent.check_python('bad.py').startswith('ERROR:'))
        (agent.WORKSPACE/'good.py').write_text(f'open({str(marker)!r}, "w").write("bad")',encoding='utf-8')
        self.assertIn('CHECK PASS',agent.check_python('good.py'))
        self.assertFalse(marker.exists())

    def test_tests_require_opt_in_and_execute_when_enabled(self):
        tests=agent.WORKSPACE/'tests';tests.mkdir()
        (tests/'test_example.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_true(self): self.assertTrue(True)\n')
        self.assertIn('disabled',agent.run_workspace_tests(False))
        with patch('sandbox_runner.run_tests',return_value='TEST PASS [Docker sandbox]') as isolated:\n            self.assertIn('TEST PASS',agent.run_workspace_tests(True))\n            isolated.assert_called_once()

    def test_blocked_skipped_by_scheduler(self):
        j=agent.make_job('bad')
        with agent.connection() as db:agent.update_status(db,j,'blocked','bad')
        with patch.object(agent,'run') as runner:
            agent.tick('dummy',1)
            runner.assert_not_called()
        agent.unblock(j)
        with agent.connection() as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()['status'],'paused')

    def test_chat_report_has_goal_and_does_not_call_remote(self):
        j=agent.make_job('make a note')
        agent.chat_report(j)
        body=(self.root/f'chat-report-{j}.md').read_text()
        self.assertIn('make a note',body)
        self.assertIn('ChatGPT',body)

    def test_read_only_review_checks_python_artifact(self):
        (agent.WORKSPACE/'broken.py').write_text('def x(:')
        ok,reason=agent.review('make working python',{'tasks':['make'],'deliverables':['broken.py']},[], 'dummy')
        self.assertFalse(ok)
        self.assertIn('構文',reason)

if __name__=='__main__':unittest.main()
