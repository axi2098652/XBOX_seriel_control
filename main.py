"""双击 start.bat 启动，也可直接运行本文件。"""

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from gui import MainWindow
    except ImportError as exc:
        message = f"缺少运行依赖：{exc}\n请按 README.md 的安装说明修复项目虚拟环境。"
        if sys.platform == "win32":  # pythonw 没有控制台，使用弹窗显示启动失败原因。
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Xbox 串口控制台启动失败", 0x10)
        elif sys.stderr is not None:
            print(message, file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName("Xbox Serial Control")
    window = MainWindow()
    app.aboutToQuit.connect(window.controller.stop)
    window.show()
    try:
        return app.exec()
    finally:
        window.controller.stop()
        window.controller.join()  # 等待串口及计时资源清理完成，线程退出后才结束进程。


if __name__ == "__main__":
    raise SystemExit(main())
