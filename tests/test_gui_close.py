"""P0-6 GUI close: no orphan subprocess and no destructive STOP operations."""
import os
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

import gui


class Label:
    def __init__(self):
        self.value = ""
    def set(self, text):
        self.value = text


class CloseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aa-gui-close-test-")
        self.addCleanup(self.tmp.cleanup)
        self.stop = Path(self.tmp.name) / "STOP"
        self.app = object.__new__(gui.DesktopApp)
        self.app.root = Mock()
        self.app.status_label = Label()
        self.app.worker = None
        self.app.proc = None
        self.app._closed = False
        self.app._closing = False
        self.app._trial_queue = queue.Queue(maxsize=1)
        self.app.output_file = None
        self.app._append = Mock()

    def running(self):
        self.app.worker = Mock()
        self.app.worker.is_alive.return_value = True
        self.app.proc = Mock()
        self.app.proc.poll.return_value = None

    def test_stop_creates_empty_file_without_changing_other_files(self):
        neighbor = self.stop.parent / "important.txt"
        neighbor.write_bytes(b"unchanged")
        gui.request_stop_marker(self.stop)
        self.assertEqual(self.stop.read_bytes(), b"")
        self.assertEqual(neighbor.read_bytes(), b"unchanged")

    def test_existing_stop_is_not_modified(self):
        self.stop.write_bytes(b"existing")
        before = self.stop.stat().st_mtime_ns
        gui.request_stop_marker(self.stop)
        self.assertEqual(self.stop.read_bytes(), b"existing")
        self.assertEqual(self.stop.stat().st_mtime_ns, before)

    def test_stop_symlink_refused_and_target_untouched(self):
        outside = self.stop.parent / "target.txt"
        outside.write_bytes(b"PRIVATE")
        try:
            self.stop.symlink_to(outside)
        except OSError:
            self.skipTest("Windows runner does not permit symlinks")
        with self.assertRaises(ValueError):
            gui.request_stop_marker(self.stop)
        self.assertEqual(outside.read_bytes(), b"PRIVATE")

    def test_directory_as_stop_is_rejected(self):
        self.stop.mkdir()
        with self.assertRaises(ValueError):
            gui.request_stop_marker(self.stop)

    def test_hardlinked_stop_is_rejected(self):
        original = self.stop.parent / "other"
        original.write_bytes(b"intact")
        try:
            os.link(original, self.stop)
        except OSError:
            self.skipTest("hardlinks unavailable on runner")
        with self.assertRaises(ValueError):
            gui.request_stop_marker(self.stop)
        self.assertEqual(original.read_bytes(), b"intact")

    def test_idle_close_is_immediate_without_stop(self):
        gui.DesktopApp.request_close(self.app)
        self.app.root.destroy.assert_called_once_with()
        self.assertTrue(self.app._closed)
        self.assertFalse(self.stop.exists())

    def test_busy_close_decline_keeps_window_and_process(self):
        self.running()
        with patch.object(gui.messagebox, "askyesno", return_value=False):
            gui.DesktopApp.request_close(self.app)
        self.assertFalse(self.app._closing)
        self.assertFalse(self.stop.exists())
        self.app.root.destroy.assert_not_called()
        self.app.proc.terminate.assert_not_called()
        self.app.proc.kill.assert_not_called()

    def test_busy_close_requests_stop_but_does_not_destroy_or_kill(self):
        self.running()
        with patch.object(gui.messagebox, "askyesno", return_value=True), \
             patch.object(gui, "request_stop_marker",
                          side_effect=lambda: gui.request_stop_marker(self.stop)):
            # Use the real helper bound to the test-specific path.
            gui.DesktopApp.request_close(self.app)
        self.assertTrue(self.stop.exists())
        self.assertTrue(self.app._closing)
        self.app.root.destroy.assert_not_called()
        self.app.proc.terminate.assert_not_called()
        self.app.proc.kill.assert_not_called()

    def test_close_during_worker_startup_still_waits(self):
        # Worker exists, but has not assigned a Popen instance yet.
        self.app.worker = Mock()
        self.app.worker.is_alive.return_value = True
        with patch.object(gui.messagebox, "askyesno", return_value=True), \
             patch.object(gui, "request_stop_marker", return_value=None):
            gui.DesktopApp.request_close(self.app)
        self.assertTrue(self.app._closing)
        self.app.root.destroy.assert_not_called()

    def test_bad_stop_refuses_close(self):
        self.running()
        with patch.object(gui.messagebox, "askyesno", return_value=True), \
             patch.object(gui, "request_stop_marker",
                          side_effect=ValueError("PRIVATE_DETAIL")), \
             patch.object(gui.messagebox, "showwarning") as warning:
            gui.DesktopApp.request_close(self.app)
        self.assertFalse(self.app._closing)
        self.app.root.destroy.assert_not_called()
        warning.assert_called_once()
        self.assertNotIn("PRIVATE_DETAIL", str(warning.call_args))

    def test_double_close_during_wait_does_not_force_quit(self):
        self.running()
        self.app._closing = True
        with patch.object(gui.messagebox, "showinfo") as info:
            gui.DesktopApp.request_close(self.app)
        info.assert_called_once()
        self.app.root.destroy.assert_not_called()

    def test_launch_is_refused_after_close_requested(self):
        self.app._closing = True
        with patch.object(gui.messagebox, "showinfo") as notice, \
             patch.object(gui.tempfile, "mkstemp") as create_log:
            result = gui.DesktopApp.launch(self.app, ["new", "example"], "create")
        self.assertFalse(result)
        notice.assert_called_once()
        create_log.assert_not_called()

    def test_run_job_cannot_remove_stop_while_closing(self):
        self.app._closing = True
        self.stop.write_bytes(b"")
        with patch.object(gui.messagebox, "showinfo") as notice:
            gui.DesktopApp.run_job(self.app)
        notice.assert_called_once()
        self.assertTrue(self.stop.exists())

    def test_poll_after_worker_exits_closes_and_skips_success_callbacks(self):
        self.running()
        self.app._closing = True
        self.app.worker.is_alive.return_value = False
        self.app.proc.poll.return_value = 0
        self.app.proc.returncode = 0
        self.app._finish_pending = True
        self.app._on_success = Mock()
        self.app.last_output = ""
        self.app.output_pos = 0
        self.app.refresh = Mock()
        log = self.stop.parent / "agent-ui-synthetic.log"
        log.write_bytes(b"completed\n")
        self.app.output_file = log
        gui.DesktopApp._poll(self.app)
        self.app._on_success is None
        self.app.refresh.assert_not_called()
        self.app.root.destroy.assert_called_once_with()
        self.assertTrue(self.app._closed)
        self.assertFalse(log.exists())
        self.app.root.after.assert_not_called()

    def test_active_child_blocks_finish_close_even_if_worker_none(self):
        self.app.proc = Mock()
        self.app.proc.poll.return_value = None
        gui.DesktopApp._finish_close(self.app)
        self.app.root.destroy.assert_not_called()

    def test_closed_callbacks_do_not_reschedule(self):
        self.app._closed = True
        self.app.refresh = Mock()
        gui.DesktopApp._poll(self.app)
        gui.DesktopApp._refresh_periodic(self.app)
        self.app.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
