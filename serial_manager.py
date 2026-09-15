"""串口对象仅由后台工作线程持有。"""

import serial
from serial.tools import list_ports

BAUD_RATE = 115200
WRITE_TIMEOUT_S = 0.05


class SerialManagerError(RuntimeError):
    pass


class SerialManager:
    def __init__(self, factory=serial.Serial):
        self._factory = factory
        self._serial = None

    @staticmethod
    def scan() -> list[tuple[str, str]]:
        try:
            return [(port.device, port.description) for port in sorted(list_ports.comports())]
        except (OSError, serial.SerialException) as exc:
            raise SerialManagerError(f"串口扫描失败：{exc}") from exc

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def port(self) -> str:
        return self._serial.port if self._serial is not None else ""

    def open(self, port: str):
        if not port:
            raise SerialManagerError("请选择串口")
        self.close()
        try:
            self._serial = self._factory(
                port=port, baudrate=BAUD_RATE, bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                timeout=0, write_timeout=WRITE_TIMEOUT_S,
                xonxoff=False, rtscts=False, dsrdtr=False,
            )
        except (OSError, ValueError, serial.SerialException) as exc:
            self._serial = None
            raise SerialManagerError(f"打开 {port} 失败：{exc}") from exc

    def close(self):
        port, self._serial = self._serial, None
        if port is not None:
            try:
                port.close()
            except (OSError, serial.SerialException) as exc:
                raise SerialManagerError(f"关闭串口失败：{exc}") from exc

    def send(self, frame: bytes):
        if not self.is_open:
            raise SerialManagerError("串口未打开")
        try:
            written = self._serial.write(frame)
            if written != len(frame):  # 短写意味着帧不完整，立即停止后续发送。
                raise SerialManagerError(f"发送不完整：{written}/{len(frame)} 字节")
        except (OSError, serial.SerialException, SerialManagerError) as exc:
            close_error = ""
            try:
                self.close()
            except SerialManagerError as cleanup:
                close_error = f"；{cleanup}"
            raise SerialManagerError(f"串口发送失败：{exc}{close_error}") from exc
