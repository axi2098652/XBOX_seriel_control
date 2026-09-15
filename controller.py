"""调度采样和发送；GUI 只读取快照，避免串口等待阻塞界面。"""

from collections import deque
import ctypes
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, SimpleQueue
from threading import Event, Lock, Thread
import sys
import time

from protocol import XboxState, pack_frame
from serial_manager import SerialManager, SerialManagerError
from xbox_input import XInputReader

SEND_INTERVAL_MS = 10
PORT_SCAN_INTERVAL_S = 2.0
MONITOR_MAX_FRAMES = 500


@dataclass(frozen=True)
class Snapshot:
    state: XboxState = XboxState()
    index: int | None = None
    input_error: str = ""
    serial_open: bool = False
    port: str = ""
    serial_error: str = ""
    ports: tuple = ()
    sent_count: int = 0
    timing_error: str = ""


class Controller(Thread):
    def __init__(self, reader=None, manager=None):
        super().__init__(name="XboxSerialWorker", daemon=False)
        self.reader = reader
        self.manager = manager
        self._stop_event = Event()
        self._wake = Event()
        self._commands = SimpleQueue()
        self._lock = Lock()
        self._snapshot = Snapshot()
        self._frames = deque(maxlen=MONITOR_MAX_FRAMES)
        self._ports = ()
        self._serial_error = ""
        self._sent_count = 0
        self._timing_error = ""

    def command(self, action: str, port: str = ""):
        self._commands.put((action, port))
        self._wake.set()

    def stop(self):
        self._stop_event.set()
        self._wake.set()

    def snapshot(self):
        with self._lock:
            snapshot = self._snapshot
            frames = list(self._frames)
            self._frames.clear()
        return snapshot, frames

    def _scan(self):
        try:
            self._ports = tuple(self.manager.scan())
            if self.manager.is_open and self.manager.port not in dict(self._ports):
                port = self.manager.port
                self.manager.close()
                self._serial_error = f"{port} 已从可用串口列表消失，请检查连接后重新打开"
        except SerialManagerError as exc:
            self._serial_error = str(exc)

    def _handle_commands(self):
        while not self._stop_event.is_set():
            try:
                action, port = self._commands.get_nowait()
            except Empty:
                return
            try:
                if action == "open":
                    self.manager.open(port)
                    self._serial_error = ""
                elif action == "close":
                    self.manager.close()
                    self._serial_error = ""
                elif action == "scan":
                    self._scan()
            except SerialManagerError as exc:
                self._serial_error = str(exc)

    def _sample(self):
        state = self.reader.read()
        if self._stop_event.is_set():  # 读取期间收到退出请求时，不再提交新数据帧。
            return
        if state is not None and self.manager.is_open:  # 只发送本周期读取到的完整状态。
            frame = pack_frame(state)
            try:
                self.manager.send(frame)
                self._sent_count += 1
                with self._lock:
                    self._frames.append((datetime.now().strftime("%H:%M:%S.%f")[:-3], frame))
            except SerialManagerError as exc:
                self._serial_error = str(exc)
        with self._lock:
            self._snapshot = Snapshot(
                state=state if state is not None else XboxState(),
                index=self.reader.index if state is not None else None,
                input_error=self.reader.error,
                serial_open=self.manager.is_open, port=self.manager.port,
                serial_error=self._serial_error, ports=self._ports,
                sent_count=self._sent_count,
                timing_error=self._timing_error,
            )

    def run(self):
        timer_library = None
        if sys.platform == "win32":  # 请求 1 ms 计时精度，避免默认系统时钟拉长 10 ms 等待。
            try:
                library = ctypes.WinDLL("winmm.dll")
                library.timeBeginPeriod.argtypes = [ctypes.c_uint]
                library.timeBeginPeriod.restype = ctypes.c_uint
                library.timeEndPeriod.argtypes = [ctypes.c_uint]
                library.timeEndPeriod.restype = ctypes.c_uint
                if library.timeBeginPeriod(1) != 0:
                    raise OSError("timeBeginPeriod(1) 失败")
                timer_library = library
            except (OSError, AttributeError) as exc:
                self._timing_error = f"无法提高计时精度，发送间隔可能增大：{exc}"
        try:
            self.reader = self.reader or XInputReader()
            self.manager = self.manager or SerialManager()
            deadline = time.monotonic()
            next_scan = deadline
            interval = SEND_INTERVAL_MS / 1000.0
            while not self._stop_event.is_set():
                self._wake.clear()
                self._handle_commands()
                if self._stop_event.is_set():  # 关闭过程中不再开始扫描或采样。
                    break
                now = time.monotonic()
                if now >= next_scan:
                    self._scan()
                    next_scan = time.monotonic() + PORT_SCAN_INTERVAL_S
                if self._stop_event.is_set():  # 扫描返回后优先响应退出请求。
                    break
                if now >= deadline:
                    self._sample()
                    deadline += interval
                    if deadline <= time.monotonic():  # 超时后跳过积压周期，避免突发补发旧状态。
                        deadline = time.monotonic() + interval
                self._wake.wait(max(0.0, deadline - time.monotonic()))
        finally:
            try:
                if self.manager is not None:  # 初始化中途失败时也完成已创建资源的清理。
                    self.manager.close()
            except SerialManagerError:
                pass
            finally:
                if timer_library is not None:  # 与成功的 timeBeginPeriod 调用配对，恢复计时资源。
                    timer_library.timeEndPeriod(1)
