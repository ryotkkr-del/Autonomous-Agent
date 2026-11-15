"""GUI/CLI parity and safety-report regression tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent
import gui


class InterfaceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.previous=(agent.ROOT,agent.WORKSPACE,agent.DB)
        agent.ROOT=Path(self.tmp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()
        self.job=agent.make_job('create lesson')

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.previous
        self.tmp.cleanup()

    def test_default_permissions_are_disabled(self):
        s=agent.safety_summary(self.job)
        self.assertFalse(s['permissions']['python_tests'])
        self.assertFalse(s['permissions']['web_search'])
        self.assertFalse(s['permissions']['local_git_checkpoint'])
        self.assertEqual(s['permissions']['approved_web_pages'],0)
        self.assertTrue(any('NOT an OS sandbox' in x for x in s['risks']))

    def test_safety_summary_reflects_permissions(self):
        agent.set_search(self.job,True)
        agent.set_tests(self.job,True)
        with agent.connection() as db:
            db.execute('UPDATE jobs SET allow_git=1 WHERE id=?',(self.job,))
        s=agent.safety_summary(self.job)
        self.assertTrue(all(s['permissions'][name] for name in
                            ('python_tests','web_search','local_git_checkpoint')))

    def test_criteria_read_is_not_destructive(self):
        agent.set_criteria(self.job,['lesson.md'],['lesson.md::Summary'])
        self.assertEqual(agent.criteria_summary(self.job)['checks'],
                         [{'type':'file','path':'lesson.md'},
                          {'type':'contains','path':'lesson.md','text':'Summary'}])
        self.assertEqual(len(agent.criteria_summary(self.job)['checks']),2)

    def test_missing_job_rejected(self):
        with self.assertRaises(ValueError):
            agent.criteria_summary(999)
        with self.assertRaises(ValueError):
            agent.safety_summary(999)

    def test_gui_has_matching_commands_without_starting_them(self):
        self.assertTrue(callable(gui.AgentGUI.set_success_criteria))
        self.assertTrue(callable(gui.AgentGUI.view_success_criteria))
        self.assertTrue(callable(gui.AgentGUI.view_safety))


if __name__=='__main__':
    unittest.main()
