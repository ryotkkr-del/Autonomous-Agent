"""Headless regression tests for the v1.0 status summary."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from gui import describe_status, read_job_details, count_outputs


class UsabilityTests(unittest.TestCase):
    def test_clear_stop_reason(self):
        self.assertIn('再開', describe_status({'status':'paused','result':'step budget reached'}))
        self.assertIn('停止', describe_status({'status':'blocked','result':'same action repeated 3 times'}))

    def test_error_detail(self):
        self.assertIn('connection refused', describe_status({'status':'paused','result':'ERROR: connection refused'}))

    def test_missing_database(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(read_job_details(7,Path(d)/'missing.sqlite3')['task_total'],0)

    def test_readonly_details(self):
        with tempfile.TemporaryDirectory() as d:
            dbpath=Path(d)/'jobs.sqlite3'
            db = sqlite3.connect(dbpath)
            try:
                db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY,job_id INTEGER,action TEXT)')
                db.execute('CREATE TABLE plan_tasks (job_id INTEGER,state TEXT)')
                db.execute("INSERT INTO events(job_id,action) VALUES(4, ?)",('write_file',))
                db.execute("INSERT INTO plan_tasks VALUES(4,'done')")
                db.execute("INSERT INTO plan_tasks VALUES(4,'todo')")
            finally:
                db.close()
            r=read_job_details(4,dbpath)
            self.assertEqual((r['task_total'],r['task_done']),(2,1))
            self.assertIn('編集',r['last_action'])

    def test_output_counter_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'normal.txt').write_text('hi')
            (root/'sub').mkdir(); (root/'sub'/'child.py').write_text('pass')
            (root/'link').symlink_to(root/'normal.txt')
            self.assertEqual(count_outputs(root),2)
