"""Phase 7 tests: decoding the preset list the amp sends during the handshake.

The format is in protocol.md section 4, "Preset list". The entries below are
real replies from captures/handshake_replies.txt; the requests are real lines
from spiderweb/handshake.txt.
"""
import struct
import unittest

from spiderweb.amp import load_handshake
from spiderweb.protocol.dump import DUMP_CHUNK_LENGTH, DumpCollector
from spiderweb.protocol.messages import DUMP_REQUEST
from spiderweb.protocol.presets import entry_name, preset_list_request, preset_names, unpack
from tests.test_connection import capture_messages

HEADER = bytes.fromhex("f000010c22054d0100000b00")       # 12 bytes: unpack starts after these
TAP = bytes.fromhex("f000010c22054d003f00000f0005000000080000020004000000767a401d420000000000f7")
DEVICE_INQUIRY = bytes.fromhex("f07e7f0601f7")

# Short layout (asked for with kind 0x06): names up to 12 characters come in 45 bytes.
ACOUSTIC = bytes.fromhex(
    "f000010c22054d01040001080001000000110000000000000000090000000041636f75730074696300000000f7")
USER_1 = bytes.fromhex(
    "f000010c22054d010c00010600010000000f0000000000000000070000000055736572200031000000000000f7")
CLEAN_1_SHORT = bytes.fromhex(
    "f000010c22054d010500020200010000001b00000000000000001300000000436c65616e0020313a2055532000446f75626c6500f7")
CLEAN_2_SHORT = bytes.fromhex(
    "f000010c22054d010600020400010000001d00000000000000001500000000436c65616e0020323a204a617a007a2043686f72750073000000000000f7")

# Long layout (asked for with kind 0x0E).
BASS_LONG = bytes.fromhex(
    "f000010c22054d012f00020400010000001d00000100000000000938002500000000007d18375c4f6204000000050000004261730073000000000000f7")
CHIME_1_LONG = bytes.fromhex(
    "f000010c22054d014300030000010000002900000200000000005423001e000000000029283c7d58650400000011000000436869006d6520313a2043006c6173732d4100f7")
CLEAN_1_LONG = bytes.fromhex(
    "f000010c22054d013900030200010000002b00000000000000002525011e00000000001178696f5b490400000013000000436c6500616e20313a2055005320446f75626c0065000000000000f7")

# Preset-list requests from handshake.txt (lines 17, 21, 61, 86 and 157).
SHORT_0 = bytes.fromhex("f000010c22054d010300000b00060000000400000000000000000000f7")
SHORT_5 = bytes.fromhex("f000010c22054d010700000b00060000000400000000050000000000f7")
LONG_0 = bytes.fromhex("f000010c22054d012f00000b000e0000000400000000000000000000f7")
LONG_5 = bytes.fromhex("f000010c22054d014800000b000e0000000400000000050000000000f7")
SHORT_127 = bytes.fromhex("f000010c22054d010f00000b000600000004000000007f0000000000f7")

SHORT, LONG = 0x06, 0x0E


def handshake_entries():
    """ Every preset-list entry in the clean handshake capture (protocol.md: 240 of them). """
    return [m for m in capture_messages("handshake_replies.txt")
            if 45 <= len(m) <= 77 and m[7] == 1 and m[13] == 1]


class TestUnpack(unittest.TestCase):
    def test_bytes_without_top_bits_pass_through(self):
        self.assertEqual(unpack(HEADER + bytes([0, 1, 2, 3, 4, 5, 6, 7]) + b"\xf7"), bytes([1, 2, 3, 4, 5, 6, 7]))

    def test_the_end_byte_is_not_data(self):
        # The F7 that ends every message isn't part of the packed data.
        self.assertEqual(len(unpack(HEADER + bytes(8) + b"\xf7")), 7)

    def test_top_bits_go_most_significant_first(self):
        # Data byte k takes bit 6 - k (0x40 >> k): 0b1010000 has bits 6 and 4 set,
        # so data bytes 0 and 2 get 0x80 added (protocol.md section 3).
        out = unpack(HEADER + bytes([0b1010000, 1, 2, 3, 4, 5, 6, 7]) + b"\xf7")
        self.assertEqual(out, bytes([0x81, 2, 0x83, 4, 5, 6, 7]))

    def test_bit_0_belongs_to_the_last_data_byte(self):
        out = unpack(HEADER + bytes([0b0000001, 1, 2, 3, 4, 5, 6, 7]) + b"\xf7")
        self.assertEqual(out, bytes([1, 2, 3, 4, 5, 6, 0x87]))

    def test_each_group_has_its_own_top_bits(self):
        out = unpack(HEADER + bytes([0, 1, 1, 1, 1, 1, 1, 1, 0b0000001, 2, 2, 2, 2, 2, 2, 2]) + b"\xf7")
        self.assertEqual(out, bytes([1] * 7 + [2] * 6 + [0x82]))

    def test_a_short_last_group(self):
        # Still numbered from bit 6: the second data byte takes bit 5.
        self.assertEqual(unpack(HEADER + bytes([0b0100000, 1, 2, 3]) + b"\xf7"), bytes([1, 0x82, 3]))

    def test_a_real_dump_reads_drive_0_and_1(self):
        # Crunch 2's Drive at 0.0 then 1.0 (00 00 80 3f): the 0x80 only comes out right
        # most significant first. Drive's float is at offset 1011 of the unpacked chunks.
        values = []
        for name in ("drive_min.txt", "drive_max.txt"):
            collector = DumpCollector()
            for msg in capture_messages(name):
                collector.offer(msg)
            data = b"".join(unpack(chunk) for chunk in collector.chunks if len(chunk) == DUMP_CHUNK_LENGTH)
            values.append(struct.unpack_from("<f", data, 1011)[0])
        self.assertEqual(values, [0.0, 1.0])


class TestPresetListRequest(unittest.TestCase):
    def test_a_short_list_request(self):
        self.assertEqual(preset_list_request(SHORT_5), (SHORT, 5))

    def test_a_long_list_request(self):
        self.assertEqual(preset_list_request(LONG_5), (LONG, 5))

    def test_the_highest_index(self):
        self.assertEqual(preset_list_request(SHORT_127), (SHORT, 127))

    def test_other_handshake_lines_are_not_requests(self):
        self.assertIsNone(preset_list_request(DUMP_REQUEST))
        self.assertIsNone(preset_list_request(TAP))

    def test_messages_too_short_to_check_give_none(self):
        # The handshake starts with a 6-byte device inquiry; it mustn't raise IndexError.
        self.assertIsNone(preset_list_request(DEVICE_INQUIRY))
        self.assertIsNone(preset_list_request(b""))

    def test_the_real_handshake_asks_for_both_lists(self):
        requests = [r for r in map(preset_list_request, load_handshake()) if r is not None]
        short = [index for kind, index in requests if kind == SHORT]
        long = [index for kind, index in requests if kind == LONG]
        self.assertEqual(sorted(short), [i for i in range(128) if i != 4])   # index 4 is never asked for
        self.assertEqual(sorted(long), list(range(115)))


class TestEntryName(unittest.TestCase):
    def test_short_layout_names(self):
        self.assertEqual(entry_name(ACOUSTIC), "Acoustic")
        self.assertEqual(entry_name(USER_1), "User 1")
        self.assertEqual(entry_name(CLEAN_1_SHORT), "Clean 1: US Double")
        self.assertEqual(entry_name(CLEAN_2_SHORT), "Clean 2: Jazz Chorus")

    def test_long_layout_names(self):
        self.assertEqual(entry_name(BASS_LONG), "Bass")
        self.assertEqual(entry_name(CHIME_1_LONG), "Chime 1: Class-A")
        self.assertEqual(entry_name(CLEAN_1_LONG), "Clean 1: US Double")

    def test_every_entry_in_the_capture_has_a_name(self):
        entries = handshake_entries()
        self.assertEqual(len(entries), 240)
        names = [entry_name(m) for m in entries]
        self.assertNotIn(None, names)
        self.assertTrue(all(name and name.isprintable() for name in names), names)

    def test_other_messages_are_not_entries(self):
        for msg in (DUMP_REQUEST, TAP, DEVICE_INQUIRY, SHORT_5, b""):
            self.assertIsNone(entry_name(msg), msg.hex())

    def test_a_message_that_fits_neither_layout_gives_none(self):
        # Right length and bytes 7 and 13, but no valid length byte. At 45 bytes the
        # unpacked data is too short to hold the long layout, so that check mustn't raise.
        for length in (45, 61, 77):
            msg = bytearray(length)
            msg[0], msg[7], msg[13], msg[-1] = 0xF0, 1, 1, 0xF7
            self.assertIsNone(entry_name(bytes(msg)), length)

    def test_a_name_with_a_bad_byte_gives_none(self):
        # Acoustic with the top bit of its first name letter set ("A" + 0x80): not ASCII.
        broken = bytearray(ACOUSTIC)
        broken[28] |= 0x40 >> 2          # msg[28] holds the top bits; the "A" is its data byte 2
        self.assertIsNone(entry_name(bytes(broken)))

    def test_no_message_in_the_captures_makes_it_raise(self):
        for name in ("handshake_replies.txt", "chime_Drive.txt", "preset_clicks.txt"):
            for msg in capture_messages(name):
                entry_name(msg)


class TestPresetNames(unittest.TestCase):
    def test_names_by_index(self):
        names = preset_names([SHORT_0, SHORT_5], [[ACOUSTIC], [USER_1]])
        self.assertEqual(names, {0: "Acoustic", 5: "User 1"})

    def test_the_short_list_wins(self):
        # Both lists agree on the real amp, but the short one covers more, so it goes first.
        names = preset_names([LONG_5, SHORT_5], [[BASS_LONG], [ACOUSTIC]])
        self.assertEqual(names, {5: "Acoustic"})

    def test_the_long_list_fills_gaps(self):
        # The real amp doesn't answer short index 0, and never gets asked short index 4.
        names = preset_names([SHORT_0, LONG_0, SHORT_5], [[], [BASS_LONG], [ACOUSTIC]])
        self.assertEqual(names, {0: "Bass", 5: "Acoustic"})

    def test_the_first_entry_in_a_line_is_its_answer(self):
        names = preset_names([SHORT_5], [[TAP, ACOUSTIC, USER_1]])
        self.assertEqual(names, {5: "Acoustic"})

    def test_a_line_with_no_entry_gives_nothing(self):
        self.assertEqual(preset_names([SHORT_5], [[TAP]]), {})

    def test_entries_after_other_lines_are_ignored(self):
        # An entry that arrives after the dump request isn't an answer to a preset-list request.
        self.assertEqual(preset_names([DUMP_REQUEST, DEVICE_INQUIRY], [[ACOUSTIC], [USER_1]]), {})

    def test_nothing_in_nothing_out(self):
        self.assertEqual(preset_names([], []), {})


if __name__ == "__main__":
    unittest.main()
