"""P0-6 opt-in, privacy preserving local runtime probe tests (no real access)."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import windows_runtime_probe as probe


class FakeResponse:
    def __init__(self, status=200, body=b'{"models":[{"name":"gemma3:4b"}]}'):
        self.status = status
        self.body = body

    def read(self, count):
        return self.body[:count]


class FakeConnection:
    def __init__(self, response=None, failure=None):
        self.response = response or FakeResponse()
        self.failure = failure
        self.calls = []
        self.closed = False

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.failure:
            raise self.failure

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class WindowsRuntimeProbeTests(unittest.TestCase):
    def _ollama(self, response=None, failure=None):
        instance = FakeConnection(response=response, failure=failure)
        used = []

        def factory(host, port, timeout):
            used.append((host, port, timeout))
            return instance

        report = probe.probe_ollama(connection_factory=factory)
        return report, instance, used

    def test_local_tags_only_no_prompt_proxy_or_redirect(self):
        result, client, used = self._ollama()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["expected_model"], "gemma3:4b")
        self.assertEqual(used, [("127.0.0.1", 11434, 3)])
        self.assertEqual(client.calls, [(("GET", "/api/tags"),
                                         {"headers": {"Accept": "application/json"}})])
        self.assertTrue(client.closed)

    def test_other_models_are_not_automatically_downloaded(self):
        response = FakeResponse(body=b'{"models":[{"name":"llama3:8b"}]}')
        result, client, _ = self._ollama(response)
        self.assertEqual(result["status"], "model_missing")
        self.assertNotIn("llama3", json.dumps(result))
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(client.closed)

    def test_redirect_is_never_followed(self):
        result, client, _ = self._ollama(FakeResponse(status=302, body=b""))
        self.assertEqual(result, {"status": "unavailable", "reason": "non_200_response"})
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(client.closed)

    def test_invalid_json_and_missing_models_rejected(self):
        for body in (b"not-json", b"{}", b'{"models":{}}',
                     b'{"models":["invalid"]}', b'{"models":[{"name":5}]}'):
            with self.subTest(body=body):
                result, client, _ = self._ollama(FakeResponse(body=body))
                self.assertEqual(result["status"], "unavailable")
                self.assertTrue(client.closed)

    def test_oversized_http_response_rejected(self):
        data = b"Z" * (probe.MAX_OLLAMA_BYTES + 1)
        result, client, _ = self._ollama(FakeResponse(body=data))
        self.assertEqual(result["reason"], "response_too_large")
        self.assertTrue(client.closed)

    def test_loopback_errors_do_not_expose_exception_data(self):
        result, client, _ = self._ollama(failure=OSError("token=PRIVATE"))
        self.assertEqual(result["reason"], "loopback_probe_failed")
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertTrue(client.closed)

    def test_docker_stage_is_whitelisted_and_details_are_not_printed(self):
        ok = probe.probe_docker(diagnosis=lambda: {
            "ready": True, "stage": "ready", "detail": "TOKEN=SECRET"})
        self.assertEqual(ok, {"status": "ready", "stage": "ready"})
        bad = probe.probe_docker(diagnosis=lambda: {
            "ready": False, "stage": "not-listed", "detail": "SECRET"})
        self.assertEqual(bad, {"status": "unavailable", "stage": "unknown"})
        self.assertNotIn("SECRET", json.dumps(ok) + json.dumps(bad))

    def test_docker_failure_is_fail_closed(self):
        def throws():
            raise RuntimeError("private path")
        self.assertEqual(probe.probe_docker(diagnosis=throws),
                         {"status": "unavailable", "stage": "unknown"})

    def test_windows_prerequisites_do_not_claim_real_e2e(self):
        static = lambda: {"assessment": "manual_trial_prerequisites_found", "blockers": []}
        outcome = probe.inspect_runtime(
            static_check=static,
            ollama_check=lambda: {"status": "ready"},
            docker_check=lambda: {"status": "ready"},
            system_name="Windows")
        self.assertEqual(outcome["assessment"], "runtime_prerequisites_found_not_e2e")
        self.assertFalse(outcome["actual_e2e_verified"])
        self.assertFalse(outcome["updates_enabled"])
        self.assertEqual(outcome["guarantees"], "none")
        self.assertIn("real_gui_launch_and_close", outcome["manual_checks_still_required"])

    def test_non_windows_never_counts_as_windows_e2e(self):
        outcome = probe.inspect_runtime(
            static_check=lambda: {"assessment": "manual_trial_prerequisites_found",
                                  "blockers": []},
            ollama_check=lambda: {"status": "ready"},
            docker_check=lambda: {"status": "ready"},
            system_name="Linux")
        self.assertEqual(outcome["assessment"], "not_ready")
        self.assertIn("windows_device_required_for_windows_e2e",
                      outcome["blockers"])

    def test_missing_model_and_docker_prevent_readiness(self):
        outcome = probe.inspect_runtime(
            static_check=lambda: {"assessment": "not_ready",
                                  "blockers": ["python_3_11_or_later_required"]},
            ollama_check=lambda: {"status": "model_missing"},
            docker_check=lambda: {"status": "unavailable"},
            system_name="Windows")
        self.assertEqual(outcome["assessment"], "not_ready")
        self.assertEqual(len(outcome["blockers"]), 3)

    def test_help_never_contacts_ollama_or_docker(self):
        script = Path(probe.__file__).resolve()
        completed = subprocess.run(
            [sys.executable, "-I", str(script), "--help"],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--probe-runtime", completed.stdout)

    def test_missing_explicit_flag_refused(self):
        script = Path(probe.__file__).resolve()
        completed = subprocess.run(
            [sys.executable, "-I", str(script)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--probe-runtime", completed.stderr)

    def test_json_mode_emits_only_safe_results(self):
        safe = {"assessment": "not_ready", "blockers": ["no_docker"],
                "ollama": {"status": "unavailable"},
                "docker": {"status": "unavailable"}, "guarantees": "none"}
        with patch.object(probe, "inspect_runtime", return_value=safe):
            out = StringIO()
            with redirect_stdout(out):
                status = probe.main(["--probe-runtime", "--json"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(out.getvalue()), safe)


if __name__ == "__main__":
    unittest.main()
