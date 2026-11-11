"""The preset's tempo (silkline/protocol/dump.py, read_tempo): header record 3 of a dump
(protocol.md section 3), and the service setting AmpState.bpm from every dump.
"""
import unittest
from unittest import mock

from silkline.protocol.dump import DumpCollector, read_tempo
from tests.helpers import preset_select_section

# What preset_select_2.txt's dumps hold (select value: name, tempo).
TEMPOS = {0: ("Bass", 120.0), 1: ("Acoustic", 96.0), 4: ("Chime 1: Class-A", 139.35),
          5: ("Chime 2: Echoes", 125.0), 6: ("Sugar Skull", 171.47), 8: ("Jungle $lash", 30.44),
          10: ("Insane 1: Lunatic", 115.61)}


def dump_of(n):
    collector = DumpCollector()
    for msg in preset_select_section("preset_select_2.txt", n):
        collector.offer(msg)
    return collector


class TestReadTempo(unittest.TestCase):
    def test_the_recorded_presets(self):
        for n, (name, tempo) in TEMPOS.items():
            with self.subTest(preset=name):
                dump = dump_of(n)
                self.assertEqual(dump.name(), name)
                self.assertAlmostEqual(read_tempo(dump), tempo, places=2)

    def test_an_empty_dump(self):
        self.assertIsNone(read_tempo(DumpCollector()))

    def test_no_tempo_record(self):
        # Record 3 is the first float after the name; with it gone there is none.
        dump = dump_of(0)
        data = bytearray(dump.data())
        start = data.find(b"Bass") + len("Bass") + 1
        for o in range(start, start + 80, 10):
            if data[o] == 3 and data[o + 4] == 3:
                data[o] = 0x63                                  # some other id
        with mock.patch.object(DumpCollector, "data", return_value=bytes(data)):
            self.assertIsNone(read_tempo(dump))


if __name__ == "__main__":
    unittest.main()
