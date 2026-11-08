"""Reading parameter values from a preset dump (protocol.md section 3, "The dump's layout").

The API these expect (spiderweb/protocol/dump.py):
  DumpCollector.data() -> bytes     each chunk unpacked and cut to its length, joined
  records(data) -> {(block, sub, record_id): value}     float for type 03, int otherwise
  read_values(dump) -> {(block, id, sub): value}         wire keys, as in parameters.py

The dumps are real: Chime from captures/chime_Drive.txt (taken after "set drive 0.9"),
Bass, Jungle $lash and Vibe 1 from captures/preset_select_2.txt. The expected values were
read with the reference parser in tools/dump_params.py.
"""
import unittest

from spiderweb.protocol.dump import DumpCollector, block_models, _find_blocks, read_values, records, stage_models
from spiderweb.protocol.parameters import BY_NAME
from tests.helpers import chime_dump, preset_select_section

GAIN = (0x2A, 0x25, 0)
BASS = (0x2A, 0x21, 0)
MID = (0x2A, 0x23, 0)
PRESENCE = (0x2A, 0x27, 0)
COMP_ON = (0x74, 0x4A, 3)
DRIVE = (0x2A, 0x26, 0)
TREBLE = (0x2A, 0x24, 0)
VOLUME = (0x74, 0x24, 3)
REVERB = (0x74, 0x20, 3)
FX_KNOBS = [(0x74, 0x1A, 3), (0x74, 0x1C, 3), (0x74, 0x1E, 3)]
FX_SWITCHES = [(0x74, 0x48, 3), (0x74, 0x47, 3), (0x74, 0x46, 3)]

# The wire keys read_values knows (protocol.md section 3, "Record id to wire id").

KNOWN = {GAIN, DRIVE, BASS, MID, TREBLE, PRESENCE, VOLUME, REVERB, COMP_ON, *FX_KNOBS, *FX_SWITCHES}


def collect(messages):
    collector = DumpCollector()
    for msg in messages:
        collector.offer(msg)
    assert collector.complete()
    return collector


def chime():
    return collect(chime_dump())


def selected(value):
    return collect(preset_select_section("preset_select_2.txt", value))


class TestData(unittest.TestCase):
    def test_each_chunk_cut_to_its_length(self):
        dump = chime()
        self.assertEqual(len(dump.data()), sum((c[10] << 4 | c[11]) + 1 for c in dump.chunks))
        self.assertEqual(len(dump.chunks), 6)

    def test_a_short_dump_keeps_its_last_chunk(self):
        # Vibe 1: Auto Wah ends at chunk 4 (277 bytes): 4 full chunks of 256, and the rest.
        vibe = selected(12)
        self.assertEqual(len(vibe.chunks), 5)
        self.assertGreater(len(vibe.data()), 4 * 256)

    def test_the_name_is_in_the_data(self):
        self.assertIn(b"Chime 1: Class-A", chime().data())


class TestRecords(unittest.TestCase):
    def test_the_amp_block(self):
        r = records(chime().data())
        self.assertAlmostEqual(r[(0x2A, 0, 0x1F)], 0.9004, places=3)     # Drive, after "set drive 0.9"
        self.assertAlmostEqual(r[(0x2A, 0, 0x1E)], 0.5569, places=3)
        self.assertAlmostEqual(r[(0x2A, 0, 0x1C)], 0.4431, places=3)

    def test_the_panel_block(self):
        r = records(chime().data())
        self.assertAlmostEqual(r[(0x74, 3, 0x3C)], 0.5922, places=3)     # Volume
        self.assertEqual(r[(0x74, 3, 0x26)], 1.0)                        # FX knob 1
        self.assertEqual(len([k for k in r if k[:2] == (0x74, 3)]), 25)

    def test_whole_numbers_are_ints(self):
        r = records(chime().data())
        self.assertEqual(r[(0x74, 3, 0x28)], 0)                          # FX1 off
        self.assertEqual(r[(0x74, 3, 0x2B)], 1)
        self.assertIsInstance(r[(0x74, 3, 0x2B)], int)
        self.assertEqual(r[(0x74, 3, 0x2D)], 1)                          # type 02, a choice

    def test_the_same_record_id_in_two_blocks(self):
        # Record ids are numbered per block: 0x1F is the amp's Drive and something else in 19:3.
        r = records(chime().data())
        self.assertAlmostEqual(r[(0x19, 3, 0x1F)], 0.6027, places=3)
        self.assertAlmostEqual(r[(0x2A, 0, 0x1F)], 0.9004, places=3)

    def test_every_block_is_found(self):
        blocks = {key[:2] for key in records(chime().data())}
        self.assertEqual(blocks, {(0x74, 3), (0x5E, 2), (0x04, 3), (0x0C, 3), (0x19, 3), (0x1B, 3),
                                  (0x1D, 3), (0x1F, 3), (0x2A, 0), (0x21, 3), (0x23, 3), (0x25, 3)})

    def test_a_short_dump_gives_the_blocks_it_has(self):
        r = records(selected(12).data())
        self.assertAlmostEqual(r[(0x74, 3, 0x3C)], 0.6268, places=3)
        self.assertAlmostEqual(r[(0x2A, 0, 0x33)], 0.57, places=3)

    def test_nothing_in_nothing_out(self):
        self.assertEqual(records(b""), {})
        self.assertEqual(records(bytes(300)), {})


class TestReadValues(unittest.TestCase):
    def test_chime(self):
        v = read_values(chime())
        self.assertAlmostEqual(v[GAIN], 0.9004, places=3)
        self.assertAlmostEqual(v[TREBLE], 0.5569, places=3)
        self.assertAlmostEqual(v[VOLUME], 0.5922, places=3)
        self.assertAlmostEqual(v[REVERB], 0.5412, places=3)
        self.assertEqual([round(v[k], 3) for k in FX_KNOBS], [1.0, 0.501, 0.419])
        self.assertEqual([v[k] for k in FX_SWITCHES], [0, 0, 0])

    def test_a_preset_has_only_the_drive_it_uses(self):
        # Chime has Gain (0x25); Bass and Jungle $lash have Drive (0x26) (protocol.md section 3, point 5).
        self.assertIn(GAIN, read_values(chime()))
        self.assertNotIn(DRIVE, read_values(chime()))
        for value, drive in ((0, 0.6226), (8, 0.7643)):
            v = read_values(selected(value))
            self.assertNotIn(GAIN, v)
            self.assertAlmostEqual(v[DRIVE], drive, places=3)

    def test_bass_and_jungle(self):
        bass, jungle = read_values(selected(0)), read_values(selected(8))
        self.assertAlmostEqual(bass[VOLUME], 0.7022, places=3)
        self.assertAlmostEqual(bass[REVERB], 0.5008, places=3)
        self.assertAlmostEqual(jungle[VOLUME], 0.2404, places=3)
        self.assertAlmostEqual(jungle[REVERB], 0.2915, places=3)

    def test_switches_that_are_on(self):
        v = read_values(selected(12))                                     # Vibe 1: FX1 and FX2 on
        self.assertEqual([v[k] for k in FX_SWITCHES], [1, 1, 0])

    def test_bass_and_mid_from_their_state_records(self):
        # BassState 0x1C and MidState 0x1D in the symbol table (protocol.md section 3).
        chime_values, bass = read_values(chime()), read_values(selected(0))
        self.assertAlmostEqual(chime_values[BASS], 0.4431, places=3)
        self.assertAlmostEqual(chime_values[MID], 0.5386, places=3)
        self.assertAlmostEqual(bass[BASS], 0.5053, places=3)
        self.assertAlmostEqual(bass[MID], 0.4136, places=3)

    def test_comp_on(self):
        # Chime's compressor is on (captures/windows/session_log.txt).
        self.assertEqual(read_values(chime())[COMP_ON], 1)

    def test_only_known_parameters(self):
        # Records not matched to a wire id (most of the other blocks, so far) are left out.
        for dump in (chime(), selected(0), selected(8), selected(12)):
            self.assertLessEqual(set(read_values(dump)), KNOWN)

    def test_an_empty_collector_gives_nothing(self):
        self.assertEqual(read_values(DumpCollector()), {})


class TestFindBlocks(unittest.TestCase):
    """ _find_blocks(data): every block start, as (block, sub, model, count, start), in
    order. records() and block_models() are built on it. """

    def test_chime(self):
        blocks = _find_blocks(chime().data())
        self.assertEqual(len(blocks), 13)
        block, sub, model, count, start = blocks[0]
        self.assertEqual((block, sub, model, count), (0x74, 3, 0x316, 25))      # the panel
        self.assertEqual([(b, s) for b, s, *_ in blocks][:3], [(0x74, 3), (0x5E, 2), (0x04, 3)])

    def test_start_is_the_first_record(self):
        # Right after the three 10-byte info records (03, 05, 06).
        data = chime().data()
        for block, sub, model, count, start in _find_blocks(data):
            with self.subTest(block=hex(block)):
                self.assertEqual([data[start - 30], data[start - 20], data[start - 10]], [3, 5, 6])

    def test_agrees_with_block_models_and_records(self):
        data = chime().data()
        blocks = _find_blocks(data)
        self.assertEqual({(b, s): m for b, s, m, _, _ in blocks}, block_models(data))
        # every block records() read from is one _find_blocks found (a block with no records has none)
        self.assertLessEqual({(b, s) for b, s, _ in records(data)}, {(b, s) for b, s, *_ in blocks})

    def test_a_made_up_block(self):
        info = (bytes([3, 0, 0, 0x80, 7, 0]) + (0x2A).to_bytes(4, "little")
                + bytes([5, 0, 0, 0x80, 7, 0]) + (0xCA).to_bytes(4, "little")
                + bytes([6, 0, 0, 0x80, 7, 0]) + (2).to_bytes(4, "little"))
        self.assertEqual(_find_blocks(b"junk" + info), [(0x2A, 0, 0xCA, 2, 34)])

    def test_nothing(self):
        self.assertEqual(_find_blocks(b""), [])
        self.assertEqual(_find_blocks(bytes(300)), [])
class TestBlockModels(unittest.TestCase):
    """ block_models(data): each block's model number, from the 05 info record at its
    start (protocol.md section 3, "The dump's layout"). """

    def test_chime_has_13_blocks(self):
        blocks = block_models(chime().data())
        self.assertEqual(len(blocks), 13)
        self.assertEqual(blocks[(0x74, 3)], 0x316)      # the panel: SpiderVGuitarFlow
        self.assertEqual(blocks[(0x21, 3)], 0)          # TNGAIRReflections

    def test_every_preset_has_the_same_13_blocks(self):
        expected = set(block_models(chime().data()))
        for value in (0, 8, 12):
            with self.subTest(preset=value):
                self.assertEqual(set(block_models(selected(value).data())), expected)

    def test_the_last_chunk_counts(self):
        # Vibe 1's last three blocks are in its short last chunk; data() keeps it.
        vibe = selected(12)
        self.assertEqual(len(block_models(vibe.data())), 13)

    def test_a_made_up_block(self):
        info = (bytes([3, 0, 0, 0x80, 7, 0]) + (0x2A).to_bytes(4, "little")
                + bytes([5, 0, 0, 0x80, 7, 0]) + (0xCA).to_bytes(4, "little")
                + bytes([6, 0, 0, 0x80, 7, 0]) + (0).to_bytes(4, "little"))
        self.assertEqual(block_models(b"junk" + info), {(0x2A, 0): 0xCA})

    def test_nothing(self):
        self.assertEqual(block_models(b""), {})
        self.assertEqual(block_models(bytes(300)), {})


class TestStageModels(unittest.TestCase):
    """ stage_models(dump): {stage: model number} for the 11 stages people pick. """

    STAGE_NAMES = {"gate", "vol", "wah", "stomp", "mod", "delay", "reverb", "amp", "cab", "comp", "eq"}

    def test_chime(self):
        self.assertEqual(stage_models(chime()), {
            "gate": 0x25E, "vol": 0x304, "wah": 0x312, "stomp": 0x22B, "mod": 0x193, "delay": 0x1DE,
            "reverb": 0x25C, "amp": 0xDC, "cab": 0x2C1, "comp": 0x261, "eq": 0x269})

    def test_bass_and_vibe(self):
        # Amps from the user's notes: Bass is the Tube Instrument Preamp (L6TubePreamp).
        bass, vibe = stage_models(selected(0)), stage_models(selected(12))
        self.assertEqual((bass["amp"], bass["stomp"], bass["reverb"]), (0xBF, 0x219, 0x258))
        self.assertEqual((vibe["amp"], vibe["wah"], vibe["mod"]), (0xB2, 0x30B, 0x1A6))

    def test_every_stage_every_time(self):
        for dump in (chime(), selected(0), selected(8), selected(12)):
            self.assertEqual(set(stage_models(dump)), self.STAGE_NAMES)

    def test_the_fixed_stages_never_change(self):
        for dump in (chime(), selected(0), selected(8), selected(12)):
            m = stage_models(dump)
            self.assertEqual((m["gate"], m["vol"], m["comp"], m["eq"]), (0x25E, 0x304, 0x261, 0x269))

    def test_the_names_match_the_on_off_parameters(self):
        # "Stomp On", "Comp On"... so a UI can pair a stage with its switch.
        for stage in self.STAGE_NAMES - {"amp", "cab"}:
            with self.subTest(stage=stage):
                self.assertIn(f"{stage} on", BY_NAME)

    def test_an_empty_dump(self):
        self.assertEqual(stage_models(DumpCollector()), {})


if __name__ == "__main__":
    unittest.main()
