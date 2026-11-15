"""Sandbox contract: Docker-only, no-network, read-only and fail-closed."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, call

import agent
import sandbox_runner as sandbox


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.workspace=Path(self.tmp.name)/"workspace"
        self.workspace.mkdir()
        tests=self.workspace/"tests"
        tests.mkdir()
        (tests/"test_example.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n"
            "    def test_one(self):\n        self.assertEqual(1,1)\n",
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_is_deny_without_docker(self):
        with patch.object(sandbox, "availability", return_value=(False, "missing docker")), \
             patch.object(sandbox.subprocess, "run") as runner:
            result=sandbox.run_tests(self.workspace)
        self.assertTrue(result.startswith("ERROR: sandbox unavailable:"))
        runner.assert_not_called()

    def test_unapproved_tests_never_call_runner(self):
        with patch.object(agent, "tests_exist", return_value=True), \
             patch.object(sandbox, "run_tests", side_effect=AssertionError("must not run")):
            self.assertIn("disabled", agent.run_workspace_tests(False))

    def test_agent_always_uses_container(self):
        with patch.object(agent, "tests_exist", return_value=True), \
             patch.object(sandbox, "run_tests", return_value="TEST PASS [Docker sandbox]") as runner, \
             patch.object(agent, "WORKSPACE", self.workspace):
            result=agent.run_workspace_tests(True)
        self.assertTrue(result.startswith("TEST PASS"))
        runner.assert_called_once_with(self.workspace, timeout=agent.MAX_TEST_SECONDS)

    def test_command_protects_host(self):
        with patch.object(sandbox.shutil, "which", return_value="docker"):
            args=sandbox.command(self.workspace,"autonomous-agent-test-unit")
        command=" ".join(args)
        for required in ["--network none","--read-only","--cap-drop ALL",
                         "--security-opt no-new-privileges:true",
                         "--pids-limit 64","--memory 512m","--cpus 1",
                         "--user 65534:65534","--pull never",
                         "readonly","--tmpfs /tmp:","python -I -m unittest"]:
            self.assertIn(required,command)
        self.assertNotIn("--privileged",args)
        self.assertNotIn("docker.sock",command)
        self.assertNotIn("sh -c",command)

    def test_success_needs_nonzero_discovered_tests(self):
        with patch.object(sandbox, "availability", return_value=(True, "ready")), \
             patch.object(sandbox.shutil, "which", return_value="docker"), \
             patch.object(sandbox.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0,stdout="Ran 1 test in 0.01s\n\nOK\n",stderr="")):
            outcome=sandbox.run_tests(self.workspace)
        self.assertTrue(outcome.startswith("TEST PASS [Docker sandbox]"))

    def test_zero_tests_cannot_pass(self):
        with patch.object(sandbox, "availability", return_value=(True, "ready")), \
             patch.object(sandbox.shutil, "which", return_value="docker"), \
             patch.object(sandbox.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0,stdout="Ran 0 tests in 0.01s\nOK\n",stderr="")):
            outcome=sandbox.run_tests(self.workspace)
        self.assertTrue(outcome.startswith("ERROR:"))

    def test_timeout_does_not_run_host_fallback(self):
        from subprocess import TimeoutExpired
        with patch.object(sandbox, "availability", return_value=(True, "ready")), \
             patch.object(sandbox.shutil, "which", return_value="docker"), \
             patch.object(sandbox.subprocess, "run", side_effect=[
                 TimeoutExpired(["docker","run"],45),
                 SimpleNamespace(returncode=0,stdout="",stderr="")
             ]) as runner:
            outcome=sandbox.run_tests(self.workspace)
        self.assertIn("timed out",outcome)
        self.assertEqual(runner.call_count,2)
        self.assertIn("rm",runner.call_args.args[0])


if __name__=="__main__":
    unittest.main()
