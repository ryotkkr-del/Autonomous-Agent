"""Live Docker isolation smoke test, run only in dedicated Docker CI."""
import os
import tempfile
import unittest
from pathlib import Path

import sandbox_runner


@unittest.skipUnless(os.environ.get("AGENT_TEST_LIVE_DOCKER") == "1",
                     "Run only with explicit Docker CI opt-in")
class DockerIntegrationTests(unittest.TestCase):
    def test_isolation_blocks_host_writes_and_network(self):
        with tempfile.TemporaryDirectory(prefix="agent-sandbox-live-") as d:
            work = Path(d)
            tests = work / "tests"
            tests.mkdir()
            (tests / "test_security.py").write_text(
                "import pathlib, socket, unittest\n"
                "class Security(unittest.TestCase):\n"
                "  def test_workspace_cannot_be_modified(self):\n"
                "    with self.assertRaises(OSError):\n"
                "      pathlib.Path('/workspace/evil.txt').write_text('changed')\n"
                "  def test_network_is_disabled(self):\n"
                "    with self.assertRaises(OSError):\n"
                "      socket.create_connection(('1.1.1.1', 443), timeout=1)\n",
                encoding="utf-8"
            )
            result = sandbox_runner.run_tests(work)
            self.assertTrue(result.startswith("TEST PASS [Docker sandbox]"), result)


    def test_virtual_draft_runs_in_docker_without_writing_workspace(self):
        import agent
        with tempfile.TemporaryDirectory(prefix="agent-draft-docker-") as directory:
            previous=agent.ROOT,agent.WORKSPACE,agent.DB
            try:
                agent.ROOT=Path(directory)
                agent.WORKSPACE=agent.ROOT/"workspace"
                agent.DB=agent.ROOT/"state.sqlite3"
                agent.ensure_workspace()
                jobid=agent.make_job("draft isolated test",require_approval=True,draft_mode=True)
                with agent.connection() as db:
                    job=db.execute("SELECT * FROM jobs WHERE id=?",(jobid,)).fetchone()
                    with agent.job_workspace(job):
                        first=agent.draft_action(db,jobid,{
                            "action":"write_file","path":"calc.py",
                            "content":"def double(x): return x*2\n","reason":"source"})
                        second=agent.draft_action(db,jobid,{
                            "action":"write_file","path":"tests/test_calc.py",
                            "content":"import unittest,runpy\nclass Example(unittest.TestCase):\n def test_double(self): self.assertEqual(runpy.run_path('/workspace/calc.py')['double'](3),6)\n",
                            "reason":"test"})
                        result=agent.draft_action(db,jobid,{"action":"run_tests","path":"",
                            "content":"","reason":"verify"},allow_tests=True)
                self.assertIn("DRAFT SAVED",first)
                self.assertIn("DRAFT SAVED",second)
                self.assertTrue(result.startswith("TEST PASS"),result)
                self.assertFalse((agent.WORKSPACE/"jobs"/str(jobid)/"calc.py").exists())
            finally:
                agent.ROOT,agent.WORKSPACE,agent.DB=previous


if __name__ == "__main__":
    unittest.main()
