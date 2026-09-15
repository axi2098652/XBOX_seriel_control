# Xbox 360 串口控制台

Windows 11 / Python 3 / PySide6 / pyserial 桌面程序。通过 Windows XInput 读取 Xbox 360 或其他兼容 XInput 的手柄，并通过 USB 转串口发送完整状态。

## 安装和启动

**日常使用：双击本目录的 `start.bat` 即可启动黑色界面，不需要输入命令。**
脚本自动定位项目虚拟环境，通过 `pythonw.exe` 启动，启动后不会保留命令行窗口。
如果虚拟环境缺失，脚本会提示；如果运行依赖缺失，程序会弹窗提示。

首次部署到尚未建立虚拟环境的电脑时，在本目录打开 PowerShell，推荐使用 64 位 Python 3.10 或更新版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

首次使用时，请先按上述命令创建虚拟环境并安装依赖，之后双击 `start.bat` 启动。首次安装依赖需要网络，不需要激活虚拟环境。

1. 连接 XInput 手柄。程序自动扫描索引 0～3，选中第一个可用手柄，连接期间持续使用该手柄。
2. 插入 USB 转串口模块，从列表选择 COM 端口；可手动刷新，也会每 2 秒自动扫描。
3. 点击 **Open Serial**。参数固定为 115200 8N1，打开后自动开始发送已连接手柄的状态。
4. 摇杆坐标区、LT/RT 进度条及 14 个按键指示实时刷新。
5. 发送监视器可切换 HEX、Text/UTF-8、Text/GBK。Text 使用 `errors="replace"`，不可读字符属于正常现象。
6. 点击 **Close Serial** 停止串口发送；关闭窗口时停止后续发送，等待正在进行的设备操作返回，关闭串口并释放计时资源，确认工作线程退出后窗口才关闭。退出等待期间界面仍响应并显示关闭提示。

## 运行约定

- 每个采样周期读取一次完整手柄快照，串口打开时一次 `write()` 提交完整 17 字节帧。即使 XInput 的包序号未变化，也会发送。
- 默认目标周期为 10 ms；修改 `controller.py` 中 `SEND_INTERVAL_MS` 可调整。采用单调时钟调度，超时后跳过积压周期，不突发补发旧状态。Windows 下并非硬实时。
- 工作线程在 Windows 上请求 1 ms 计时精度，退出时配对释放。Windows 11 在窗口最小化或完全被遮挡时不保证保持提高后的计时精度，联调时应保持窗口可见并实测周期。[Microsoft timeBeginPeriod 说明](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod)
- GUI 使用精确定时器，目标每 10 ms（100 Hz）读取后台快照并刷新；实际频率受系统负载影响。I/O、采样和串口扫描由独立线程处理。
- 手柄缺席或断开：清零显示并暂停发送；每 500 ms 探测重连。自动选择当前可用手柄，不提供多手柄同时发送。
- 串口不存在、占用、写超时、短写或拔出：显示错误原因；发送失败后关闭串口，排除故障后手动重新打开。即使没有手柄，周期性端口扫描仍检测串口消失。
- 监视器仅记录成功完整写入的帧，最多保留最近 500 帧。清空显示不重置累计发送计数。
- 上位机无 MCU 应答功能，写入成功不等于 MCU 收到。下位机应实现接收超时处理，具体见协议指南。
- 不使用死区过滤；保留原始摇杆、扳机数值。XInput 保留的按钮位 10/11 被清零。

## 文件结构

| 文件 | 职责 |
|---|---|
| `main.py` | 应用入口、依赖错误提示、退出清理 |
| `start.bat` | 双击启动，自动定位项目虚拟环境，无常驻控制台 |
| `xbox_input.py` | XInput DLL 加载、ABI 结构体、设备检测和重连 |
| `serial_manager.py` | 串口扫描、固定参数打开、关闭、完整写入与异常封装 |
| `protocol.py` | 数据类、按钮映射、打包/解析、CRC 和显示格式 |
| `controller.py` | 10 ms 后台调度、命令队列、快照和有界发送记录 |
| `gui.py` | 摇杆绘图、扳机与按钮显示、串口控制和发送监视器 |
| `requirements.txt` | Python 运行依赖 |
| `docs/MCU_Protocol_Guide.md` | STM32 交接文档，含帧格式、示例和可编译 C99 解析器 |
| `tests/` | 协议、模拟设备、pyserial 回环、GUI 和文档 C 代码验证 |

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试 GUI 使用 Qt offscreen 平台，不需要打开真实窗口；设备异常使用模拟对象，串口数据通路另外使用 pyserial `loop://` 回环验证。
文档中的 C 代码在检测到 GCC 时自动提取、以 C99 和警告视为错误编译，再执行帧解析及流同步恢复测试；未安装 GCC 时跳过该项。
编译产物保留在系统临时目录的 `xbox_c_test_*` 目录内供核验，测试不进行批量删除。

已验证的开发环境：Windows、Python 3.14.7、PySide6 6.11.2、pyserial 3.5。
本次验证结果：26 项测试全部通过，包含启动后立即关闭、读取过程中退出、等待串口清理、超过原 2 秒等待时限的应用退出场景；黑色界面的离屏布局检查通过。
`start.bat` 已从其他工作目录进行启动检查，确认窗口关闭后工作线程结束且 `pythonw` 进程退出。此前依赖一致性检查已通过。
模拟手柄和模拟串口的 1.2 秒节拍测量产生 120 帧，帧间隔平均 10.004 ms、中位数 10.041 ms、最大 11.432 ms。
以上数据为本机软件调度测量结果，不代表硬件线上延迟或长期时序保证。
项目已完成测试，可正常运行。

## 实现核验片段

完整状态打包见 `protocol.py`：

```python
PAYLOAD_STRUCT = struct.Struct("<hhhhBBH")
body = bytes([PAYLOAD_SIZE]) + payload
return HEADER + body + struct.pack("<H", crc16_modbus(body))
```

`<hhhhBBH` 明确规定四个 int16、两个 uint8、一个 uint16 使用小端排列，总共 12 字节；CRC 只覆盖 `LEN + payload`，追加 2 字节包头和 2 字节 CRC 后得到 17 字节。

采样发送条件见 `controller.py`：

```python
state = self.reader.read()
if state is not None and self.manager.is_open:  # 只发送本周期读取到的完整状态。
    frame = pack_frame(state)
    try:
        self.manager.send(frame)
```

条件直接约束“手柄状态有效且串口已打开”，随后统一打包并发送，断线时不重复发送旧状态。此片段截取了完整方法的条件与发送部分。

## 外部接口依据

- [Microsoft XINPUT_GAMEPAD](https://learn.microsoft.com/en-us/windows/win32/api/xinput/ns-xinput-xinput_gamepad)：轴值、按钮映射与保留位。
- [Microsoft XInputGetState](https://learn.microsoft.com/en-us/windows/win32/api/xinput/nf-xinput-xinputgetstate)：索引 0～3、返回码及连接检测。
- [pyserial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)：串口配置、写超时和写入长度。
