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


if __name__ == "__main__":
    unittest.main()
