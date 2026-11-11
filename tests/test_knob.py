"""The preset knob's slot (silkline/protocol/knob.py, find_slot): which of slots 0 to 15
a knob click loaded, from the loaded preset's name (protocol.md section 11).

Marking m loads slot (m + 8) % 16, so position p is slot (p + 8) % 16; a click's last
reading is either right or its 4-bit flip (slot ^ 0x0F).
"""
import unittest

from silkline.protocol.knob import find_slot

KNOB = {0: "Bass", 1: "Acoustic", 4: "Chime 1: Class-A", 8: "Jungle $lash",
        9: "Chunk 2: Phat Chunk", 11: "Insane 2: Criminal", 16: "Brit Plexi 45"}


class TestFindSlot(unittest.TestCase):
    def test_a_unique_name_needs_no_reading(self):
        self.assertEqual(find_slot("Insane 2: Criminal", KNOB, None), 11)
        self.assertEqual(find_slot("Insane 2: Criminal", KNOB, 7), 11)    # a wrong reading doesn't matter

    def test_an_unknown_name(self):
        self.assertIsNone(find_slot("Not There", KNOB, 3))

    def test_only_slots_0_to_15_count(self):
        # Slot 16 isn't on the knob, even if its name matches.
        self.assertIsNone(find_slot("Brit Plexi 45", KNOB, 8))

    def test_a_duplicate_told_apart_by_the_reading(self):
        presets = {**KNOB, 9: "Chime 1: Class-A"}                       # Chime 1 at slots 4 and 9
        self.assertEqual(find_slot("Chime 1: Class-A", presets, 12), 4)  # position 12 is slot 4
        self.assertEqual(find_slot("Chime 1: Class-A", presets, 1), 9)   # position 1 is slot 9

    def test_a_duplicate_told_apart_by_the_flip(self):
        presets = {**KNOB, 9: "Chime 1: Class-A"}
        # Position 3 is slot 11 (not Chime 1); its flip is slot 4, which is.
        self.assertEqual(find_slot("Chime 1: Class-A", presets, 3), 4)

    def test_a_flip_pair_of_duplicates_cant_be_told(self):
        presets = {**KNOB, 11: "Chime 1: Class-A"}                      # slots 4 and 11: 4 ^ 0x0F == 11
        self.assertIsNone(find_slot("Chime 1: Class-A", presets, 12))
        self.assertIsNone(find_slot("Chime 1: Class-A", presets, 3))

    def test_a_duplicate_the_reading_doesnt_reach(self):
        presets = {**KNOB, 9: "Chime 1: Class-A"}
        self.assertIsNone(find_slot("Chime 1: Class-A", presets, 5))    # slot 13 / 2: neither
        self.assertIsNone(find_slot("Chime 1: Class-A", presets, None))


if __name__ == "__main__":
    unittest.main()
