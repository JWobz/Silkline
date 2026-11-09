import struct
import unittest

from silkline.protocol import (
    FLOAT_VALUE,
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
    encode_switch,
    unpack,
)

class TestProtocol(unittest.TestCase):
    def test_build_begin_message(self):
        message = build_begin_message(0x0C)
        self.assertEqual(len(message), BEGIN_LENGTH)
        self.assertEqual(message[:8], BYTE_HEADER)
        self.assertEqual(message[8], 0x0C)
        self.assertEqual(message[-1], 0xF7)

    def test_build_set_message(self):
        message = build_set_message(0x0D, 0x74, 3, 0x324, FLOAT_VALUE, encode_set_value(0.5))
        self.assertEqual(len(message), SET_VALUE_LENGTH)
        self.assertEqual(message[:8], BYTE_HEADER)
        self.assertEqual(message[8:12], bytes([0x0D, 0, 0, 0x0F]))
        self.assertEqual(unpack(message)[:16], bytes.fromhex("74030000" "24030000" "04000000" "0000003f"))
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
        self.assertEqual(classify(msg), (MessageKind.PRESET_INFO, "Crunch 2: Pasadena"))

    def test_short_preset_info_message(self):
        # Names of 12 characters or fewer come in 45-byte messages, in the short layout (protocol.md section 4).
        msg = bytes.fromhex(
            "f000010c22054d01040001080001000000110000000000000000090000000041636f75730074696300000000f7")
        self.assertEqual(classify(msg), (MessageKind.PRESET_INFO, "Acoustic"))

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

    def test_preset_change_messages(self):
        # Real preset-knob clicks from captures/preset_clicks.txt.
        # The raw value at msg[26] is the knob position plus 8, wrapped at 16.
        cases = [
            ("f000010c22054d002f0001070003000000100000000002000000080000000002000000000000000000000000f7", 0),   # raw 8
            ("f000010c22054d000b0001070003000000100000000002000000050000000002000000000000000000000000f7", 13),  # raw 5
            ("f000010c22054d001e0001070003000000100000000002000000000000000002000000000000000000000000f7", 8),   # raw 0
            ("f000010c22054d00060001070003000000100000000002000000070000000002000000000000000000000000f7", 15),  # raw 7
        ]
        for hex_text, position in cases:
            with self.subTest(position=position):
                self.assertEqual(classify(bytes.fromhex(hex_text)), (MessageKind.PRESET_CHANGE, position))

    def test_preset_change_covers_all_positions(self):
        # Every raw value 0 to 15 maps to a different position 0 to 15.
        base = bytearray.fromhex(
            "f000010c22054d002f0001070003000000100000000002000000080000000002000000000000000000000000f7"
        )
        positions = set()
        for raw in range(16):
            base[26] = raw
            kind, position = classify(bytes(base))
            self.assertEqual(kind, MessageKind.PRESET_CHANGE)
            positions.add(position)
        self.assertEqual(positions, set(range(16)))

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
        # (msg[26:31] of the PC app's set messages, expected value): the float's top
        # 16 bits, with msg[28]'s packing bit for msg[29] (protocol.md section 8).
        vectors = [
            ("5022405d3e", 0.4316),
            ("6033400c3e", 0.2734),
            ("7b1800023f", 0.5078),
        ]
        for raw_hex, expected in vectors:
            with self.subTest(raw=raw_hex):
                value = decode_set_value(bytes.fromhex(raw_hex))
                self.assertAlmostEqual(value, expected, places=3)

    def test_encode_set_value_is_the_plain_float(self):
        # 4 little-endian bytes; build_set_message packs them.
        for x in (0.0, 0.2345, 0.5, 1.0, 77.0):
            with self.subTest(x=x):
                self.assertEqual(encode_set_value(x), struct.pack("<f", x))

    def test_encode_set_value_takes_negatives(self):
        # The models file gives the gate threshold -96 to 0; packing carries the sign bit.
        self.assertEqual(encode_set_value(-96.0), struct.pack("<f", -96.0))

    def test_encode_switch(self):
        self.assertEqual(encode_switch(True), bytes([1, 0, 0, 0]))
        self.assertEqual(encode_switch(False), bytes(4))
        self.assertEqual(encode_switch(1), encode_switch(True))

if __name__ == "__main__":
    unittest.main()