"""通过 Windows XInputGetState 读取快照，不解析 USB 原始包。"""

import ctypes
import sys
import time

from protocol import DEFINED_BUTTON_MASK, XboxState

ERROR_DEVICE_NOT_CONNECTED = 1167
RECONNECT_INTERVAL_S = 0.5


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_uint16),
        ("bLeftTrigger", ctypes.c_uint8),
        ("bRightTrigger", ctypes.c_uint8),
        ("sThumbLX", ctypes.c_int16), ("sThumbLY", ctypes.c_int16),
        ("sThumbRX", ctypes.c_int16), ("sThumbRY", ctypes.c_int16),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", XINPUT_GAMEPAD)]


class XInputReader:
    def __init__(self, get_state=None):
        self.index = None
        self.error = ""
        self._next_probe = 0.0
        self._get_state = get_state
        self._dll = None
        if get_state is not None:  # 允许测试注入模拟 XInput API。
            return
        if sys.platform != "win32":
            self.error = "XInput 仅支持 Windows"
            return
        errors = []
        for name in ("xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll"):
            try:
                self._dll = ctypes.WinDLL(name)
                self._get_state = self._dll.XInputGetState
                self._get_state.argtypes = [ctypes.c_uint32, ctypes.POINTER(XINPUT_STATE)]
                self._get_state.restype = ctypes.c_uint32
                break
            except (OSError, AttributeError) as exc:
                errors.append(f"{name}: {exc}")
        if self._get_state is None:
            self.error = "无法加载 XInput：" + "; ".join(errors)

    def read(self) -> XboxState | None:
        if self._get_state is None:
            return None
        now = time.monotonic()
        if self.index is None and now < self._next_probe:  # 无连接时降低探测频率。
            return None
        indices = [self.index] if self.index is not None else range(4)
        self.error = ""
        for index in indices:
            native = XINPUT_STATE()
            try:
                result = self._get_state(index, ctypes.byref(native))
            except OSError as exc:
                self.error = f"XInput 读取失败：{exc}"
                continue
            if result == 0:
                self.index = index
                gamepad = native.Gamepad
                self.error = ""
                return XboxState(
                    gamepad.sThumbLX, gamepad.sThumbLY,
                    gamepad.sThumbRX, gamepad.sThumbRY,
                    gamepad.bLeftTrigger, gamepad.bRightTrigger,
                    gamepad.wButtons & DEFINED_BUTTON_MASK,
                )
            if result != ERROR_DEVICE_NOT_CONNECTED:
                self.error = f"XInput 错误码：{result}"
        self.index = None
        self._next_probe = now + RECONNECT_INTERVAL_S
        return None
