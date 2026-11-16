"""Regression tests for GUI timer proliferation, without opening a Tk window."""
import queue
import unittest
from unittest.mock import patch, Mock

import gui


class FakeRoot:
    def __init__(self):
        self.scheduled = []

    def after(self, delay, callback):
        self.scheduled.append((delay, callback))


class GuiTimerTests(unittest.TestCase):
    def test_initialization_schedules_exactly_one_poll_and_one_refresh(self):
        root = FakeRoot()
        root.title = Mock()
        root.geometry = Mock()
        root.minsize = Mock()
        with patch.object(gui.DesktopApp, "_build"), \
             patch.object(gui.DesktopApp, "refresh"), \
             patch.object(gui.tk, "StringVar", return_value=Mock()), \
             patch.object(gui.tk, "IntVar", return_value=Mock()), \
             patch.object(gui.tk, "BooleanVar", return_value=Mock()):
            app = gui.DesktopApp(root)
        self.assertEqual(len(root.scheduled), 2)
        self.assertEqual([delay for delay, _ in root.scheduled], [350, 2000])
        self.assertEqual(root.scheduled[0][1], app._poll)
        self.assertEqual(root.scheduled[1][1], app._refresh_periodic)

    def test_frequent_polling_does_not_spawn_new_refresh_loops(self):
        app = object.__new__(gui.DesktopApp)
        app.root = FakeRoot()
        app._trial_queue = queue.Queue(maxsize=1)
        app.output_file = None
        for _ in range(100):
            gui.DesktopApp._poll(app)
        self.assertEqual(len(app.root.scheduled), 100)
        self.assertTrue(all(delay == 350 and handler == app._poll
                            for delay, handler in app.root.scheduled))
        self.assertFalse(any(handler == app._refresh_periodic
                             for _, handler in app.root.scheduled))

    def test_refresh_loop_rearms_exactly_once_per_tick(self):
        app = object.__new__(gui.DesktopApp)
        app.root = FakeRoot()
        app.worker = None
        app.output_file = None
        with patch.object(gui.DesktopApp, "refresh") as refresh:
            for tick in range(50):
                gui.DesktopApp._refresh_periodic(app)
                self.assertEqual(len(app.root.scheduled), tick + 1)
                self.assertEqual(app.root.scheduled[-1],
                                 (2000, app._refresh_periodic))
        self.assertEqual(refresh.call_count, 50)

    def test_refresh_skips_db_during_running_child_process(self):
        app = object.__new__(gui.DesktopApp)
        app.root = FakeRoot()
        app.worker = object()
        app.output_file = None
        with patch.object(gui.DesktopApp, "refresh") as refresh:
            gui.DesktopApp._refresh_periodic(app)
            refresh.assert_not_called()
        self.assertEqual(app.root.scheduled, [(2000, app._refresh_periodic)])

    def test_refresh_skips_db_during_log_handling(self):
        app = object.__new__(gui.DesktopApp)
        app.root = FakeRoot()
        app.worker = None
        app.output_file = "synthetic log path, not accessed"
        with patch.object(gui.DesktopApp, "refresh") as refresh:
            gui.DesktopApp._refresh_periodic(app)
            refresh.assert_not_called()
        self.assertEqual(app.root.scheduled, [(2000, app._refresh_periodic)])


if __name__ == "__main__":
    unittest.main()
