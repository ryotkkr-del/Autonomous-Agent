import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent


class V08Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patchers=[patch.object(agent,'ROOT',self.root),patch.object(agent,'WORKSPACE',self.root/'workspace'),patch.object(agent,'DB',self.root/'state.sqlite3')]
        for patcher in self.patchers:patcher.start()
        agent.ensure_workspace()
        self.j=agent.make_job('make an app')
        self.plan={'tasks':['Investigate','Implement','Verify'],'deliverables':['app.py']}
        with agent.connection() as db: agent.ensure_plan_tasks(db,self.j,self.plan)

    def tearDown(self):
        for patcher in reversed(self.patchers):patcher.stop()
        self.temp.cleanup()

    def test_board_persists_and_is_prioritized(self):
        agent.update_task(self.j,2,priority=5,state='doing',note='focus')
        with agent.connection() as db:
            result=agent.task_board(db,self.j)
            self.assertEqual(result[0]['idx'],2)
            agent.ensure_plan_tasks(db,self.j,self.plan)
            self.assertEqual(agent.task_board(db,self.j)[0]['note'],'focus')

    def test_invalid_task_updates_rejected(self):
        with self.assertRaises(ValueError): agent.update_task(self.j,1,priority=9)
        with self.assertRaises(ValueError): agent.update_task(self.j,99,state='done')
        with self.assertRaises(ValueError): agent.update_task(self.j,1,state='deleted')

    def test_diagnosis_requires_failed_test(self):
        with agent.connection() as db:
            with self.assertRaisesRegex(ValueError,'no current failed test'):
                agent.diagnostic_proposals(db,self.j,'dummy')

    def test_diagnosis_saved_and_readonly(self):
        proposal={'hypotheses':[{'cause':'wrong input check','evidence':'AssertionError','safe_check':'Read function','priority':5}]}
        with agent.connection() as db:
            agent.record(db,self.j,{'action':'run_tests','path':'','content':'','reason':''},'ERROR: failed test AssertionError')
            with patch.object(agent,'ollama',return_value=proposal) as ollama:
                answer=agent.diagnostic_proposals(db,self.j,'dummy')
            self.assertEqual(answer,proposal['hypotheses'])
            self.assertEqual(db.execute('SELECT count(*) AS n FROM diagnoses').fetchone()['n'],1)
            self.assertEqual(db.execute('SELECT count(*) AS n FROM events').fetchone()['n'],1)
            self.assertIn('AssertionError',ollama.call_args.args[0][1]['content'])

    def test_invalid_diagnosis_not_saved(self):
        with agent.connection() as db:
            agent.record(db,self.j,{'action':'run_tests','path':'','content':'','reason':''},'ERROR: a failed test')
            with patch.object(agent,'ollama',return_value={'hypotheses':[{'cause':'a','evidence':'b','safe_check':'c','priority':99}]}):
                with self.assertRaises(ValueError): agent.diagnostic_proposals(db,self.j,'dummy')
            self.assertEqual(db.execute('SELECT count(*) AS n FROM diagnoses').fetchone()['n'],0)

    def test_decide_receives_task_board_and_diagnosis(self):
        action={'action':'list_files','path':'','content':'','reason':''}
        with patch.object(agent,'ollama',return_value=action) as mock:
            agent.decide('goal',self.plan,[],'dummy',board=[{'title':'Implement','priority':5}],diagnoses=[[{'cause':'X'}]])
            msg=mock.call_args.args[0][1]['content']
            self.assertIn('Implement',msg)
            self.assertIn('cause',msg)


if __name__=='__main__': unittest.main()
