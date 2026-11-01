import unittest

from amp import Amp
from protocol import BYTE_HEADER, BEGIN_LENGTH, SET_VALUE_LENGTH, encode_set_value


class FakeAmp(Amp):
    """ An Amp that records what it would send instead of opening a device. """
    def __init__(self):
        self.seq = 0x0C
        self.transport = FakeTransport()

class FakeTransport():
    def __init__(self):
        self.sent = []

    def send(self, data: bytes):
        self.sent.append(data)

    def read_messages(self, quiet=0.05, limit=1.0):
        return []
class TestSendMessages(unittest.TestCase):
    def setUp(self):
        self.amp = FakeAmp()

    def send_drive(self, value=0.5):
        self.amp.set_raw(0x2A, 0, 0x25, encode_set_value(value))
        return self.amp.transport.sent

    def test_set_sends_begin_then_set(self):
        sent = self.send_drive()
        self.assertEqual(len(sent), 2)
        self.assertEqual(len(sent[0]), BEGIN_LENGTH)
        self.assertEqual(len(sent[1]), SET_VALUE_LENGTH)

    def test_messages_start_with_header_and_end_with_f7(self):
        for msg in self.send_drive():
            self.assertEqual(msg[:8], BYTE_HEADER)
            self.assertEqual(msg[-1], 0xF7)

    def test_all_bytes_except_f0_and_f7_are_below_0x80(self):
        for value in (0.0, 0.3, 0.5, 0.99, 1.0):
            self.setUp()
            for msg in self.send_drive(value):
                for byte in msg[1:-1]:
                    self.assertLess(byte, 0x80)

    def test_amp_block_fields(self):
        msg = self.send_drive()[1]
        self.assertEqual(msg[11], 0x0F)
        self.assertEqual(msg[13], 0x2A)   # block
        self.assertEqual(msg[14], 0)      # sub
        self.assertEqual(msg[17], 0x25)   # parameter id
        self.assertEqual(msg[18], 0)      # sub repeated

    def test_panel_block_puts_sub_in_both_places(self):
        self.amp.set_raw(0x74, 3, 0x24, encode_set_value(0.5))
        msg = self.amp.transport.sent[1]
        self.assertEqual(msg[13], 0x74)
        self.assertEqual(msg[14], 3)
        self.assertEqual(msg[17], 0x24)
        self.assertEqual(msg[18], 3)

    def test_value_bytes_are_where_the_decoder_expects_them(self):
        raw5 = encode_set_value(0.75)
        self.amp.set_raw(0x2A, 0, 0x25, raw5)
        self.assertEqual(self.amp.transport.sent[1][26:31], raw5)

    def test_padding_after_value_is_zero(self):
        msg = self.send_drive()[1]
        self.assertEqual(msg[31:36], bytes(5))

    def test_unknown_byte_defaults_to_one_and_can_be_changed(self):
        self.assertEqual(self.send_drive()[1][20], 1)
        amp2 = FakeAmp()
        amp2.set_raw(0x2A, 0, 0x25, encode_set_value(0.5), unknown=3)
        self.assertEqual(amp2.transport.sent[1][20], 3)

    def test_sequence_numbers(self):
        self.send_drive()
        begin, setmsg = self.amp.transport.sent
        self.assertEqual(begin[8], 0x0C)
        self.assertEqual(setmsg[8], 0x0D)
        self.assertEqual(self.amp.seq, 0x0E)

    def test_sequence_wraps_and_stays_below_0x80(self):
        self.amp.seq = 126
        self.send_drive()
        self.assertEqual(self.amp.transport.sent[1][8], 127)
        self.assertEqual(self.amp.seq, 0)

    def test_matches_the_app_capture_layout(self):
        # Layout of an app panel set from the capture:
        # ...0f 00 74 03 00 00 24 03 00 00 00 04 00 00 00 ...
        self.amp.set_raw(0x74, 3, 0x24, encode_set_value(0.5), unknown=0)
        msg = self.amp.transport.sent[1]
        self.assertEqual(msg[11:26].hex(), "0f00740300002403000000040000" + "00")


if __name__ == "__main__":
    unittest.main()