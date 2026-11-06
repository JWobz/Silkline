"""Byte layout of the messages we send to set a parameter, and of the amp's answer
(protocol.md section 8).

These test the message builders and the answer check directly. What Amp sends, and
its seq counter, are tested in test_amp.py.
"""
import unittest

from spiderweb.protocol.messages import (
    BEGIN_LENGTH,
    BYTE_HEADER,
    DUMP_REQUEST,
    SET_VALUE_LENGTH,
    SetAnswer,
    build_begin_message,
    build_set_message,
    is_set_answer,
)
from spiderweb.protocol.values import encode_set_value

# Real messages from captures/set_pace.txt and captures/amp_survey_2.txt.
SET_ANSWER = bytes.fromhex("f000010c22054d000900000b00010000000400000000000000000000f7")
SELECT_ANSWER = bytes.fromhex("f000010c22054d017500000b00010000000400000000000000000000f7")   # channel 1
STATUS = bytes.fromhex(
    "f000010c22054d000a00010700030000001000000300020000007f7f607f7f02000000010000000000000000f7")


def drive_set(value=0.5, sequence=0x0D, unknown=1):
    """ A set message for Drive (block 0x2A, sub 0, id 0x25). """
    return build_set_message(sequence, 0x2A, 0, 0x25, encode_set_value(value), unknown)


def panel_volume_set(value=0.5, unknown=1):
    """ A set message for panel Volume (block 0x74, sub 3, id 0x24). """
    return build_set_message(0x0D, 0x74, 3, 0x24, encode_set_value(value), unknown)


class TestBeginMessage(unittest.TestCase):
    def test_length(self):
        self.assertEqual(len(build_begin_message(0x0C)), BEGIN_LENGTH)

    def test_header_sequence_and_end(self):
        msg = build_begin_message(0x0C)
        self.assertEqual(msg[:8], BYTE_HEADER)
        self.assertEqual(msg[8], 0x0C)
        self.assertEqual(msg[-1], 0xF7)

    def test_sequence_out_of_range_is_refused(self):
        for bad in (-1, 0x80):
            with self.assertRaises(ValueError):
                build_begin_message(bad)


class TestSetMessage(unittest.TestCase):
    def test_length(self):
        self.assertEqual(len(drive_set()), SET_VALUE_LENGTH)

    def test_header_sequence_and_end(self):
        msg = drive_set(sequence=0x0D)
        self.assertEqual(msg[:8], BYTE_HEADER)
        self.assertEqual(msg[8], 0x0D)
        self.assertEqual(msg[-1], 0xF7)

    def test_all_bytes_except_f0_and_f7_are_below_0x80(self):
        for value in (0.0, 0.3, 0.5, 0.99, 1.0):
            for msg in (build_begin_message(0x7E), drive_set(value, sequence=0x7F)):
                for byte in msg[1:-1]:
                    self.assertLess(byte, 0x80)

    def test_amp_block_fields(self):
        msg = drive_set()
        self.assertEqual(msg[11], 0x0F)   # set
        self.assertEqual(msg[13], 0x2A)   # block
        self.assertEqual(msg[14], 0)      # sub
        self.assertEqual(msg[17], 0x25)   # parameter id
        self.assertEqual(msg[18], 0)      # sub repeated

    def test_panel_block_puts_sub_in_both_places(self):
        msg = panel_volume_set()
        self.assertEqual(msg[13], 0x74)
        self.assertEqual(msg[14], 3)
        self.assertEqual(msg[17], 0x24)
        self.assertEqual(msg[18], 3)

    def test_value_bytes_are_where_the_decoder_expects_them(self):
        raw5 = encode_set_value(0.75)
        msg = build_set_message(0x0D, 0x2A, 0, 0x25, raw5)
        self.assertEqual(msg[26:31], raw5)

    def test_padding_after_value_is_zero(self):
        self.assertEqual(drive_set()[31:36], bytes(5))

    def test_unknown_byte_defaults_to_one_and_can_be_changed(self):
        self.assertEqual(build_set_message(0x0D, 0x2A, 0, 0x25, encode_set_value(0.5))[20], 1)
        self.assertEqual(drive_set(unknown=3)[20], 3)

    def test_matches_the_app_capture_layout(self):
        # Layout of an app panel set from the capture:
        # ...0f 00 74 03 00 00 24 03 00 00 00 04 00 00 00 ...
        msg = panel_volume_set(unknown=0)
        self.assertEqual(msg[11:26].hex(), "0f00740300002403000000040000" + "00")

    def test_sequence_out_of_range_is_refused(self):
        for bad in (-1, 0x80):
            with self.assertRaises(ValueError):
                drive_set(sequence=bad)

    def test_value_must_be_five_bytes(self):
        with self.assertRaises(ValueError):
            build_set_message(0x0D, 0x2A, 0, 0x25, bytes(4))


class TestSetAnswer(unittest.TestCase):
    def test_the_amps_answer_to_a_set(self):
        self.assertTrue(is_set_answer(SET_ANSWER))

    def test_the_answer_to_a_select_is_not_it(self):
        # Same shape, but on channel 1 (msg[7] == 1).
        self.assertFalse(is_set_answer(SELECT_ANSWER))

    def test_other_messages_are_not_it(self):
        for msg in (DUMP_REQUEST, STATUS, build_begin_message(0x0C), drive_set(), b""):
            self.assertFalse(is_set_answer(msg), msg.hex())

    def test_collector_is_complete_after_the_answer(self):
        collector = SetAnswer()
        self.assertFalse(collector.complete())
        self.assertTrue(collector.offer(SET_ANSWER))
        self.assertTrue(collector.complete())

    def test_collector_refuses_other_messages(self):
        collector = SetAnswer()
        self.assertFalse(collector.offer(STATUS))
        self.assertFalse(collector.offer(SELECT_ANSWER))
        self.assertFalse(collector.complete())

    def test_collector_takes_only_one_answer(self):
        # A second answer belongs to the next set, so it must be left for that set's collector.
        collector = SetAnswer()
        collector.offer(SET_ANSWER)
        self.assertFalse(collector.offer(SET_ANSWER))


if __name__ == "__main__":
    unittest.main()
