"""v2.6 hostile-input regression tests: workspace isolation and network pinning."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import agent


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=agent.ROOT,agent.WORKSPACE,agent.DB
        agent.ROOT=Path(self.temp.name)
        agent.WORKSPACE=agent.ROOT/'workspace'
        agent.DB=agent.ROOT/'state.sqlite3'
        agent.ensure_workspace()

    def tearDown(self):
        agent.ROOT,agent.WORKSPACE,agent.DB=self.old
        self.temp.cleanup()

    def test_hidden_credentials_and_git_metadata_are_inaccessible(self):
        paths=['.env','.git/config','.ssh/id_rsa','.github/workflows/run.yml',
               'credentials.json','my_api_key.txt','cache/passwords.json',
               'NUL.txt','CON','.secret.md','study.','README.md ']
        for raw in paths:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                agent.safe_path(raw)

    def test_sensitive_paths_do_not_appear_in_agent_file_listing_or_search(self):
        (agent.WORKSPACE/'.env').write_text('secret expression canary')
        (agent.WORKSPACE/'credentials.json').write_text('secret expression canary')
        (agent.WORKSPACE/'normal.py').write_text('def normal(): pass')
        self.assertEqual(agent.files_list(),['normal.py'])
        self.assertNotIn('canary',agent.search_code('canary'))
        self.assertIn('normal.py',agent.search_code('def normal'))

    def test_hardlinks_cannot_be_read_or_searched(self):
        outside=agent.ROOT/'outside.py'
        outside.write_text('secret canary outside')
        try:
            os.link(outside,agent.WORKSPACE/'local.py')
        except (OSError,NotImplementedError):
            self.skipTest('hardlinks unavailable')
        with self.assertRaisesRegex(ValueError,'hard-linked'):
            agent.safe_path('local.py')
        self.assertNotIn('local.py',agent.files_list())
        self.assertNotIn('canary',agent.search_code('canary'))
        self.assertEqual(outside.read_text(),'secret canary outside')

    def test_public_url_validation_rejects_private_dns(self):
        fake=[(2,1,6,'',('127.0.0.1',443))]
        with patch.object(agent.socket,'getaddrinfo',return_value=fake):
            with self.assertRaisesRegex(ValueError,'private or reserved'):
                agent.validate_public_https('https://example.org/docs')

    def test_https_network_pins_a_single_verified_dns_answer(self):
        public=[(2,1,6,'',('93.184.216.34',443))]
        private=[(2,1,6,'',('127.0.0.1',443))]
        response=MagicMock()
        response.status=200
        response.getheaders.return_value=[('Content-Type','text/plain')]
        response.read.return_value=b'hello'
        conn=MagicMock()
        conn.getresponse.return_value=response
        with patch.object(agent.socket,'getaddrinfo',side_effect=[public,private]) as resolver, \
             patch.object(agent.http.client,'HTTPSConnection',return_value=conn) as factory, \
             patch.object(agent.socket,'create_connection',return_value=MagicMock()) as connect:
            status,headers,payload=agent._fetch_public_https(
                'https://example.org/a?x=1',{'Accept':'text/plain'},500)
            self.assertEqual(resolver.call_count,1)
            self.assertEqual(status,200)
            self.assertEqual(payload,b'hello')
            self.assertEqual(headers['content-type'],'text/plain')
            self.assertEqual(factory.call_args.args[:2],('example.org',443))
            conn.request.assert_called_once_with('GET','/a?x=1',headers={'Accept':'text/plain'})
            conn._create_connection(('example.org',443),timeout=4)
            self.assertEqual(connect.call_args.args[0],('93.184.216.34',443))
            conn.close.assert_called_once()

    def test_redirects_are_not_followed_for_approved_urls(self):
        with patch.object(agent,'_fetch_public_https',return_value=(302,{'location':'http://127.0.0.1'},b'')) as fetch:
            result=agent.read_approved_url('https://example.org/a',{'https://example.org/a'})
        self.assertIn('redirects refused',result)
        fetch.assert_called_once()

    def test_local_ollama_rejects_remote_configuration_before_network(self):
        for endpoint in ('https://remote.example/api/chat',
                         'http://192.168.1.7:11434/api/chat',
                         'http://127.0.0.1:11434/redirect',
                         'http://127.0.0.1:11434/api/chat?next=remote'):
            with self.subTest(endpoint=endpoint), \
                 patch.object(agent,'OLLAMA_URL',endpoint), \
                 patch.object(agent.urllib.request,'build_opener',side_effect=AssertionError('network forbidden')):
                with self.assertRaises(ValueError):
                    agent.ollama([],{},'gemma3:4b')

    def test_localhost_ollama_is_pinned_to_numeric_loopback(self):
        values=[(2,1,6,'',('127.0.0.1',11434)),
                (10,1,6,'',('::1',11434,0,0))]
        with patch.object(agent.socket,'getaddrinfo',return_value=values):
            address=agent._validate_local_ollama_url('http://localhost:11434/api/chat')
        self.assertEqual(address,'http://127.0.0.1:11434/api/chat')
        remote=[(2,1,6,'',('93.184.216.34',11434))]
        with patch.object(agent.socket,'getaddrinfo',return_value=remote):
            with self.assertRaisesRegex(ValueError,'loopback'):
                agent._validate_local_ollama_url('http://localhost:11434/api/chat')

    def test_git_status_needs_permission_and_is_never_run_in_protected_draft(self):
        operation={'action':'git_status','path':'','content':'','reason':'inspect'}
        with patch.object(agent,'git_status',side_effect=AssertionError('Git must not execute')):
            self.assertIn('disabled',agent.execute(operation))
            jobid=agent.make_job('protected draft',require_approval=True,draft_mode=True)
            with agent.connection() as db:
                job=db.execute('SELECT * FROM jobs WHERE id=?',(jobid,)).fetchone()
                with agent.job_workspace(job):
                    self.assertIn('unavailable',agent.draft_action(db,jobid,operation))

    def test_git_cli_explicitly_disables_fsmonitor(self):
        with patch.object(agent.shutil,'which',return_value='git'), \
             patch.object(agent.subprocess,'run',return_value=MagicMock(returncode=0,stdout='',stderr='')) as invoked:
            rc,out=agent.git_command(['status','--short'])
        self.assertEqual(rc,0)
        argv=invoked.call_args.args[0]
        self.assertIn('core.fsmonitor=false',argv)
        self.assertIn('diff.external=',argv)
        self.assertIn('credential.helper=',argv)

    def test_ollama_uses_explicit_no_proxy_and_redirect_handler(self):
        payload=json.dumps({'message':{'content':'{"tasks":[]}'}}).encode()
        response=MagicMock()
        response.read.return_value=payload
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value=response
        with patch.object(agent,'OLLAMA_URL','http://127.0.0.1:11434/api/chat'), \
             patch.object(agent.urllib.request,'build_opener',return_value=opener) as build:
            value=agent.ollama([],{},'gemma3:4b')
            self.assertEqual(value,{'tasks':[]})
        self.assertIsInstance(build.call_args.args[0],agent.urllib.request.ProxyHandler)
        self.assertIsInstance(build.call_args.args[1],agent.NoRedirect)


if __name__=='__main__':
    unittest.main()
