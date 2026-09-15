from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


class DocumentationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("gcc"), "需要 GCC 才能编译文档 C 示例")
    def test_c_parser_and_stream_resynchronization(self):
        document = (Path(__file__).resolve().parents[1] / "docs" / "MCU_Protocol_Guide.md").read_text(encoding="utf-8")
        source = re.search(r"```c\n(.*?)```", document, re.DOTALL).group(1)
        harness = r'''
#include <assert.h>
int main(void)
{
    uint8_t frame[] = {0xAA,0x55,0x0C,0x00,0x80,0xFF,0x7F,0xFF,0xFF,
                       0x39,0x30,0x80,0xFF,0x01,0x11,0x77,0x2E};
    XboxState state = {0};
    assert(crc16_modbus((const uint8_t *)"123456789", 9) == 0x4B37u);
    assert(xbox_parse_frame(frame, 17, &state) == 1);
    assert(state.lx == -32768 && state.ly == 32767 && state.rx == -1);
    assert(state.ry == 12345 && state.lt == 128 && state.rt == 255);
    assert(state.buttons == 0x1101u);
    for (size_t i = 0; i < 17; ++i) {
        for (unsigned int bit = 0; bit < 8; ++bit) {
            frame[i] ^= (uint8_t)(1u << bit);
            assert(xbox_parse_frame(frame, 17, &state) == 0);
            assert(state.lx == -32768 && state.buttons == 0x1101u);
            frame[i] ^= (uint8_t)(1u << bit);
        }
    }
    assert(xbox_parse_frame(frame, 16, &state) == 0);
    assert(xbox_parse_frame(NULL, 17, &state) == 0);
    XboxReceiver receiver;
    xbox_rx_init(&receiver);
    uint8_t noise[] = {0,0xAA,0xAA,0x55,0x77,0xAA};
    int accepted = 0;
    for (size_t i = 0; i < sizeof(noise); ++i) {
        accepted += xbox_rx_byte(&receiver, noise[i], &state);
    }
    /* A truncated frame followed by two valid frames, without resetting. */
    for (size_t i = 0; i < 9; ++i) {
        accepted += xbox_rx_byte(&receiver, frame[i], &state);
    }
    for (int round = 0; round < 2; ++round) {
        for (size_t i = 0; i < 17; ++i) {
            accepted += xbox_rx_byte(&receiver, frame[i], &state);
        }
    }
    assert(accepted == 2);
    /* Corrupted frame containing an embedded header, then valid frame. */
    frame[5] = 0xAA; frame[6] = 0x55;
    for (size_t i = 0; i < 17; ++i) {
        accepted += xbox_rx_byte(&receiver, frame[i], &state);
    }
    frame[5] = 0xFF; frame[6] = 0x7F;
    for (size_t i = 0; i < 17; ++i) {
        accepted += xbox_rx_byte(&receiver, frame[i], &state);
    }
    assert(accepted == 3);
    return 0;
}
'''
        # 保留临时编译产物供核验，不递归或批量删除文件。
        directory = Path(tempfile.mkdtemp(prefix="xbox_c_test_"))
        c_file = directory / "protocol_test.c"
        executable = directory / "protocol_test.exe"
        c_file.write_text(source + harness, encoding="utf-8")
        result = subprocess.run([shutil.which("gcc"), "-std=c99", "-Wall", "-Wextra", "-Werror",
                                 str(c_file), "-o", str(executable)], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        result = subprocess.run([str(executable)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
