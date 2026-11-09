"""Byte layout of the messages we send to set a parameter, and of the amp's answer
(protocol.md section 8).

These test the message builders and the answer check directly. What Amp sends, and
its seq counter, are tested in test_amp.py.
"""
import struct
import unittest

from silkline.protocol.messages import (
    BEGIN_LENGTH,
    BYTE_HEADER,
    DUMP_REQUEST,
    FLOAT_VALUE,
    SET_VALUE_LENGTH,
    SWITCH_VALUE,
    SetAnswer,
    build_begin_message,
    build_set_message,
    _is_set_answer,
)
from silkline.protocol.parameters import PARAMETERS
from silkline.protocol.packing import unpack
from silkline.protocol.values import encode_set_value, encode_switch
from tests.helpers import SET_ANSWER, set_fields

# Real messages from captures/amp_survey_2.txt (SET_ANSWER is in helpers.py).
SELECT_ANSWER = bytes.fromhex("f000010c22054d017500000b00010000000400000000000000000000f7")   # channel 1
STATUS = bytes.fromhex(
    "f000010c22054d000a00010700030000001000000300020000007f7f607f7f02000000010000000000000000f7")


def drive_set(value=0.5, sequence=0x0D):
    """ A set message for Drive (block 2A sub 0, symbol 0x026). """
    return build_set_message(sequence, 0x2A, 0, 0x026, FLOAT_VALUE, encode_set_value(value))


def panel_volume_set(value=0.5, sequence=0x0D):
    """ A set message for panel Volume (block 74 sub 3, symbol 0x324). """
    return build_set_message(sequence, 0x74, 3, 0x324, FLOAT_VALUE, encode_set_value(value))


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
    """ A set is four little-endian numbers, packed like a dump (protocol.md section 8). """

    def test_length(self):
        self.assertEqual(len(drive_set()), SET_VALUE_LENGTH)

    def test_header_sequence_and_end(self):
        msg = drive_set(sequence=0x0D)
        self.assertEqual(msg[:8], BYTE_HEADER)
        self.assertEqual(msg[8:12], bytes([0x0D, 0, 0, 0x0F]))
        self.assertEqual(msg[-1], 0xF7)

    def test_all_bytes_except_f0_and_f7_are_below_0x80(self):
        for value in (0.0, 0.3, 0.5, 0.99, 1.0, -96.0, 77.0):
            for msg in (build_begin_message(0x7E), drive_set(value, sequence=0x7F)):
                for byte in msg[1:-1]:
                    self.assertLess(byte, 0x80)

    def test_the_four_numbers(self):
        self.assertEqual(set_fields(panel_volume_set(0.5)), (0x74, 3, 0x324, FLOAT_VALUE, 0.5))

    def test_the_unpacked_bytes(self):
        # 74 03 00 00 | 24 03 00 00 | 04 00 00 00 | 00 00 00 3f | 5 zeros
        self.assertEqual(unpack(panel_volume_set(0.5)).hex(),
                         "74030000" "24030000" "04000000" "0000003f" "0000000000")

    def test_the_whole_float_goes(self):
        # The old encoding kept only the top 16 bits (0.2345 came back as 0.2344...).
        value = set_fields(drive_set(0.2345))[4]
        self.assertEqual(struct.pack("<f", value), struct.pack("<f", 0.2345))

    def test_a_switch(self):
        msg = build_set_message(0x0D, 0x74, 3, 0x348, SWITCH_VALUE, encode_switch(True))
        self.assertEqual(set_fields(msg), (0x74, 3, 0x348, SWITCH_VALUE, 1))

    def test_namespace_can_differ_from_sub(self):
        # Reverb mix from the app capture: block 1F sub 3, symbol 0x17A (id 7A, namespace 1).
        msg = build_set_message(0x0D, 0x1F, 3, 0x17A, FLOAT_VALUE, encode_set_value(0.5))
        self.assertEqual(set_fields(msg)[:3], (0x1F, 3, 0x17A))

    def test_a_symbol_of_0x80_and_more(self):
        # EQ Hi Shelf Gain is 0x282: the id's top bit goes in msg[12] (0x04), as the app
        # sends it (names.txt) and the amp takes it (2026-11-09).
        msg = build_set_message(0x0D, 0x25, 3, 0x282, FLOAT_VALUE, encode_set_value(0.5))
        self.assertEqual((msg[12], msg[17], msg[18]), (0x04, 0x02, 0x02))
        self.assertEqual(set_fields(msg)[2], 0x282)

    def test_every_parameter(self):
        for p in PARAMETERS:
            with self.subTest(p.name):
                value, value_type = p.encode(1 if p.kind == "switch" else p.low)
                msg = build_set_message(0x0D, p.block, p.sub, p.symbol, value_type, value)
                self.assertEqual(set_fields(msg)[:4], (p.block, p.sub, p.symbol, value_type))

    def test_matches_the_apps_sets(self):
        # Three sets the app sent (captures/windows/names.txt): same bytes when rebuilt.
        for hex_msg in (
            "f000010c22054d000d00000f0074030000240300030004000000322900183f0000000000f7",   # Volume
            "f000010c22054d005e00000f007403000050030000000300000000000000000000000000f7",   # Reverb On, off
            "f000010c22054d002f00000f0425030000020200010004000000726640603e0000000000f7",   # EQ Hi Shelf Gain
        ):
            with self.subTest(msg=hex_msg[16:40]):
                app = bytes.fromhex(hex_msg)
                block, sub, symbol, value_type, value = set_fields(app)
                raw = unpack(app)[12:16]
                self.assertEqual(build_set_message(app[8], block, sub, symbol, value_type, raw), app)

    def test_sequence_out_of_range_is_refused(self):
        for bad in (-1, 0x80):
            with self.assertRaises(ValueError):
                drive_set(sequence=bad)

    def test_value_must_be_four_bytes(self):
        for bad in (bytes(3), bytes(5)):
            with self.assertRaises(ValueError):
                build_set_message(0x0D, 0x2A, 0, 0x026, FLOAT_VALUE, bad)


class TestSetAnswer(unittest.TestCase):
    def test_the_amps_answer_to_a_set(self):
        self.assertTrue(_is_set_answer(SET_ANSWER))

    def test_the_answer_to_a_select_is_not_it(self):
        # Same shape, but on channel 1 (msg[7] == 1).
        self.assertFalse(_is_set_answer(SELECT_ANSWER))

    def test_other_messages_are_not_it(self):
        for msg in (DUMP_REQUEST, STATUS, build_begin_message(0x0C), drive_set(), b""):
            self.assertFalse(_is_set_answer(msg), msg.hex())

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
