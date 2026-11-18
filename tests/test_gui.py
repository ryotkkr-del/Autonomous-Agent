"""Headless tests for the UI's durable, security-sensitive helpers."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui import validate_goal, extract_job_id, load_jobs, job_folder, readonly_database_uri

class DesktopHelpersTest(unittest.TestCase):
    def test_goal_validation(self):
        self.assertEqual(validate_goal('  記録を作る  '), '記録を作る')
        with self.assertRaises(ValueError):validate_goal('  ')
        with self.assertRaises(ValueError):validate_goal('a'*2001)

    def test_extract_created_job(self):
        self.assertEqual(extract_job_id('Created job # 17\n'),17)
        self.assertEqual(extract_job_id('Created safe/free job # 18\n'),18)
        with self.assertRaises(ValueError):extract_job_id('ERROR')

    def test_read_only_job_listing(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'state.sqlite3'
            self.assertEqual(load_jobs(file),[])
            db = sqlite3.connect(file)
            try:
                db.execute('CREATE TABLE jobs (id INTEGER, goal TEXT, status TEXT, steps INTEGER, result TEXT, allow_tests INTEGER, allow_git INTEGER, workspace_rel TEXT, updated TEXT)')
                db.execute('INSERT INTO jobs VALUES (1, ?, ?, 0, ?, 0, 0, ?, ?)',('目標','paused','','jobs/1','today'))
            finally:
                db.commit()
                db.close()
            rows=load_jobs(file)
            self.assertEqual(rows[0]['goal'],'目標')
            self.assertEqual(len(rows),1)

    def test_readonly_uri_escapes_windows_uri_characters(self):
        with tempfile.TemporaryDirectory(prefix='agent#readonly-') as d:
            file = Path(d) / 'state.sqlite3'
            db = sqlite3.connect(file)
            db.execute('CREATE TABLE jobs (id INTEGER, goal TEXT, status TEXT, steps INTEGER, result TEXT, allow_tests INTEGER, allow_git INTEGER, workspace_rel TEXT, updated TEXT)')
            db.commit()
            db.close()
            uri = readonly_database_uri(file)
            self.assertIn('%23', uri)
            self.assertTrue(uri.endswith('?mode=ro'))
            self.assertEqual(load_jobs(file), [])

    def test_job_folder_prevents_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.assertEqual(job_folder({'id':1,'workspace_rel':'jobs/1'},root),root/'workspace'/'jobs'/'1')
            for rel in ['../outside','jobs/2','/absolute']:
                with self.assertRaises(ValueError):job_folder({'id':1,'workspace_rel':rel},root)

if __name__=='__main__':unittest.main()
