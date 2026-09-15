import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from controller import Controller
from gui import MainWindow
from serial_manager import SerialManager
from test_devices import FakePort, ReaderStub


class ShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_waits_for_serial_cleanup_and_worker_exit(self):
        closing = Event()
        release = Event()

        class SlowClosePort(FakePort):
            def close(self):
                closing.set()
                release.wait(3)
                super().close()

        manager = SerialManager(SlowClosePort)
        manager.scan = lambda: [("COM_TEST", "测试")]
        manager.open("COM_TEST")
        port = manager._serial
        worker = Controller(ReaderStub(), manager)
        window = MainWindow(worker)
        window.show()
        try:
            limit = time.monotonic() + 1
            while not port.writes and time.monotonic() < limit:
                QTest.qWait(10)
            self.assertTrue(port.writes)
            self.assertFalse(worker.daemon)
            window.close()
            self.assertTrue(closing.wait(1))
            self.assertTrue(window.isVisible())
            self.assertTrue(worker.is_alive())
            count = len(port.writes)
            QTest.qWait(60)
            self.assertEqual(len(port.writes), count)
            release.set()
            limit = time.monotonic() + 1
            while window.isVisible() and time.monotonic() < limit:
                QTest.qWait(10)
            self.assertFalse(window.isVisible())
            self.assertFalse(worker.is_alive())
            self.assertFalse(port.is_open)
            self.assertFalse(window.timer.isActive())
        finally:
            release.set()
            worker.stop()
            worker.join(1)
            window.close()

    def test_stop_during_read_does_not_send_another_frame(self):
        reading = Event()
        release = Event()

        class SlowReader(ReaderStub):
            def read(self):
                reading.set()
                release.wait(3)
                return self.state

        manager = SerialManager(FakePort)
        manager.scan = lambda: [("COM_TEST", "测试")]
        manager.open("COM_TEST")
        port = manager._serial
        worker = Controller(SlowReader(), manager)
        worker.start()
        try:
            self.assertTrue(reading.wait(1))
            worker.stop()
            release.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(port.writes, [])
            self.assertFalse(port.is_open)
        finally:
            release.set()
            worker.stop()
            worker.join(1)

    def test_immediate_window_close_stops_real_backend(self):
        window = MainWindow()
        window.show()
        window.close()
        try:
            limit = time.monotonic() + 4
            while window.isVisible() and time.monotonic() < limit:
                QTest.qWait(20)
            self.assertFalse(window.isVisible())
            self.assertFalse(window.controller.is_alive())
        finally:
            window.controller.stop()
            window.controller.join(4)
            window.close()

    def test_application_quit_waits_beyond_previous_two_second_timeout(self):
        # 使用独立进程验证真正的事件循环退出及入口 finally 清理。
        project = Path(__file__).resolve().parents[1]
        source = r'''
import sys, time, threading
sys.path.insert(0, 'tests')
from PySide6.QtCore import QTimer
from controller import Controller
from serial_manager import SerialManager
from test_devices import FakePort, ReaderStub
import gui
import main
class SlowClosePort(FakePort):
    def close(self):
        time.sleep(2.2)
        super().close()
manager = SerialManager(SlowClosePort)
manager.scan = lambda: [('COM_TEST', 'test')]
manager.open('COM_TEST')
port = manager._serial
worker = Controller(ReaderStub(), manager)
original_window = gui.MainWindow
class TestWindow(original_window):
    def __init__(self):
        super().__init__(worker)
        QTimer.singleShot(50, self.request_quit)
    def request_quit(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
gui.MainWindow = TestWindow
assert main.main() == 0
assert not worker.is_alive()
assert not port.is_open
assert not any(t.name == 'XboxSerialWorker' for t in threading.enumerate())
print('QUIT_CLEANUP_OK')
'''
        result = subprocess.run([sys.executable, "-c", source], cwd=project,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"QUIT_CLEANUP_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
