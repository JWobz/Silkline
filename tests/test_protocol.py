import unittest
from protocol import (
    MessageKind,
    BEGIN_LENGTH,
    BYTE_HEADER,
    SET_VALUE_LENGTH,
    build_begin_message,
    build_set_message,
    classify,
    decode_set_value,
    decode_value,
    encode_set_value,
)

class TestProtocol(unittest.TestCase):
    def test_build_begin_message(self):
        message = build_begin_message(0x0C)
        self.assertEqual(len(message), BEGIN_LENGTH)
        self.assertEqual(message[:8], BYTE_HEADER)
        self.assertEqual(message[8], 0x0C)
        self.assertEqual(message[-1], 0xF7)

    def test_build_set_message(self):
        raw5 = encode_set_value(0.5)
        message = build_set_message(0x0D, 0x74, 3, 0x24, raw5, unknown=0)
        self.assertEqual(len(message), SET_VALUE_LENGTH)
        self.assertEqual(message[:8], BYTE_HEADER)
        self.assertEqual(message[8], 0x0D)
        self.assertEqual(message[11:19], bytes([0x0F, 0, 0x74, 3, 0, 0, 0x24, 3]))
        self.assertEqual(message[20], 0)
        self.assertEqual(message[26:31], raw5)
        self.assertEqual(message[-1], 0xF7)

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
        self.assertEqual(result[0], MessageKind.PARAM)
        self.assertEqual(result[1], (0x2a, 0x25, 0))
        self.assertAlmostEqual(result[2], 0.9921875)

    def test_status_message(self):
        msg = bytes.fromhex("f000010c22054d000700010700030000001000000300020000007f7f607f7f02000000010000000000000000f7")
        result = classify(msg)
        self.assertEqual(result, (MessageKind.STATUS,))

    def test_short_message(self):
        msg = bytes([0xF0, 0xF7])
        result = classify(msg)
        self.assertEqual(result, (MessageKind.UNKNOWN, (2, None, None)))

    def test_preset_info_message(self):
        msg = bytes.fromhex(
            "f000010c22054d011400030200010000002b00000300000000000e2100260000"
            "0000001f780554687c0400000013000000437275006e636820323a2000506173"
            "6164656e0061000000000000f7"
        )
        self.assertEqual(classify(msg), (MessageKind.PRESET_INFO, "Crunch 2: Pasadena", 0x7c))

    def test_dump_chunk_is_not_preset_info(self):
        msg = bytearray(309)     # 309 zero bytes
        msg[13] = 1              # the byte that used to fool the old rule
        self.assertEqual(classify(bytes(msg))[0], MessageKind.UNKNOWN)

    def test_tap_message(self):
        msg = bytes.fromhex(
            "f000010c22054d003f00000f0005000000080000020004000000767a401d420000000000f7"
        )
        result = classify(msg)
        self.assertEqual(result[0], MessageKind.TAP)
        self.assertAlmostEqual(result[1], 157.0)

    def test_save_message(self):
        msg = bytes.fromhex(
            "f000010c22054d00450001070003000000100000000002000000080000000002000000010000000000000000f7"
        )
        self.assertEqual(classify(msg), (MessageKind.SAVE,))

    def test_heartbeat_message(self):
        msg = bytes.fromhex(
            "f000010c22054d00060001070003000000100000000002000000070000000002000000000000000000000000f7"
        )
        self.assertEqual(classify(msg), (MessageKind.HEARTBEAT, 7))

    def test_status_message_is_not_save(self):
        # A status message also has msg[35] == 1, so the 0x7F check must come first.
        msg = bytearray.fromhex(
            "f000010c22054d00060001070003000000100000000002000000070000000002000000000000000000000000f7"
        )
        msg[26] = 0x7F
        msg[27] = 0x7F
        msg[35] = 1
        self.assertEqual(classify(bytes(msg)), (MessageKind.STATUS,))

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

    # --- set values (what we send to the amp) ---

    def test_decode_set_value_known_app_vectors(self):
        # (raw five bytes from the PC app's set messages, expected value)
        vectors = [
            ("5022405d3e", 0.4316),
            ("6033400c3e", 0.2734),
            ("7b1800023f", 0.5078),
        ]
        for raw_hex, expected in vectors:
            with self.subTest(raw=raw_hex):
                value = decode_set_value(bytes.fromhex(raw_hex))
                self.assertAlmostEqual(value, expected, places=3)

    def test_set_value_endpoints(self):
        self.assertEqual(decode_set_value(encode_set_value(0.0)), 0.0)
        self.assertEqual(decode_set_value(encode_set_value(1.0)), 1.0)

    def test_set_value_round_trip(self):
        for x in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
            with self.subTest(x=x):
                result = decode_set_value(encode_set_value(x))
                # the encoder drops the low 16 bits of the float
                self.assertAlmostEqual(result, x, delta=1 / 128)

    def test_encode_set_value_length_is_five(self):
        for x in (0.0, 0.5, 1.0):
            self.assertEqual(len(encode_set_value(x)), 5)

    def test_encode_set_value_bytes_are_valid_sysex_data(self):
        # SysEx data bytes must be below 0x80
        for i in range(101):
            x = i / 100
            with self.subTest(x=x):
                for byte in encode_set_value(x):
                    self.assertLess(byte, 0x80)

    def test_encode_set_value_flag_is_in_third_byte_only(self):
        raw = encode_set_value(1.0)
        self.assertEqual(raw[0], 0)
        self.assertEqual(raw[1], 0)
        self.assertEqual(raw[2], 0x40)

    def test_encode_set_value_out_of_range_raises(self):
        for bad in (-0.1, 1.5):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    encode_set_value(bad)

if __name__ == "__main__":
    unittest.main()