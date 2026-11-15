"""Security regression checks for workspace writes and sandbox snapshots."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
import sandbox_runner


class WorkspaceHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=(agent.ROOT,agent.WORKSPACE,agent.DB)
        agent.ROOT=Path(self.tmp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.tmp.cleanup()

    def _write(self,path,content):
        return agent.execute({"action":"write_file","path":path,
                              "content":content,"reason":"test"})

    def test_existing_write_preserves_earlier_backup(self):
        path=agent.WORKSPACE/'note.md'
        path.write_text('original',encoding='utf-8')
        self.assertIn('WROTE',self._write('note.md','updated'))
        self.assertIn('WROTE',self._write('note.md','newer'))
        self.assertEqual(path.read_text(encoding='utf-8'),'newer')
        self.assertEqual((agent.WORKSPACE/'note.md.agent-backup').read_text(encoding='utf-8'),'original')

    def test_dangling_backup_symlink_cannot_write_outside_workspace(self):
        outside=agent.ROOT/'external.md'
        path=agent.WORKSPACE/'note.md'
        path.write_text('original',encoding='utf-8')
        backup=agent.WORKSPACE/'note.md.agent-backup'
        try: backup.symlink_to(outside)
        except (OSError,NotImplementedError): self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            self._write('note.md','updated')
        self.assertFalse(outside.exists())
        self.assertEqual(path.read_text(encoding='utf-8'),'original')

    def test_preexisting_legacy_temp_symlink_not_used(self):
        outside=agent.ROOT/'external.txt'
        outside.write_text('safe',encoding='utf-8')
        legacy=agent.WORKSPACE/'file.txt.agent-tmp'
        try: legacy.symlink_to(outside)
        except (OSError,NotImplementedError): self.skipTest('symlinks unavailable')
        self.assertIn('WROTE',self._write('file.txt','agent data'))
        self.assertEqual(outside.read_text(encoding='utf-8'),'safe')

    def test_staging_excludes_secrets_and_unknown_extensions(self):
        src=agent.WORKSPACE
        (src/'main.py').write_text('value=1',encoding='utf-8')
        (src/'test_data.json').write_text('{"ok":true}',encoding='utf-8')
        (src/'credentials.json').write_text('should not copy',encoding='utf-8')
        (src/'api_token.txt').write_text('should not copy',encoding='utf-8')
        (src/'.env').write_text('SECRET=1',encoding='utf-8')
        (src/'private.pdf').write_bytes(b'%PDF')
        with tempfile.TemporaryDirectory() as destination:
            sandbox_runner.snapshot_workspace(src,destination)
            self.assertTrue((Path(destination)/'main.py').exists())
            self.assertTrue((Path(destination)/'test_data.json').exists())
            for filename in ['credentials.json','api_token.txt','.env','private.pdf']:
                self.assertFalse((Path(destination)/filename).exists())

    def test_staging_rejects_hardlinked_file(self):
        outside=agent.ROOT/'outside.py'
        outside.write_text('key=1',encoding='utf-8')
        try: os.link(outside,agent.WORKSPACE/'copy.py')
        except (OSError,NotImplementedError): self.skipTest('hardlinks unavailable')
        with tempfile.TemporaryDirectory() as destination:
            with self.assertRaisesRegex(ValueError,'hard-linked'):
                sandbox_runner.snapshot_workspace(agent.WORKSPACE,destination)


if __name__=='__main__':
    unittest.main()
