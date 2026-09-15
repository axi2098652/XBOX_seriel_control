"""PySide6 界面：设备操作通过命令队列交给后台线程。"""

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from controller import Controller, MONITOR_MAX_FRAMES, SEND_INTERVAL_MS
from protocol import BUTTONS, format_frame

GUI_REFRESH_MS = 10


class StickWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.x = self.y = 0
        self.setMinimumSize(160, 160)

    def set_position(self, x: int, y: int):
        self.x, self.y = x, y
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) / 2 - 20
        painter.setPen(QPen(QColor("#4b5563"), 1))
        painter.setBrush(QColor("#101010"))
        painter.drawRect(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2))
        painter.drawEllipse(center, radius, radius)
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))
        x = self.x / (32768 if self.x < 0 else 32767)
        y = self.y / (32768 if self.y < 0 else 32767)
        point = QPointF(center.x() + x * radius, center.y() - y * radius)
        painter.setPen(QPen(QColor("#45d6cb"), 2))
        painter.drawLine(center, point)
        painter.setBrush(QColor("#45d6cb"))
        painter.drawEllipse(point, 7, 7)


class MainWindow(QMainWindow):
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller or Controller()
        self._history = deque(maxlen=MONITOR_MAX_FRAMES)
        self._ports = None
        self._closing = False
        self.setWindowTitle("Xbox 360 · 串口控制台")
        self.resize(1020, 860)
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(GUI_REFRESH_MS)
        self.controller.start()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("Xbox 360 串口控制台")
        title.setFont(QFont("Microsoft YaHei UI", 20, QFont.Weight.Bold))
        layout.addWidget(title)
        self.input_status = QLabel("正在检测 XInput 手柄…")
        layout.addWidget(self.input_status)

        serial_box = QGroupBox("串口连接")
        serial_layout = QGridLayout(serial_box)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        self.scan_button = QPushButton("刷新串口")
        self.scan_button.clicked.connect(lambda: self.controller.command("scan"))
        self.open_button = QPushButton("Open Serial")
        self.open_button.clicked.connect(self.open_serial)
        self.close_button = QPushButton("Close Serial")
        self.close_button.clicked.connect(self.close_serial)
        self.close_button.setEnabled(False)
        self.serial_status = QLabel("CLOSED")
        serial_layout.addWidget(self.port_combo, 0, 0)
        serial_layout.addWidget(self.scan_button, 0, 1)
        serial_layout.addWidget(self.open_button, 0, 2)
        serial_layout.addWidget(self.close_button, 0, 3)
        serial_layout.addWidget(self.serial_status, 0, 4)
        serial_layout.addWidget(QLabel(f"115200 baud  ·  8 data bits  ·  None parity  ·  1 stop bit  |  发送周期 {SEND_INTERVAL_MS} ms"), 1, 0, 1, 5)
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #ff8a80;")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        serial_layout.addWidget(self.error_label, 2, 0, 1, 5)
        layout.addWidget(serial_box)

        controls = QHBoxLayout()
        self.sticks = []
        for name in ("左摇杆 · LX / LY", "右摇杆 · RX / RY"):
            box = QGroupBox(name)
            column = QVBoxLayout(box)
            stick = StickWidget()
            value = QLabel("X: 0    Y: 0")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(stick)
            column.addWidget(value)
            controls.addWidget(box, 1)
            self.sticks.append((stick, value))
        triggers_box = QGroupBox("扳机 · 原始值")
        triggers_layout = QVBoxLayout(triggers_box)
        self.triggers = []
        for name in ("LT", "RT"):
            triggers_layout.addWidget(QLabel(name))
            bar = QProgressBar()
            bar.setRange(0, 255)
            bar.setValue(0)
            bar.setFormat("%v / 255")
            triggers_layout.addWidget(bar)
            self.triggers.append(bar)
        triggers_layout.addStretch()
        controls.addWidget(triggers_box, 1)
        layout.addLayout(controls)

        button_box = QGroupBox("数字按键")
        button_layout = QGridLayout(button_box)
        self.buttons = {}
        names = ("A", "B", "X", "Y", "LB", "RB", "Back", "Start",
                 "Left Thumb", "Right Thumb", "D-Pad Up", "D-Pad Down", "D-Pad Left", "D-Pad Right")
        for i, name in enumerate(names):
            label = QLabel("○ " + name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(30)
            button_layout.addWidget(label, i // 7, i % 7)
            self.buttons[name] = label
        layout.addWidget(button_box)

        monitor_box = QGroupBox(f"发送监视器 · 最近 {MONITOR_MAX_FRAMES} 帧")
        monitor_layout = QVBoxLayout(monitor_box)
        toolbar = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["HEX", "Text"])
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["UTF-8", "GBK"])
        self.encoding_combo.setEnabled(False)
        self.mode_combo.currentTextChanged.connect(self.display_changed)
        self.encoding_combo.currentTextChanged.connect(self.render_history)
        clear_button = QPushButton("清空显示")
        clear_button.clicked.connect(self.clear_monitor)
        self.count_label = QLabel("成功发送 0 帧")
        toolbar.addWidget(self.mode_combo)
        toolbar.addWidget(self.encoding_combo)
        toolbar.addWidget(clear_button)
        toolbar.addStretch()
        toolbar.addWidget(self.count_label)
        monitor_layout.addLayout(toolbar)
        self.monitor = QPlainTextEdit()
        self.monitor.setReadOnly(True)
        self.monitor.setFont(QFont("Consolas", 10))
        self.monitor.setMinimumHeight(160)
        monitor_layout.addWidget(self.monitor)
        monitor_layout.addWidget(QLabel("仅记录成功写入串口的帧；Text 使用替换策略解码，可能出现不可读字符。"))
        layout.addWidget(monitor_box, 1)
        self.statusBar().showMessage("手柄未连接时暂停发送；串口打开后自动发送当前手柄状态。")
        self.setStyleSheet("""
            QWidget { background: #000000; color: #eeeeee; }
            QGroupBox { font-weight: bold; border: 1px solid #383838;
                        border-radius: 7px; margin-top: 12px; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; }
            QPushButton { padding: 7px 12px; background: #1c1c1c;
                          border: 1px solid #555555; border-radius: 4px; }
            QPushButton:hover { background: #303030; }
            QPushButton:pressed { background: #14554f; }
            QPushButton:disabled, QComboBox:disabled { color: #777777; border-color: #303030; }
            QComboBox { padding: 6px; background: #161616; border: 1px solid #555555; }
            QComboBox QAbstractItemView { background: #161616; color: #eeeeee;
                                         selection-background-color: #14554f; }
            QProgressBar { min-height: 24px; text-align: center; background: #101010;
                           border: 1px solid #555555; }
            QProgressBar::chunk { background: #17685f; }
            QPlainTextEdit { background: #000000; color: #eeeeee; border: 1px solid #383838; }
            QStatusBar { background: #000000; color: #bbbbbb; }
        """)

    def open_serial(self):
        port = self.port_combo.currentData()
        if port:
            self.controller.command("open", port)

    def close_serial(self):
        self.controller.command("close")

    def refresh(self):
        if self._closing:  # 等后台线程退出后再销毁窗口，避免关闭时阻塞界面。
            if not self.controller.is_alive():
                self.timer.stop()
                self.close()
            return
        snapshot, frames = self.controller.snapshot()
        if snapshot.index is None:
            self.input_status.setText(snapshot.input_error or "● 手柄未连接 · 已暂停发送")
            self.input_status.setStyleSheet("color: #f0c66b;")
        else:
            self.input_status.setText(f"● XInput 手柄 {snapshot.index + 1} 已连接（索引 {snapshot.index}）")
            self.input_status.setStyleSheet("color: #45d6cb;")
        if self._ports != snapshot.ports:
            selected = self.port_combo.currentData()
            self.port_combo.clear()
            for port, description in snapshot.ports:
                self.port_combo.addItem(f"{port} · {description}", port)
            index = self.port_combo.findData(selected)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            self._ports = snapshot.ports
        self.port_combo.setEnabled(not snapshot.serial_open)
        self.open_button.setEnabled(not snapshot.serial_open and self.port_combo.currentData() is not None)
        self.close_button.setEnabled(snapshot.serial_open)
        self.serial_status.setText(f"OPEN · {snapshot.port}" if snapshot.serial_open else "CLOSED")
        self.serial_status.setStyleSheet("color: #45d6cb;" if snapshot.serial_open else "color: #aaaaaa;")
        self.error_label.setText("\n".join(message for message in
                                          (snapshot.serial_error, snapshot.timing_error) if message))
        state = snapshot.state
        for (stick, label), x, y in zip(self.sticks, (state.lx, state.rx), (state.ly, state.ry)):
            stick.set_position(x, y)
            label.setText(f"X: {x}    Y: {y}")
        self.triggers[0].setValue(state.lt)
        self.triggers[1].setValue(state.rt)
        for name, label in self.buttons.items():
            if state.buttons & BUTTONS[name]:
                label.setText("● " + name)
                label.setStyleSheet("background: #17685f; color: white; border-radius: 5px;")
            else:
                label.setText("○ " + name)
                label.setStyleSheet("background: #1c1c1c; color: #bbbbbb; border-radius: 5px;")
        self.count_label.setText(f"成功发送 {snapshot.sent_count} 帧 / {snapshot.sent_count * 17} 字节")
        if frames:
            self._history.extend(frames)
            self.render_history()

    def display_changed(self, mode):
        self.encoding_combo.setEnabled(mode == "Text")
        self.render_history()

    def render_history(self, *_):
        scrollbar = self.monitor.verticalScrollBar()
        position = scrollbar.value()
        at_bottom = position >= scrollbar.maximum()
        self.monitor.setPlainText("\n".join(
            f"[{timestamp}] {format_frame(frame, self.mode_combo.currentText(), self.encoding_combo.currentText())}"
            for timestamp, frame in self._history
        ))
        if at_bottom:
            self.monitor.moveCursor(QTextCursor.MoveOperation.End)
        else:
            scrollbar.setValue(position)

    def clear_monitor(self):
        self._history.clear()
        self.monitor.clear()

    def closeEvent(self, event):
        if self.controller.is_alive():
            self._closing = True
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("正在停止发送并关闭串口…")
            self.controller.stop()
            event.ignore()
        else:
            self.timer.stop()
            event.accept()
