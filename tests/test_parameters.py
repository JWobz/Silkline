"""The parameter list and how each kind of parameter is encoded for a set
(spiderweb/protocol/parameters.py, protocol.md section 8).
"""
import unittest

from spiderweb.protocol.messages import FLOAT_VALUE, SWITCH_VALUE
from spiderweb.protocol.parameters import BY_NAME, KNOWN_PARAMETERS, PARAMETERS
from spiderweb.protocol.values import decode_set_value


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
        self.assertEqual(self.STOMP.encode(1), (bytes([1, 0, 0, 0, 0]), SWITCH_VALUE))

    def test_off(self):
        self.assertEqual(self.STOMP.encode(0), (bytes(5), SWITCH_VALUE))

    def test_true_and_false_work_too(self):
        self.assertEqual(self.STOMP.encode(True), self.STOMP.encode(1))
        self.assertEqual(self.STOMP.encode(False), self.STOMP.encode(0))

    def test_anything_else_is_refused(self):
        for bad in (0.5, 2, -1):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.STOMP.encode(bad)

    def test_switch_value_type_is_what_the_app_sends(self):
        # msg[22] is 03 in every on/off set the app sends, 04 in float sets.
        self.assertEqual((SWITCH_VALUE, FLOAT_VALUE), (0x03, 0x04))


class TestEncodeFloat(unittest.TestCase):
    def test_in_range(self):
        raw5, value_type = BY_NAME["volume"].encode(0.5)
        self.assertEqual(value_type, FLOAT_VALUE)
        self.assertEqual(decode_set_value(raw5), 0.5)

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
        raw5, _ = gate.encode(50)
        self.assertEqual(decode_set_value(raw5), 50.0)
        for bad in (0.5, 10, 80):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    gate.encode(bad)


if __name__ == "__main__":
    unittest.main()
