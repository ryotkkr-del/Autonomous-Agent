import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent

class V05Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.ps=[patch.object(agent,'ROOT',self.root),patch.object(agent,'WORKSPACE',self.root/'workspace'),patch.object(agent,'DB',self.root/'state.sqlite3')]
        for p in self.ps:p.start()
        agent.ensure_workspace()
    def tearDown(self):
        for p in reversed(self.ps):p.stop()
        self.tmp.cleanup()

    def test_urls_require_explicit_approval(self):
        out=agent.execute({'action':'read_url','path':'https://example.com/x','content':'','reason':''})
        self.assertIn('not approved',out)

    def test_private_or_malformed_urls_refused(self):
        for url in ['http://example.com','https://127.0.0.1/','https://user:pass@example.com/','https://localhost/','https://x.local/','https://example.com:8443/']:
            with self.subTest(url=url),self.assertRaises(ValueError):
                agent.validate_public_https(url)

    def test_approval_persisted(self):
        j=agent.make_job('research')
        with patch.object(agent,'validate_public_https',return_value='https://example.com'):
            agent.approve_url(j,'https://example.com')
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT url FROM approved_urls WHERE job_id=?',(j,)).fetchone()['url'],'https://example.com')
        agent.revoke_url(j,'https://example.com')
        with agent.connection() as db:
            self.assertIsNone(db.execute('SELECT url FROM approved_urls WHERE job_id=?',(j,)).fetchone())

    def test_git_opt_in(self):
        self.assertIn('disabled',agent.execute({'action':'git_checkpoint','path':'','content':'','reason':''}).lower())

    @unittest.skipUnless(shutil.which('git'),'git unavailable')
    def test_local_git_checkpoint(self):
        (agent.WORKSPACE/'output.txt').write_text('A',encoding='utf-8')
        out=agent.execute({'action':'git_checkpoint','path':'','content':'','reason':''},allow_git=True)
        self.assertTrue(out.startswith('GIT CHECKPOINT:'),out)
        (agent.WORKSPACE/'output.txt').write_text('B',encoding='utf-8')
        out=agent.execute({'action':'git_checkpoint','path':'','content':'','reason':''},allow_git=True)
        self.assertTrue(out.startswith('GIT CHECKPOINT:'),out)
        blocked=agent.execute({'action':'git_status','path':'','content':'','reason':''})
        self.assertIn('disabled',blocked.lower())
        status=agent.execute({'action':'git_status','path':'','content':'','reason':''},allow_git=True)
        self.assertEqual(status.strip(),'GIT STATUS:')

    def test_decider_receives_permissions_and_url_allowlist(self):
        with patch.object(agent,'ollama',return_value={'action':'finish','path':'','content':'','reason':'done'}) as mock:
            agent.decide('goal',{'tasks':['x'],'deliverables':['x.txt']},[],'dummy',['https://example.com'],True,False)
            payload=mock.call_args.args[0][1]['content']
            self.assertIn('https://example.com',payload)
            self.assertIn('Gitチェックポイント許可: True',payload)

    def test_legacy_db_migration_to_git(self):
        j=agent.make_job('old')
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT allow_git FROM jobs WHERE id=?',(j,)).fetchone()['allow_git'],0)
        agent.set_git(j,True)
        with agent.connection() as db:
            self.assertEqual(db.execute('SELECT allow_git FROM jobs WHERE id=?',(j,)).fetchone()['allow_git'],1)

if __name__=='__main__':unittest.main()
