"""不依赖硬件和 GUI 的 17 字节串口协议。"""

from dataclasses import dataclass
import struct

HEADER = b"\xAA\x55"
PAYLOAD_STRUCT = struct.Struct("<hhhhBBH")
PAYLOAD_SIZE = 12
FRAME_SIZE = 17
BUTTONS = {
    "D-Pad Up": 0x0001, "D-Pad Down": 0x0002,
    "D-Pad Left": 0x0004, "D-Pad Right": 0x0008,
    "Start": 0x0010, "Back": 0x0020,
    "Left Thumb": 0x0040, "Right Thumb": 0x0080,
    "LB": 0x0100, "RB": 0x0200,
    "A": 0x1000, "B": 0x2000, "X": 0x4000, "Y": 0x8000,
}
DEFINED_BUTTON_MASK = sum(BUTTONS.values())


@dataclass(frozen=True)
class XboxState:
    lx: int = 0
    ly: int = 0
    rx: int = 0
    ry: int = 0
    lt: int = 0
    rt: int = 0
    buttons: int = 0


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 1:  # 最低位为 1 时右移并异或反射多项式。
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def pack_frame(state: XboxState) -> bytes:
    payload = PAYLOAD_STRUCT.pack(
        state.lx, state.ly, state.rx, state.ry,
        state.lt, state.rt, state.buttons,
    )
    body = bytes([PAYLOAD_SIZE]) + payload
    return HEADER + body + struct.pack("<H", crc16_modbus(body))


def unpack_frame(frame: bytes) -> XboxState:
    """供联调和测试使用；所有检查通过后才返回完整状态。"""
    if len(frame) != FRAME_SIZE:  # 拒绝残帧和多帧粘连。
        raise ValueError("数据帧长度必须为 17 字节")
    if frame[:2] != HEADER or frame[2] != PAYLOAD_SIZE:
        raise ValueError("包头或 LEN 错误")
    if crc16_modbus(frame[2:15]) != int.from_bytes(frame[15:17], "little"):
        raise ValueError("CRC 校验失败")
    return XboxState(*PAYLOAD_STRUCT.unpack(frame[3:15]))


def format_frame(frame: bytes, mode: str = "HEX", encoding: str = "UTF-8") -> str:
    if mode == "HEX":  # 显示模式只作用于副本，不改变串口原始字节。
        return frame.hex(" ").upper()
    if encoding.upper() not in ("UTF-8", "GBK"):
        raise ValueError("仅支持 UTF-8 和 GBK")
    return frame.decode(encoding, errors="replace")
