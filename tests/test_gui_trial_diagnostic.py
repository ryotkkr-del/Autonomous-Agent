"""Headless GUI initial diagnostic tests: never open Tk, Docker, or Ollama."""
import queue
from unittest.mock import patch
import unittest

import gui


class Label:
    def __init__(self):
        self.value = ""
    def set(self, value):
        self.value = value


class Root:
    def __init__(self):
        self.scheduled = []
    def after(self, delay, callback):
        self.scheduled.append((delay, callback))


class TrialDiagnosticGuiTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(gui.DesktopApp)
        self.app._trial_queue = queue.Queue(maxsize=1)
        self.app._trial_running = False
        self.app.status_label = Label()
        self.app.root = Root()
        self.app.output_file = None
        self.safe = {
            "assessment": "runtime_prerequisites_found_not_e2e",
            "static_assessment": "manual_trial_prerequisites_found",
            "ollama": {"status": "ready", "private_server_path": "C:\\private\\keys"},
            "docker": {"status": "ready", "detail": "SECRET=DO_NOT_SHOW"},
        }

    def test_success_message_is_cautious_and_filtered(self):
        okay, message = gui.format_trial_diagnostic(self.safe)
        self.assertTrue(okay)
        self.assertIn("実機E2E合格ではありません", message)
        self.assertIn("設定の変更やダウンロードは行っていません", message)
        self.assertNotIn("SECRET", message)
        self.assertNotIn("C:\\private", message)

    def test_missing_model_message_is_helpful_and_non_sensitive(self):
        result = {
            "assessment": "not_ready",
            "static_assessment": "manual_trial_prerequisites_found",
            "ollama": {"status": "model_missing", "unknown": "PRIVATE"},
            "docker": {"status": "unavailable", "stage": "remote_daemon", "url": "SECRET"},
        }
        ok, message = gui.format_trial_diagnostic(result)
        self.assertFalse(ok)
        self.assertIn("gemma3:4bがありません", message)
        self.assertIn("Docker: テスト実行用の環境が未準備", message)
        self.assertNotIn("PRIVATE", message)
        self.assertNotIn("SECRET", message)

    def test_unknown_objects_show_no_exception_or_private_content(self):
        for report in (None, [], {}, {"assessment": "not_ready",
                                    "ollama": "SECRET", "docker": 1}):
            with self.subTest(report=report):
                ok, message = gui.format_trial_diagnostic(report)
                self.assertFalse(ok)
                self.assertNotIn("SECRET", message)

    def test_button_work_runs_in_separate_worker_and_uses_queue(self):
        with patch("windows_runtime_probe.inspect_runtime", return_value=self.safe) as probe:
            with patch.object(gui.threading, "Thread") as worker_type:
                gui.DesktopApp.check_trial_runtime(self.app)
                self.assertTrue(self.app._trial_running)
                worker_type.assert_called_once()
                self.assertTrue(worker_type.call_args.kwargs["daemon"])
                probe.assert_not_called()
                self.assertTrue(self.app._trial_queue.empty())
                # Simulate the worker without running an actual thread.
                worker_type.call_args.kwargs["target"]()
                probe.assert_called_once()
        self.assertEqual(self.app._trial_queue.get_nowait(), self.safe)

    def test_second_click_never_starts_another_probe(self):
        self.app._trial_running = True
        with patch.object(gui.threading, "Thread") as worker_type, \
             patch.object(gui.messagebox, "showinfo") as notice:
            gui.DesktopApp.check_trial_runtime(self.app)
            worker_type.assert_not_called()
            notice.assert_called_once()

    def test_probe_exceptions_are_sanitized_and_not_leaked(self):
        with patch("windows_runtime_probe.inspect_runtime",
                   side_effect=RuntimeError("API_KEY=PRIVATE")):
            with patch.object(gui.threading, "Thread") as worker:
                gui.DesktopApp.check_trial_runtime(self.app)
                worker.call_args.kwargs["target"]()
        report = self.app._trial_queue.get_nowait()
        self.assertEqual(report["assessment"], "not_ready")
        self.assertNotIn("PRIVATE", str(report))

    def test_poll_delivers_message_on_gui_thread_and_clears_busy_state(self):
        self.app._trial_running = True
        self.app._trial_queue.put(self.safe)
        with patch.object(gui.messagebox, "showinfo") as info, \
             patch.object(gui.messagebox, "showwarning") as warning:
            gui.DesktopApp._poll(self.app)
            info.assert_called_once()
            warning.assert_not_called()
        self.assertFalse(self.app._trial_running)
        self.assertTrue(self.app._trial_queue.empty())
        self.assertTrue(self.app.root.scheduled)

    def test_failed_probe_uses_warning_not_success(self):
        self.app._trial_running = True
        self.app._trial_queue.put({"assessment": "not_ready"})
        with patch.object(gui.messagebox, "showinfo") as info, \
             patch.object(gui.messagebox, "showwarning") as warning:
            gui.DesktopApp._poll(self.app)
            info.assert_not_called()
            warning.assert_called_once()
        self.assertFalse(self.app._trial_running)

    def test_thread_launch_error_is_visible_without_local_details(self):
        with patch.object(gui.threading, "Thread") as worker_type, \
             patch.object(gui.messagebox, "showwarning") as warning:
            worker_type.side_effect = RuntimeError("TOKEN=DO_NOT_DISPLAY")
            gui.DesktopApp.check_trial_runtime(self.app)
            warning.assert_called_once()
            self.assertNotIn("TOKEN", str(warning.call_args))
            self.assertFalse(self.app._trial_running)


    def test_inconsistent_result_never_receives_green_status(self):
        inconsistent = {
            "assessment": "runtime_prerequisites_found_not_e2e",
            "static_assessment": "not_ready",
            "ollama": {"status": "ready"},
            "docker": {"status": "ready"},
            "blockers": ["required_source_files_missing_or_unsafe"],
        }
        status, message = gui.format_trial_diagnostic(inconsistent)
        self.assertFalse(status)
        self.assertIn("準備に不足", message)



if __name__ == "__main__":
    unittest.main()
