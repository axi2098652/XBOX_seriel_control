import ctypes
import time
import unittest

import serial

from controller import Controller, MONITOR_MAX_FRAMES
from protocol import XboxState, pack_frame
from serial_manager import SerialManager, SerialManagerError
from xbox_input import XInputReader, XINPUT_GAMEPAD, XINPUT_STATE


class FakePort:
    def __init__(self, **kwargs):
        self.settings = kwargs
        self.port = kwargs["port"]
        self.is_open = True
        self.writes = []
        self.failure = None
        self.short = False

    def write(self, frame):
        if self.failure:
            raise self.failure
        self.writes.append(frame)
        if self.short:
            return len(frame) - 1
        return len(frame)

    def close(self):
        self.is_open = False


class FakeAPI:
    def __init__(self):
        self.connected = {2}
        self.result = 1167

    def __call__(self, index, pointer):
        if index not in self.connected:
            return self.result
        native = ctypes.cast(pointer, ctypes.POINTER(XINPUT_STATE)).contents
        native.dwPacketNumber = 1
        native.Gamepad = XINPUT_GAMEPAD(0xFFFF, 128, 255, -32768, 32767, -1, 12345)
        return 0


class ReaderStub:
    def __init__(self):
        self.state = XboxState(lx=123, buttons=0x1000)
        self.index = 0
        self.error = ""

    def read(self):
        return self.state


class DeviceTests(unittest.TestCase):
    def test_xinput_layout(self):
        self.assertEqual(ctypes.sizeof(XINPUT_GAMEPAD), 12)
        self.assertEqual(ctypes.sizeof(XINPUT_STATE), 16)
        self.assertEqual(XINPUT_STATE.Gamepad.offset, 4)
        self.assertEqual(XINPUT_GAMEPAD.sThumbLX.offset, 4)

    def test_xinput_connect_disconnect_reconnect(self):
        api = FakeAPI()
        reader = XInputReader(api)
        self.assertEqual(reader.read(), XboxState(-32768, 32767, -1, 12345, 128, 255, 0xF3FF))
        self.assertEqual(reader.index, 2)
        api.connected.clear()
        self.assertIsNone(reader.read())
        self.assertIsNone(reader.index)
        api.connected.add(1)
        reader._next_probe = 0
        self.assertIsNotNone(reader.read())
        self.assertEqual(reader.index, 1)

    def test_xinput_error_visible(self):
        api = FakeAPI()
        api.connected.clear()
        api.result = 5
        reader = XInputReader(api)
        self.assertIsNone(reader.read())
        self.assertIn("5", reader.error)

    def test_serial_fixed_settings_and_complete_frame(self):
        manager = SerialManager(FakePort)
        manager.open("COM_TEST")
        port = manager._serial
        self.assertEqual((port.settings["baudrate"], port.settings["bytesize"],
                          port.settings["parity"], port.settings["stopbits"]), (115200, 8, "N", 1))
        self.assertEqual(port.settings["write_timeout"], 0.05)
        frame = pack_frame(XboxState())
        manager.send(frame)
        self.assertEqual(port.writes, [frame])
        manager.close()
        self.assertFalse(manager.is_open)

    def test_open_failures(self):
        for error in (FileNotFoundError("不存在"), PermissionError("被占用")):
            def fail(**kwargs):
                raise error
            manager = SerialManager(fail)
            with self.assertRaises(SerialManagerError):
                manager.open("COM_TEST")
            self.assertFalse(manager.is_open)

    def test_short_write_timeout_and_unplug_close_port(self):
        for failure in (None, serial.SerialTimeoutException("超时"), OSError("已拔出")):
            manager = SerialManager(FakePort)
            manager.open("COM_TEST")
            port = manager._serial
            port.short = failure is None
            port.failure = failure
            with self.assertRaises(SerialManagerError):
                manager.send(pack_frame(XboxState()))
            self.assertFalse(manager.is_open)
            self.assertFalse(port.is_open)

    def test_pyserial_loopback(self):
        # serial_for_url 使用 url 参数；通过适配器保持产品端口接口不变。
        manager = SerialManager(lambda port, **kwargs: serial.serial_for_url(port, **kwargs))
        manager.open("loop://")
        frame = pack_frame(XboxState(lx=-200, rt=255))
        try:
            manager.send(frame)
            self.assertEqual(manager._serial.read(17), frame)
        finally:
            manager.close()

    def test_disconnect_never_sends_stale_state(self):
        reader = ReaderStub()
        manager = SerialManager(FakePort)
        manager.open("COM_TEST")
        port = manager._serial
        controller = Controller(reader, manager)
        controller._sample()
        reader.state = None
        controller._sample()
        snapshot, frames = controller.snapshot()
        self.assertEqual(snapshot.state, XboxState())
        self.assertIsNone(snapshot.index)
        self.assertEqual(len(port.writes), 1)
        reader.state = XboxState(lt=123)
        controller._sample()
        self.assertEqual(port.writes[-1], pack_frame(reader.state))

    def test_removed_port_detected_without_controller(self):
        reader = ReaderStub()
        reader.state = None
        manager = SerialManager(FakePort)
        manager.open("COM_TEST")
        manager.scan = lambda: []
        controller = Controller(reader, manager)
        controller._scan()
        controller._sample()
        snapshot, _ = controller.snapshot()
        self.assertFalse(snapshot.serial_open)
        self.assertIn("消失", snapshot.serial_error)

    def test_monitor_buffer_is_bounded(self):
        manager = SerialManager(FakePort)
        manager.open("COM_TEST")
        controller = Controller(ReaderStub(), manager)
        for _ in range(MONITOR_MAX_FRAMES + 12):
            controller._sample()
        snapshot, frames = controller.snapshot()
        self.assertEqual(len(frames), MONITOR_MAX_FRAMES)
        self.assertEqual(snapshot.sent_count, MONITOR_MAX_FRAMES + 12)

    def test_worker_commands_periodic_send_and_shutdown(self):
        manager = SerialManager(FakePort)
        manager.scan = lambda: [("COM_TEST", "测试串口")]
        controller = Controller(ReaderStub(), manager)
        controller.start()
        try:
            controller.command("open", "COM_TEST")
            time.sleep(0.25)
            snapshot, frames = controller.snapshot()
            self.assertTrue(snapshot.serial_open)
            self.assertGreaterEqual(snapshot.sent_count, 5)
            self.assertTrue(all(len(frame) == 17 for _, frame in frames))
            controller.command("close")
            limit = time.monotonic() + 1
            while time.monotonic() < limit:
                snapshot, _ = controller.snapshot()
                if not snapshot.serial_open:
                    break
                time.sleep(0.01)
            self.assertFalse(snapshot.serial_open)
        finally:
            controller.stop()
            controller.join(1)
        self.assertFalse(controller.is_alive())
        self.assertFalse(manager.is_open)


if __name__ == "__main__":
    unittest.main()
