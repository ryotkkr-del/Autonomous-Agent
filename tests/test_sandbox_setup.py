"""Docker setup UX: safe diagnostics and opt-in image preparation."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import sandbox_runner as sandbox
import gui

class SetupTests(unittest.TestCase):
    def test_missing_docker_guides_install(self):
        with patch.object(sandbox,"availability",return_value=(False,"Docker CLI not found.")):
            result=sandbox.setup_diagnosis()
        self.assertEqual(result["stage"],"missing_cli")
        self.assertFalse(result["ready"])
        self.assertIn("Docker Desktop",result["next_step"])

    def test_missing_image_guides_pull(self):
        with patch.object(sandbox,"availability",return_value=(False,"Image not present. Run manually: docker pull python:3.11-slim")):
            result=sandbox.setup_diagnosis()
        self.assertEqual(result["stage"],"missing_image")

    def test_wrong_mode_diagnostic(self):
        with patch.object(sandbox,"availability",return_value=(False,"Docker must be running Linux containers.")):
            result=sandbox.setup_diagnosis()
        self.assertEqual(result["stage"],"wrong_container_mode")

    def test_remote_docker_denied(self):
        with patch.object(sandbox,"availability",return_value=(False,"Remote Docker hosts are not supported.")):
            result=sandbox.setup_diagnosis()
        self.assertEqual(result["stage"],"remote_daemon")

    def test_ready(self):
        with patch.object(sandbox,"availability",return_value=(True,"ready")):
            result=sandbox.setup_diagnosis()
        self.assertTrue(result["ready"])

    def test_image_pull_requires_consent(self):
        with patch.object(sandbox,"availability",side_effect=AssertionError("must not inspect daemon")), \
             patch.object(sandbox.subprocess,"run",side_effect=AssertionError("must not download")):
            result=sandbox.prepare_image(confirmed=False)
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("confirmation",result)

    def test_no_pull_when_daemon_unavailable(self):
        with patch.object(sandbox,"availability",return_value=(False,"Docker daemon unavailable")) as check, \
             patch.object(sandbox.subprocess,"run",side_effect=AssertionError("must not pull")):
            result=sandbox.prepare_image(confirmed=True)
        self.assertTrue(result.startswith("ERROR:"))
        check.assert_called_once_with(require_image=False)

    def test_image_pull_uses_fixed_argv(self):
        with patch.object(sandbox,"availability",side_effect=[(True,"ready"),(True,"image ready")]), \
             patch.object(sandbox.shutil,"which",return_value="docker"), \
             patch.object(sandbox.subprocess,"run",return_value=SimpleNamespace(returncode=0,stdout="ok",stderr="")) as run:
            result=sandbox.prepare_image(confirmed=True)
        self.assertIn("Docker image ready",result)
        self.assertEqual(run.call_args.args[0],["docker","pull","python:3.11-slim"])
        self.assertLessEqual(run.call_args.kwargs["timeout"],300)

    def test_gui_buttons_and_callbacks_exist(self):
        for member in ["check_sandbox","_sandbox_result","prepare_sandbox"]:
            self.assertTrue(callable(getattr(gui.DesktopApp,member)))

if __name__=="__main__":
    unittest.main()
