import unittest
from pathlib import Path

from spiderweb.protocol.dump import DumpCollector

CAPTURES = Path(__file__).resolve().parent.parent / "captures"

TAP = bytes.fromhex("f000010c22054d003f00000f0005000000080000020004000000767a401d420000000000f7")
PARAM = bytes.fromhex("f000010c22054d0008000107000400000010000000002a0000002500010000040000007f407e7e3f00000000f7")


def capture_messages(name):
    """ Every hex message in a capture file (the last word of each line; other lines skipped). """
    messages = []
    for line in (CAPTURES / name).read_text().splitlines():
        words = line.split()
        if not words:
            continue
        try:
            messages.append(bytes.fromhex(words[-1]))
        except ValueError:
            continue
    return messages


def preset_select_section(name, value):
    """ The messages logged under 'value N:' in a tools/preset_select.py log. """
    messages, inside = [], False
    for line in (CAPTURES / name).read_text().splitlines():
        if line.startswith("value"):
            inside = line.split(":")[0].split()[1] == str(value)
            continue
        if inside and line.strip():
            messages.append(bytes.fromhex(line.strip()))
    return messages


def collect(messages):
    """ Offer every message to a new collector; return it and the list of offer() results. """
    collector = DumpCollector()
    results = [collector.offer(m) for m in messages]
    return collector, results


class TestDumpCollector(unittest.TestCase):
    def test_new_collector_is_empty(self):
        collector = DumpCollector()
        self.assertEqual(collector.chunks, [])
        self.assertFalse(collector.complete())
        self.assertIsNone(collector.name())

    def test_full_dump_from_capture(self):
        # Five 309-byte chunks plus a 45-byte last chunk, mixed in with other messages.
        collector, _ = collect(capture_messages("chime_Drive.txt"))
        self.assertTrue(collector.complete())
        self.assertEqual(collector.name(), "Chime 1: Class-A")
        self.assertEqual([len(c) for c in collector.chunks], [309, 309, 309, 309, 309, 45])

    def test_dump_after_preset_select(self):
        # Last chunk is 53 bytes with 01 0F (not 45 with 01 08).
        collector, _ = collect(preset_select_section("preset_select_2.txt", 0))
        self.assertTrue(collector.complete())
        self.assertEqual(collector.name(), "Bass")
        self.assertEqual(len(collector.chunks[-1]), 53)

    def test_short_dump_ends_at_chunk_4(self):
        collector, _ = collect(preset_select_section("preset_select_2.txt", 12))
        self.assertTrue(collector.complete())
        self.assertEqual(collector.name(), "Vibe 1: Auto Wah")
        self.assertEqual([len(c) for c in collector.chunks], [309, 309, 309, 309, 277])

    def test_offer_reports_what_it_took(self):
        messages = preset_select_section("preset_select_2.txt", 0)
        collector, results = collect(messages)
        taken = [m for m, took in zip(messages, results) if took]
        self.assertEqual(taken, collector.chunks)

    def test_other_messages_are_refused(self):
        collector = DumpCollector()
        self.assertFalse(collector.offer(TAP))
        self.assertFalse(collector.offer(PARAM))
        self.assertEqual(collector.chunks, [])

    def test_later_chunk_before_first_is_refused(self):
        chunks = collect(capture_messages("chime_Drive.txt"))[0].chunks
        collector = DumpCollector()
        self.assertFalse(collector.offer(chunks[1]))
        self.assertEqual(collector.chunks, [])

    def test_chunk_from_another_dump_is_refused(self):
        chunks = collect(capture_messages("chime_Drive.txt"))[0].chunks
        other = bytearray(chunks[1])
        other[8] = (other[8] + 1) % 0x80          # a different dump counter
        collector = DumpCollector()
        self.assertTrue(collector.offer(chunks[0]))
        self.assertFalse(collector.offer(bytes(other)))
        self.assertEqual(len(collector.chunks), 1)

    def test_nothing_taken_after_complete(self):
        chunks = collect(capture_messages("chime_Drive.txt"))[0].chunks
        collector, _ = collect(chunks)
        self.assertTrue(collector.complete())
        self.assertFalse(collector.offer(chunks[0]))   # even another first chunk
        self.assertEqual(len(collector.chunks), 6)

    def test_incomplete_dump_still_has_a_name(self):
        chunks = collect(capture_messages("chime_Drive.txt"))[0].chunks
        collector, _ = collect(chunks[:3])
        self.assertFalse(collector.complete())
        self.assertEqual(collector.name(), "Chime 1: Class-A")


if __name__ == "__main__":
    unittest.main()
