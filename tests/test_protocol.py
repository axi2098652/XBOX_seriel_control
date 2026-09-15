import random
import struct
import unittest

from protocol import XboxState, crc16_modbus, format_frame, pack_frame, unpack_frame

EXAMPLE_FRAME = bytes.fromhex("AA 55 0C 00 80 FF 7F FF FF 39 30 80 FF 01 11 77 2E")
EXAMPLE_STATE = XboxState(-32768, 32767, -1, 12345, 128, 255, 0x1101)


def reference_crc(data):
    # 使用正向多项式及输入/输出反射，独立核对右移实现。
    crc = 0xFFFF
    for byte in data:
        crc ^= int(f"{byte:08b}"[::-1], 2) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x8005) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return int(f"{crc:016b}"[::-1], 2)


class ProtocolTests(unittest.TestCase):
    def test_modbus_check_value(self):
        self.assertEqual(crc16_modbus(b"123456789"), 0x4B37)

    def test_document_example(self):
        self.assertEqual(pack_frame(EXAMPLE_STATE), EXAMPLE_FRAME)
        self.assertEqual(unpack_frame(EXAMPLE_FRAME), EXAMPLE_STATE)
        self.assertEqual(reference_crc(EXAMPLE_FRAME[2:15]), 0x2E77)

    def test_zero_frame(self):
        self.assertEqual(pack_frame(XboxState()).hex(), "aa550c0000000000000000000000001227")

    def test_random_states_and_independent_crc(self):
        rng = random.Random(360)
        for _ in range(200):
            state = XboxState(*(rng.randint(-32768, 32767) for _ in range(4)),
                              rng.randrange(256), rng.randrange(256), rng.randrange(65536))
            frame = pack_frame(state)
            self.assertEqual(len(frame), 17)
            self.assertEqual(unpack_frame(frame), state)
            self.assertEqual(int.from_bytes(frame[15:], "little"), reference_crc(frame[2:15]))

    def test_every_single_bit_corruption_rejected(self):
        for byte in range(17):
            for bit in range(8):
                damaged = bytearray(EXAMPLE_FRAME)
                damaged[byte] ^= 1 << bit
                with self.assertRaises(ValueError):
                    unpack_frame(damaged)

    def test_wrong_lengths_rejected(self):
        for frame in (b"", EXAMPLE_FRAME[:16], EXAMPLE_FRAME + b"\0"):
            with self.assertRaises(ValueError):
                unpack_frame(frame)

    def test_values_out_of_range_rejected(self):
        for state in (XboxState(lx=32768), XboxState(ly=-32769), XboxState(lt=256), XboxState(buttons=-1)):
            with self.assertRaises(struct.error):
                pack_frame(state)

    def test_display_does_not_change_bytes(self):
        frame = bytes(EXAMPLE_FRAME)
        self.assertEqual(format_frame(frame), EXAMPLE_FRAME.hex(" ").upper())
        for encoding in ("UTF-8", "GBK"):
            self.assertEqual(format_frame(frame, "Text", encoding), frame.decode(encoding, errors="replace"))
        self.assertEqual(frame, EXAMPLE_FRAME)


if __name__ == "__main__":
    unittest.main()
