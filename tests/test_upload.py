"""Uploads: packing, the message framing, and whole uploads rebuilt from the app's own
(protocol.md section 8, "Uploads"). Also the preset data inside a dump, which save() sends.

The captures are the Windows app's: captures/windows/save.txt (a save over Chime 1)
and captures/windows/session.txt (14 type changes and a save-as).
"""
import unittest
from pathlib import Path

from spiderweb.protocol.dump import DumpCollector, preset_data
from spiderweb.protocol.presets import unpack
from spiderweb.protocol.upload import EDIT_BUFFER, build_upload, pack, upload_message
from tests.helpers import chime_dump

WINDOWS = Path(__file__).parent.parent / "captures" / "windows"


def outgoing(name):
    """ Every PC -> amp message in a Windows capture, in order. """
    out = []
    for line in (WINDOWS / name).read_text().splitlines():
        words = line.split()
        if len(words) == 4 and words[2] == "out":
            out.append(bytes.fromhex(words[3]))
    return out


def app_uploads(name):
    """ Each upload the app sent: (its messages, counter, slot, data).

    An upload is a 37-byte channel-1 header whose data starts 0C 00 00 00, then the
    messages with the next counter and index 0, 1, 2... The data is read straight from
    the messages (unpacked, cut to the length in msg[10:12]), not with upload.py.
    """
    msgs, found = outgoing(name), []
    for i, m in enumerate(msgs):
        if not (len(m) == 37 and m[7] == 1 and m[9:12] == b"\x00\x00\x0f"):
            continue
        head = unpack(m)
        if head[:4] != b"\x0c\x00\x00\x00":
            continue
        pieces = []
        for x in msgs[i + 1:i + 12]:
            if x[7] == 1 and x[8] == (m[8] + 1) % 128 and x[9] == len(pieces) and len(x) > 20:
                pieces.append(x)
        data = b"".join(unpack(x)[:(x[10] << 4 | x[11]) + 1] for x in pieces)
        found.append(([m] + pieces, m[8], int.from_bytes(head[8:12], "little"), data))
    return found


class TestPack(unittest.TestCase):
    def test_low_bytes_pass_through(self):
        self.assertEqual(pack(bytes(range(7))), bytes([0]) + bytes(range(7)))

    def test_top_bits_go_in_the_first_byte_most_significant_first(self):
        # byte 0's top bit is 0x40, byte 6's is 0x01 (protocol.md section 3)
        self.assertEqual(pack(bytes([0x80, 0, 0, 0, 0, 0, 0xFF])),
                         bytes([0x41, 0, 0, 0, 0, 0, 0, 0x7F]))

    def test_pads_to_a_whole_group(self):
        self.assertEqual(pack(b"\x01\x02"), bytes([0, 1, 2, 0, 0, 0, 0, 0]))

    def test_nothing_in_the_output_is_above_0x7f(self):
        self.assertTrue(all(b < 0x80 for b in pack(bytes(range(256)))))

    def test_unpack_undoes_it(self):
        data = bytes(range(256)) * 2
        msg = b"\x00" * 12 + pack(data) + b"\xf7"          # unpack reads msg[12:-1]
        self.assertEqual(unpack(msg)[:len(data)], data)


class TestUploadMessage(unittest.TestCase):
    def test_framing(self):
        msg = upload_message(0x39, 2, bytes(210))
        self.assertEqual(msg[:7], bytes.fromhex("f000010c22054d"))
        self.assertEqual(msg[7:12], bytes([0x01, 0x39, 2, 0x0D, 0x01]))   # 209 = 0xD1
        self.assertEqual(msg[-1], 0xF7)
        self.assertEqual(len(msg), 253)

    def test_the_length_halves(self):
        for length, halves in ((210, (0x0D, 0x01)), (203, (0x0C, 0x0A)), (16, (0x00, 0x0F)), (256, (0x0F, 0x0F))):
            with self.subTest(length=length):
                self.assertEqual(tuple(upload_message(0, 0, bytes(length))[10:12]), halves)


class TestBuildUpload(unittest.TestCase):
    def test_the_header_holds_the_lengths_and_slot(self):
        header = unpack(build_upload(0x38, 4, bytes(1253))[0])[:16]
        self.assertEqual([int.from_bytes(header[i:i + 4], "little") for i in range(0, 16, 4)],
                         [12, 1261, 4, 1253])

    def test_the_edit_buffer_is_ff_ff_ff_ff(self):
        header = unpack(build_upload(0, EDIT_BUFFER, bytes(10))[0])
        self.assertEqual(header[8:12], b"\xff\xff\xff\xff")

    def test_pieces_share_the_next_counter_and_count_up(self):
        msgs = build_upload(0x38, 4, bytes(1253))
        self.assertEqual([(m[8], m[9]) for m in msgs],
                         [(0x38, 0)] + [(0x39, i) for i in range(6)])
        self.assertEqual([len(m) for m in msgs], [37, 253, 253, 253, 253, 253, 245])

    def test_the_counter_wraps(self):
        self.assertEqual(build_upload(0x7F, 4, bytes(10))[1][8], 0)

    def test_the_apps_save_is_rebuilt_exactly(self):
        (msgs, counter, slot, data), = app_uploads("save.txt")
        self.assertEqual((slot, len(data)), (4, 1253))
        self.assertEqual(build_upload(counter, slot, data), msgs)

    def test_every_upload_in_the_session_is_rebuilt_exactly(self):
        uploads = app_uploads("session.txt")
        self.assertEqual(len(uploads), 23)                  # 22 type changes and stage moves, and a save
        for msgs, counter, slot, data in uploads:
            with self.subTest(counter=counter, length=len(data)):
                self.assertEqual(build_upload(counter, slot, data), msgs)

    def test_type_changes_go_to_the_edit_buffer(self):
        slots = {slot for _, _, slot, _ in app_uploads("session.txt")}
        self.assertEqual(slots, {EDIT_BUFFER, 4})


def chime():
    collector = DumpCollector()
    for msg in chime_dump():
        collector.offer(msg)
    assert collector.complete()
    return collector


class TestPresetData(unittest.TestCase):
    def test_data_cuts_each_chunk_to_its_length(self):
        dump = chime()
        self.assertEqual(len(dump.data()),
                         sum((c[10] << 4 | c[11]) + 1 for c in dump.chunks))

    def test_the_dump_header_counts_the_bytes_after_it(self):
        data = chime().data()
        self.assertEqual(data[:4], b"\x01\x00\x00\x00")
        self.assertEqual(int.from_bytes(data[4:8], "little"), len(data) - 8)

    def test_preset_data_starts_like_the_apps_upload(self):
        # The app's save starts with the same bytes: 00 00 00 80 02 00 02 00 ... "PSRP"
        (_, _, _, app_data), = app_uploads("save.txt")
        ours = preset_data(chime())
        self.assertEqual(ours[:16], app_data[:16])
        self.assertEqual(ours[16:20], b"PSRP")

    def test_preset_data_is_the_rest_of_the_dump(self):
        dump = chime()
        self.assertEqual(preset_data(dump), dump.data()[12:])


if __name__ == "__main__":
    unittest.main()
