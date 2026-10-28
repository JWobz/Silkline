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
        self.assertEqual(result[1], 0x25)
        self.assertAlmostEqual(result[2], 0.9921875)

    def test_status_message(self):
        msg = bytes.fromhex("f000010c22054d000700010700030000001000000300020000007f7f607f7f02000000010000000000000000f7")
        result = classify(msg)
        self.assertEqual(result, ("status",))

    def test_short_message(self):
        msg = bytes([0xF0, 0xF7])
        result = classify(msg)
        self.assertEqual(result, ("unknown", (2, None, None)))

    
if __name__ == "__main__":
    unittest.main()