import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from controller import Snapshot
from gui import MainWindow
from protocol import XboxState, pack_frame


class ControllerStub:
    def __init__(self):
        self.current = Snapshot()
        self.frames = []
        self.commands = []
        self.alive = False

    def start(self):
        self.alive = True

    def stop(self):
        self.alive = False

    def is_alive(self):
        return self.alive

    def command(self, *args):
        self.commands.append(args)

    def snapshot(self):
        frames, self.frames = self.frames, []
        return self.current, frames


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.worker = ControllerStub()
        self.window = MainWindow(self.worker)
        self.window.show()

    def tearDown(self):
        self.window.close()
        QTest.qWait(80)

    def test_states_ports_buttons_and_modes(self):
        state = XboxState(-32768, 32767, 123, -456, 128, 255, 0x1101)
        frame = pack_frame(state)
        self.worker.current = Snapshot(state, 0, serial_open=True, port="COM3",
                                       ports=(("COM3", "测试串口"),), sent_count=1)
        self.worker.frames = [("12:34:56.789", frame)]
        self.window.refresh()
        self.assertEqual(self.window.sticks[0][0].x, -32768)
        self.assertEqual(self.window.triggers[1].value(), 255)
        self.assertEqual(self.window.buttons["A"].text(), "● A")
        self.assertEqual(self.window.buttons["B"].text(), "○ B")
        self.assertFalse(self.window.open_button.isEnabled())
        self.assertTrue(self.window.close_button.isEnabled())
        self.assertIn(frame.hex(" ").upper(), self.window.monitor.toPlainText())
        self.window.mode_combo.setCurrentText("Text")
        self.window.encoding_combo.setCurrentText("GBK")
        self.assertTrue(self.window.encoding_combo.isEnabled())
        self.assertEqual(self.window._history[0][1], frame)
        self.window.mode_combo.setCurrentText("HEX")
        self.assertIn(frame.hex(" ").upper(), self.window.monitor.toPlainText())
        self.window.clear_monitor()
        self.assertEqual(self.window.monitor.toPlainText(), "")

    def test_disconnect_errors_and_control_commands(self):
        self.worker.current = Snapshot(serial_error="打开失败：串口被占用", ports=(("COM3", "测试"),))
        self.window.refresh()
        self.assertIn("未连接", self.window.input_status.text())
        self.assertIn("被占用", self.window.error_label.text())
        self.assertTrue(self.window.open_button.isEnabled())
        self.window.open_button.click()
        self.assertIn(("open", "COM3"), self.worker.commands)
        self.assertEqual(self.window.serial_status.text(), "CLOSED")
        self.assertEqual(self.window.triggers[0].value(), 0)


if __name__ == "__main__":
    unittest.main()
