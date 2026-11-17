import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patchers=[patch.object(agent,'ROOT',self.root),patch.object(agent,'WORKSPACE',self.root/'workspace'),patch.object(agent,'DB',self.root/'state.sqlite3')]
        for p in self.patchers:p.start()
        agent.ensure_workspace()
    def tearDown(self):
        for p in reversed(self.patchers):p.stop()
        self.temp.cleanup()
    def test_escape(self):
        for v in ('../oops','/tmp/x','C:/windows/x','folder\\x',''):
            with self.assertRaises(ValueError):agent.safe_path(v)
    def test_symlink(self):
        outside=self.root/'outside';outside.mkdir()
        try:(agent.WORKSPACE/'link').symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
        with self.assertRaises(ValueError):agent.safe_path('link/file')
    def test_atomic_write_backup(self):
        p=agent.WORKSPACE/'note.md'
        self.assertIn('WROTE',agent.execute({'action':'write_file','path':'note.md','content':'hello'}))
        self.assertIn('WROTE',agent.execute({'action':'write_file','path':'note.md','content':'updated'}))
        self.assertEqual(p.read_text(),'updated')
        self.assertEqual((agent.WORKSPACE/'note.md.agent-backup').read_text(),'hello')
    def test_checkpoint_resume_verified(self):
        job=agent.make_job('create a note')
        plan={'tasks':['write a note'],'deliverables':['note.md']}
        actions=[{'action':'write_file','path':'note.md','content':'hello','reason':''},
                 {'action':'finish','path':'','content':'','reason':'done'}]
        with patch.object(agent,'make_plan',return_value=plan),patch.object(agent,'decide',side_effect=actions),patch.object(agent,'review',return_value=(True,'verified')):
            agent.run(job,'dummy',1)
            with agent.connection() as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()['status'],'paused')
            agent.run(job,'dummy',1)
        self.assertEqual((agent.WORKSPACE/f'jobs/{job}/note.md').read_text(),'hello')
        with agent.connection() as db:
            row=db.execute('SELECT status,steps,plan FROM jobs').fetchone()
            self.assertEqual((row['status'],row['steps']),('done',2))
            self.assertEqual(__import__('json').loads(row['plan'])['tasks'],plan['tasks'])
    def test_finish_rejected_if_missing(self):
        job=agent.make_job('create a note')
        plan={'tasks':['write a note'],'deliverables':['missing.txt']}
        with patch.object(agent,'make_plan',return_value=plan),patch.object(agent,'decide',return_value={'action':'finish','path':'','content':'','reason':'done'}):
            agent.run(job,'dummy',1)
        with agent.connection() as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()['status'],'paused')

    def test_initial_plan_retries_after_malformed_model_output(self):
        job=agent.make_job('create a note')
        plan={'tasks':['write a note'],'deliverables':['note.md']}
        actions=[{'action':'write_file','path':'note.md','content':'hello','reason':''}]
        with patch.object(agent,'make_plan',side_effect=[ValueError('unsafe path'),plan]) as make_plan, \
             patch.object(agent,'decide',side_effect=actions):
            agent.run(job,'dummy',1)
        self.assertEqual(make_plan.call_count,2)
        self.assertEqual(make_plan.call_args_list[1].kwargs,{'retry':True})
        with agent.connection() as db:
            row=db.execute('SELECT status,plan FROM jobs WHERE id=?',(job,)).fetchone()
        self.assertEqual(row['status'],'paused')
        self.assertEqual(__import__('json').loads(row['plan']),plan)

    def test_initial_plan_rejection_pauses_without_crashing(self):
        job=agent.make_job('create a note')
        with patch.object(agent,'make_plan',side_effect=ValueError('unsafe path')):
            agent.run(job,'dummy',1)
        with agent.connection() as db:
            row=db.execute('SELECT status,result,plan FROM jobs WHERE id=?',(job,)).fetchone()
            event=db.execute('SELECT action,result FROM events WHERE job_id=?',(job,)).fetchone()
        self.assertEqual(row['status'],'paused')
        self.assertEqual(row['plan'],'')
        self.assertEqual(row['result'],'initial plan rejected: ValueError')
        self.assertEqual(tuple(event),('plan_error','ERROR: initial plan rejected: ValueError'))
    def test_stop(self):
        job=agent.make_job('test');(self.root/'STOP').touch()
        with patch.object(agent,'make_plan',return_value={'tasks':['a'],'deliverables':[]}),patch.object(agent,'decide') as d:
            agent.run(job,'dummy',2);d.assert_not_called()
    def test_repeats_detected(self):
        job=agent.make_job('test')
        action={'action':'list_files','path':'','content':'','reason':''}
        plan={'tasks':['a'],'deliverables':[]}
        with patch.object(agent,'make_plan',return_value=plan), \
             patch.object(agent,'decide',return_value=action), \
             patch.object(agent,'revise_plan',return_value=plan) as revise:
            agent.run(job,'dummy',12)
        with agent.connection() as db:
            row=db.execute('SELECT result,steps,status FROM jobs').fetchone()
            guard=db.execute('SELECT stall_recoveries FROM job_controls WHERE job_id=?',(job,)).fetchone()
            self.assertEqual(row['status'],'blocked')
            self.assertIn('repeated',row['result'])
            self.assertGreater(row['steps'],3)
            self.assertEqual(guard['stall_recoveries'],agent.MAX_STALL_RECOVERIES)
            # The regular 8-step checkpoint may also invoke the mocked planner.
            self.assertGreaterEqual(revise.call_count,agent.MAX_STALL_RECOVERIES)
    def test_tick_selects_pending(self):
        job=agent.make_job('pending')
        with patch.object(agent,'run') as runner:
            agent.tick('dummy',3)
            runner.assert_called_once_with(job,'dummy',3)
    def test_tick_respects_stop(self):
        agent.make_job('pending')
        (self.root/'STOP').touch()
        with patch.object(agent,'run') as runner:
            agent.tick('dummy',3)
            runner.assert_not_called()
    def test_migration(self):
        import sqlite3
        con=sqlite3.connect(agent.DB)
        con.execute('CREATE TABLE jobs (id INTEGER PRIMARY KEY, goal TEXT, status TEXT, created TEXT, updated TEXT, steps INTEGER DEFAULT 0, result TEXT DEFAULT "", codex_used INTEGER DEFAULT 0)')
        con.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, job_id INTEGER, created TEXT, action TEXT, details TEXT, result TEXT)')
        con.commit();con.close()
        with agent.connection() as db:
            self.assertIn('plan',{r['name'] for r in db.execute('PRAGMA table_info(jobs)')})
            self.assertIn('signature',{r['name'] for r in db.execute('PRAGMA table_info(events)')})

if __name__=='__main__':unittest.main()
