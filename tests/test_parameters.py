"""The parameter list and how each kind of parameter is encoded for a set
(silkline/protocol/parameters.py, protocol.md section 8).
"""
import unittest

from silkline.protocol.messages import FLOAT_VALUE, SWITCH_VALUE
from silkline.protocol.parameters import BY_NAME, DUMP_RECORDS, KNOWN_PARAMETERS, PARAMETERS
import struct


class TestRecords(unittest.TestCase):
    """ Parameter.record: the dump record holding its value (protocol.md section 8, found on
    the amp 2026-11-09). DUMP_RECORDS is built from it. """

    # (name, record) from the amp run (captures/dump_params_2.txt, _3.txt) and earlier dumps.
    AMP_RUN = {
        "Gain": 0x1F, "Drive": 0x33, "Bass": 0x1C, "Mid": 0x1D, "Treble": 0x1E, "Presence": 0x20,
        "Volume": 0x3C, "Reverb": 0x32, "Stomp Knob": 0x26, "Mod Knob": 0x2A, "Delay Knob": 0x2E,
        "Gate On": 0x38, "Wah On": 0x3B, "Stomp On": 0x28, "Mod On": 0x2C, "Comp On": 0x3D,
        "EQ On": 0x3E, "Vol On": 0x3A, "Delay On": 0x30, "Reverb On": 0x34,
        "Gate Threshold": 0x5F, "Gate Decay": 0x21, "Vol Min": 0x06, "Vol Max": 0x07,
        "Comp Threshold": 0x62, "Comp Gain": 0x1F, "EQ Low Freq": 0x6A, "EQ Low Gain": 0x6B,
        "EQ Low-Mid Freq": 0x6C, "EQ Low-Mid Gain": 0x6D, "EQ High-Mid Freq": 0x6E,
        "EQ High-Mid Gain": 0x1F, "EQ High Freq": 0x6F, "EQ High Gain": 0x70,
        "Reverb Time": 0x21, "Reverb Tone": 0x45, "Reverb Mix": 0x75,
    }

    def test_every_settable_parameter_has_its_record(self):
        self.assertEqual({p.name: p.record for p in PARAMETERS if p.settable}, self.AMP_RUN)

    def test_tap_has_none(self):
        self.assertIsNone(BY_NAME["tap (hold)"].record)

    def test_dump_records_is_built_from_them(self):
        self.assertEqual(len(DUMP_RECORDS), 37)
        for p in PARAMETERS:
            if p.record is not None:
                with self.subTest(p.name):
                    self.assertEqual(DUMP_RECORDS[(p.block, p.sub, p.record)], p.key)

    def test_no_two_parameters_share_a_record(self):
        # 0x1F is in three blocks (Gain, Comp Gain, EQ High-Mid Gain): fine, the block is
        # part of the key. Within one block a record holds one parameter.
        places = [(p.block, p.sub, p.record) for p in PARAMETERS if p.record is not None]
        self.assertEqual(len(places), len(set(places)))

    def test_eq_high_gain_is_symbol_0x282(self):
        # The app sends it with the id's top bit in msg[12] (protocol.md section 8).
        self.assertEqual(BY_NAME["eq high gain"].symbol, 0x282)


class TestTheList(unittest.TestCase):
    def test_names_are_unique(self):
        names = [p.name.lower() for p in PARAMETERS]
        self.assertEqual(len(names), len(set(names)))

    def test_keys_are_unique(self):
        # Two entries with one key would share a value in AmpState.params.
        keys = [p.key for p in PARAMETERS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_key_uses_the_namespace_like_the_amps_reports(self):
        # Reports carry (block, id, namespace) (classify, msg[22], msg[26], msg[27]).
        self.assertEqual(BY_NAME["reverb mix"].key, (0x1F, 0x7A, 1))
        self.assertEqual(KNOWN_PARAMETERS[(0x1F, 0x7A, 1)], "Reverb Mix")

    def test_symbol_is_namespace_and_id(self):
        # protocol.md section 8: the set names a parameter by its symbol.
        self.assertEqual(BY_NAME["volume"].symbol, 0x324)
        self.assertEqual(BY_NAME["reverb mix"].symbol, 0x17A)
        self.assertEqual(BY_NAME["gain"].symbol, 0x025)

    def test_kinds_are_float_or_switch(self):
        for p in PARAMETERS:
            with self.subTest(p.name):
                self.assertIn(p.kind, ("float", "switch"))
                self.assertLess(p.low, p.high)

    def test_every_stage_has_a_switch(self):
        for stage in ("gate", "wah", "stomp", "mod", "comp", "eq", "vol", "delay", "reverb"):
            with self.subTest(stage):
                p = BY_NAME[f"{stage} on"]
                self.assertEqual((p.block, p.sub, p.namespace, p.kind), (0x74, 3, 3, "switch"))


class TestEncodeSwitch(unittest.TestCase):
    STOMP = BY_NAME["stomp on"]

    def test_on(self):
        self.assertEqual(self.STOMP.encode(1), (bytes([1, 0, 0, 0]), SWITCH_VALUE))

    def test_off(self):
        self.assertEqual(self.STOMP.encode(0), (bytes(4), SWITCH_VALUE))

    def test_true_and_false_work_too(self):
        self.assertEqual(self.STOMP.encode(True), self.STOMP.encode(1))
        self.assertEqual(self.STOMP.encode(False), self.STOMP.encode(0))

    def test_anything_else_is_refused(self):
        for bad in (0.5, 2, -1):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.STOMP.encode(bad)

    def test_switch_value_type_is_what_the_app_sends(self):
        # The value type is 3 in every on/off set the app sends, 4 in float sets.
        self.assertEqual((SWITCH_VALUE, FLOAT_VALUE), (0x03, 0x04))


class TestEncodeFloat(unittest.TestCase):
    def test_in_range(self):
        value, value_type = BY_NAME["volume"].encode(0.5)
        self.assertEqual(value_type, FLOAT_VALUE)
        self.assertEqual(value, struct.pack("<f", 0.5))

    def test_the_ends_are_allowed(self):
        for value in (0.0, 1.0):
            BY_NAME["volume"].encode(value)

    def test_out_of_range_is_refused(self):
        for bad in (-0.1, 1.5):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    BY_NAME["volume"].encode(bad)

    def test_gate_threshold_has_its_own_range(self):
        gate = BY_NAME["gate threshold"]
        value, _ = gate.encode(50)
        self.assertEqual(value, struct.pack("<f", 50.0))
        for bad in (0.5, 10, 80):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    gate.encode(bad)


if __name__ == "__main__":
    unittest.main()
