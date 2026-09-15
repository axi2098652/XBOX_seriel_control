# Xbox 手柄串口协议交接说明

## 1. 通信与发送行为

串口固定为 **115200 baud、8 数据位、无校验、1 停止位（8N1）**，关闭软硬件流控。
PC 经 USB 转串口模块输出二进制字节流。每个应用层帧为 17 字节，默认每 10 ms 采样并发送一帧。
帧内同时包含四个摇杆轴、两个扳机和全部已定义数字按键；状态没有变化也照常发送。
Windows 调度、串口驱动和设备延迟会造成抖动，10 ms 是目标周期，不是硬实时保证。

上位机只在手柄已连接且串口已打开时发送；手柄断开后停止发送，不发送零状态替代帧。
手柄重连探测间隔 500 ms，连接恢复后继续发送；串口错误后关闭端口，需要用户重新打开。
协议没有连接标志、序号、时间戳、应答或重传。成功写入 PC 串口并不证明 MCU 已收到。
下位机应独立检测接收超时，例如连续 100 ms 未收到合法帧时清零控制量并进入项目规定的失联状态；
此阈值是集成建议，需要按实际控制系统确定。CRC 错误帧不能刷新有效帧时间。

17 × 100 = 1700 字节/秒；按 8N1 的每字节 10 bit 计算，约 17000 bit/秒，约占 115200 的 14.8%。

## 2. 帧格式

偏移从 0 开始，所有 16 bit 数值均为 Little Endian（低字节在前）。

| Offset | 字段 | 类型 | 字节数 | 含义 |
|---:|---|---|---:|---|
| 0 | HEAD1 | uint8 | 1 | 固定 0xAA |
| 1 | HEAD2 | uint8 | 1 | 固定 0x55 |
| 2 | LEN | uint8 | 1 | 固定 0x0C，只计算 Xbox Payload |
| 3 | LX | int16 | 2 | 左摇杆 X，-32768～32767 |
| 5 | LY | int16 | 2 | 左摇杆 Y，-32768～32767 |
| 7 | RX | int16 | 2 | 右摇杆 X，-32768～32767 |
| 9 | RY | int16 | 2 | 右摇杆 Y，-32768～32767 |
| 11 | LT | uint8 | 1 | 左扳机，0～255 |
| 12 | RT | uint8 | 1 | 右扳机，0～255 |
| 13 | Buttons | uint16 | 2 | 数字按键位掩码 |
| 15 | CRC_L | uint8 | 1 | CRC 低 8 bit |
| 16 | CRC_H | uint8 | 1 | CRC 高 8 bit |

Payload 恰好 12 字节。摇杆负值表示左/下，正值表示右/上；0 为中心。
上位机传输原始轴值，不做死区过滤、归一化或 Y 轴取反，中心可能存在轻微漂移。
LT/RT 的 0 为未扣下，255 为满量程。

Little Endian 示例：`0x1234 → 34 12`；int16 的 `-1 → FF FF`，`-32768 → 00 80`。
原生 `XINPUT_GAMEPAD` 的内存字段顺序与本协议不同，不能直接将该结构体内存发送或按该顺序解析。

## 3. Buttons 位映射

置 1 表示按下，置 0 表示松开，允许多个位同时为 1。

| Bit | Mask | 按键 | XInput 定义 |
|---:|---|---|---|
| 0 | 0x0001 | D-Pad Up | XINPUT_GAMEPAD_DPAD_UP |
| 1 | 0x0002 | D-Pad Down | XINPUT_GAMEPAD_DPAD_DOWN |
| 2 | 0x0004 | D-Pad Left | XINPUT_GAMEPAD_DPAD_LEFT |
| 3 | 0x0008 | D-Pad Right | XINPUT_GAMEPAD_DPAD_RIGHT |
| 4 | 0x0010 | Start | XINPUT_GAMEPAD_START |
| 5 | 0x0020 | Back | XINPUT_GAMEPAD_BACK |
| 6 | 0x0040 | Left Thumb（左摇杆按下） | XINPUT_GAMEPAD_LEFT_THUMB |
| 7 | 0x0080 | Right Thumb（右摇杆按下） | XINPUT_GAMEPAD_RIGHT_THUMB |
| 8 | 0x0100 | LB | XINPUT_GAMEPAD_LEFT_SHOULDER |
| 9 | 0x0200 | RB | XINPUT_GAMEPAD_RIGHT_SHOULDER |
| 10 | 0x0400 | 保留，上位机清零 | 未定义 |
| 11 | 0x0800 | 保留，上位机清零 | 未定义 |
| 12 | 0x1000 | A | XINPUT_GAMEPAD_A |
| 13 | 0x2000 | B | XINPUT_GAMEPAD_B |
| 14 | 0x4000 | X | XINPUT_GAMEPAD_X |
| 15 | 0x8000 | Y | XINPUT_GAMEPAD_Y |

标准 XInputGetState 没有公开定义 Xbox Guide 中央键，本协议不为其虚构按键位。
按钮与坐标定义来源：[Microsoft XINPUT_GAMEPAD 文档](https://learn.microsoft.com/en-us/windows/win32/api/xinput/ns-xinput-xinput_gamepad)。
连接状态读取依据：[Microsoft XInputGetState 文档](https://learn.microsoft.com/en-us/windows/win32/api/xinput/nf-xinput-xinputgetstate)。

## 4. CRC-16/MODBUS

- 宽度：16 bit。
- 初始值：0xFFFF。
- 正向多项式：0x8005；下面右移算法使用反射多项式 **0xA001**。
- 输入/输出反射：均为 true；右移逐位实现不需要额外进行反转。
- 最终异或值：0x0000。
- 计算范围：**Byte2～Byte14，共 13 字节，即 LEN + Payload**。
- 不包含 AA 55，也不包含 CRC 本身。
- 存储顺序：低字节 CRC_L 在前，高字节 CRC_H 在后。
- 自检向量：ASCII `123456789`（不带结束符）的 CRC 为 0x4B37。

每输入一个字节，先与 CRC 低 8 bit 异或，再执行 8 次：最低位为 1 则右移并异或 0xA001，否则只右移。

## 5. 完整数据帧示例

```text
AA 55 0C 00 80 FF 7F FF FF 39 30 80 FF 01 11 77 2E
```

| 字段 | 线上字节 | 解析结果 |
|---|---|---|
| 包头、长度 | AA 55 0C | Payload 12 字节 |
| LX | 00 80 | -32768 |
| LY | FF 7F | 32767 |
| RX | FF FF | -1 |
| RY | 39 30 | 12345 |
| LT | 80 | 128 |
| RT | FF | 255 |
| Buttons | 01 11 | 0x1101，D-Pad Up + LB + A |
| CRC | 77 2E | 0x2E77 |

CRC 输入为 `0C 00 80 FF 7F FF FF 39 30 80 FF 01 11`。
全部状态为零时，合法帧为 `AA 55 0C 00 00 00 00 00 00 00 00 00 00 00 00 12 27`。

## 6. C99 解析与流式接收示例

以下代码只依赖 C 标准库，可保存为 `.c` 编译。逐字节拼接，避免未对齐访问和结构体填充问题。
`xbox_parse_frame()` 校验成功后才更新输出，返回 1；失败返回 0 并保留原输出。
`xbox_rx_byte()` 可连续接收任意长度分片，返回 1 时得到一个完整、通过校验的新快照。

```c
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define XBOX_FRAME_SIZE 17u

typedef struct {
    int16_t lx, ly, rx, ry;
    uint8_t lt, rt;
    uint16_t buttons;
} XboxState;

typedef struct {
    uint8_t data[XBOX_FRAME_SIZE];
    size_t used;
} XboxReceiver;

static uint16_t read_u16_le(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static int16_t read_i16_le(const uint8_t *p)
{
    uint16_t value = read_u16_le(p);
    if (value >= 0x8000u) { /* 显式还原二进制补码，避免越界有符号转换。 */
        return (int16_t)((int32_t)value - 65536);
    }
    return (int16_t)value;
}

static uint16_t crc16_modbus(const uint8_t *data, size_t length)
{
    uint16_t crc = 0xFFFFu;
    for (size_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (unsigned int bit = 0; bit < 8u; ++bit) {
            if (crc & 1u) { /* 使用反射多项式执行右移算法。 */
                crc = (uint16_t)((crc >> 1) ^ 0xA001u);
            } else {
                crc = (uint16_t)(crc >> 1);
            }
        }
    }
    return crc;
}

int xbox_parse_frame(const uint8_t *frame, size_t length, XboxState *out)
{
    if (frame == NULL || out == NULL || length != XBOX_FRAME_SIZE) {
        return 0;
    }
    if (frame[0] != 0xAAu || frame[1] != 0x55u || frame[2] != 0x0Cu) {
        return 0;
    }
    if (crc16_modbus(frame + 2, 13) != read_u16_le(frame + 15)) {
        return 0;
    }
    XboxState next;
    next.lx = read_i16_le(frame + 3);
    next.ly = read_i16_le(frame + 5);
    next.rx = read_i16_le(frame + 7);
    next.ry = read_i16_le(frame + 9);
    next.lt = frame[11];
    next.rt = frame[12];
    next.buttons = read_u16_le(frame + 13);
    *out = next;
    return 1;
}

void xbox_rx_init(XboxReceiver *receiver)
{
    receiver->used = 0;
}

int xbox_rx_byte(XboxReceiver *receiver, uint8_t byte, XboxState *out)
{
    receiver->data[receiver->used++] = byte;
    if (receiver->used < XBOX_FRAME_SIZE) { /* 尚未收满一个候选帧。 */
        return 0;
    }
    if (xbox_parse_frame(receiver->data, XBOX_FRAME_SIZE, out)) {
        receiver->used = 0;
        return 1;
    }
    /* 失败后仅丢弃最旧的一个字节，保留可能已进入缓冲区的新帧头。 */
    memmove(receiver->data, receiver->data + 1, XBOX_FRAME_SIZE - 1);
    receiver->used = XBOX_FRAME_SIZE - 1;
    return 0;
}
```

使用方式：创建 `XboxReceiver receiver; XboxState state;`，启动时调用 `xbox_rx_init(&receiver)`。
将每个接收到的字节交给 `xbox_rx_byte(&receiver, byte, &state)`，返回 1 时更新控制层状态和有效帧时间。
例如 `if (state.buttons & 0x1000u) { /* A 已按下。 */ }`。
该示例未包含 HAL 初始化、DMA 启停或具体执行器控制，需要集成到实际 STM32 工程。

## 7. 接收状态机和 STM32 集成建议

可采用如下状态机：等待 AA → 等待 55 → 验证 LEN=0C → 收集 12 字节 Payload → 收集 2 字节 CRC → 校验发布。

1. 等待 55 时再次收到 AA，应保持等待 55，正确处理 `AA AA 55`。
2. Payload/CRC 内可能自然出现 `AA 55`、0x00、换行等字节，不得据此重启接收或按文本分行。
3. LEN 不等于 0x0C 时拒绝，不按不可信长度分配缓冲区。
4. CRC 失败时保留候选帧中后续可能的包头，避免简单清空 17 字节导致下一合法帧被吞掉。
   上面的 C 实现用固定 17 字节滑动窗口完成同步恢复，适合当前固定帧长度协议。
5. UART DMA/空闲中断返回的数据块可能包含半帧、一帧或多帧，必须按字节流持续解析，不能假设一次回调等于一帧。
6. 接收器使用前必须初始化；同一接收器只由一个执行上下文调用。跨中断/任务发布完整状态时使用临界区或消息队列。
7. UART 溢出或 DMA 丢字节后允许重新同步；连续未收到 CRC 合法帧时按上面的超时策略处理，恢复后用最新完整帧更新状态。
8. 不向 UART 添加文本、结束符或额外的 CR/LF。GUI HEX/Text 只改变显示，同一状态的发送 bytes 完全相同。

## 8. 联调核验

- 用第 5 节示例确认字段值、按钮组合和 CRC。
- 人为修改任一位，接收器应拒绝该帧。
- 输入噪声、连续 AA、残帧和多帧粘连，随后输入合法帧，应恢复同步。
- 分别将 LX/LY/RX/RY 移到两端，确认符号及方向，再逐个检查 14 个按键与 LT/RT。
- 拔下手柄，确认下位机在接收超时后处理失联；重新连接，确认合法帧恢复。
- 用逻辑分析仪或串口接收端实测帧长和周期；上位机成功写入计数不能替代线上测量。
