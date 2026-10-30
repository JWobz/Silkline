import unittest
from protocol import decode_value, classify

class TestProtocol(unittest.TestCase):
    def test_known_values(self):
        decode_cases = [
            ("7f407e7e3f", 0.9921875),
            ("014000003f", 0.5),
            ("00607f7e3e", 0.49609375),
            ("026000003e", 0.25),
            ("00407d7c3e", 0.24609375),
            ("086000003b", 0.00390625),
        ]

        for hex_text, expected in decode_cases:
            with self.subTest(hex=hex_text):
                self.assertAlmostEqual(decode_value(bytes.fromhex(hex_text)), expected)

    def test_param_message(self):
        msg = bytes.fromhex("f000010c22054d0008000107000400000010000000002a0000002500010000040000007f407e7e3f00000000f7")
        result = classify(msg)
        self.assertEqual(result[0], "param")
        self.assertEqual(result[1], (0x2a, 0x25, 0))
        self.assertAlmostEqual(result[2], 0.9921875)

    def test_status_message(self):
        msg = bytes.fromhex("f000010c22054d000700010700030000001000000300020000007f7f607f7f02000000010000000000000000f7")
        result = classify(msg)
        self.assertEqual(result, ("status",))

    def test_short_message(self):
        msg = bytes([0xF0, 0xF7])
        result = classify(msg)
        self.assertEqual(result, ("unknown", (2, None, None)))

    def test_preset_info_message(self):
        msg = bytes.fromhex(
            "f000010c22054d011400030200010000002b00000300000000000e2100260000"
            "0000001f780554687c0400000013000000437275006e636820323a2000506173"
            "6164656e0061000000000000f7"
        )
        self.assertEqual(classify(msg), ("preset_info", "Crunch 2: Pasadena", 0x7c))

    def test_dump_chunk_is_not_preset_info(self):
        msg = bytearray(309)     # 309 zero bytes
        msg[13] = 1              # the byte that used to fool the old rule
        self.assertEqual(classify(bytes(msg))[0], "unknown")

    def test_tap_message(self):
        msg = bytes.fromhex(
            "f000010c22054d003f00000f0005000000080000020004000000767a401d420000000000f7"
        )
        result = classify(msg)
        self.assertEqual(result[0], "tap")
        self.assertAlmostEqual(result[1], 157.0)

    def test_save_message(self):
        msg = bytes.fromhex(
            "f000010c22054d00450001070003000000100000000002000000080000000002000000010000000000000000f7"
        )
        self.assertEqual(classify(msg), ("save",))

    def test_heartbeat_message(self):
        msg = bytes.fromhex(
            "f000010c22054d00060001070003000000100000000002000000070000000002000000000000000000000000f7"
        )
        self.assertEqual(classify(msg), ("heartbeat", 7))

    def test_status_message_is_not_save(self):
        # A status message also has msg[35] == 1, so the 0x7F check must come first.
        msg = bytearray.fromhex(
            "f000010c22054d00060001070003000000100000000002000000070000000002000000000000000000000000f7"
        )
        msg[26] = 0x7F
        msg[27] = 0x7F
        msg[35] = 1
        self.assertEqual(classify(bytes(msg)), ("status",))

    def test_same_id_different_block_gives_different_keys(self):
        base = bytearray.fromhex(
            "f000010c22054d0011000107000400000010000000002a000000250001000004000000214020203d00000000f7"
        )
        amp_msg = bytearray(base)
        amp_msg[26] = 0x24            # block 0x2a, sub 0
        panel_msg = bytearray(base)
        panel_msg[22] = 0x74
        panel_msg[26] = 0x24
        panel_msg[27] = 3
        amp_key = classify(bytes(amp_msg))[1]
        panel_key = classify(bytes(panel_msg))[1]
        self.assertEqual(amp_key, (0x2a, 0x24, 0))
        self.assertEqual(panel_key, (0x74, 0x24, 3))
        self.assertNotEqual(amp_key, panel_key)

if __name__ == "__main__":
    unittest.main()