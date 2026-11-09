import unittest
from dataclasses import FrozenInstanceError

from silkline.errors import AmpDisconnected, AmpError, AmpTimeout
from silkline.service import (
    AmpState,
    ConnectionState,
    Event,
    EventType,
)


class TestAmpState(unittest.TestCase):
    def test_defaults(self):
        state = AmpState()
        self.assertEqual(state.connection, ConnectionState.DISCONNECTED)
        self.assertIsNone(state.preset_number)
        self.assertIsNone(state.preset_name)
        self.assertIsNone(state.knob_position)
        self.assertEqual(state.params, {})
        self.assertIsNone(state.bpm)

    def test_states_do_not_share_params(self):
        amp1 = AmpState()
        amp2 = AmpState()
        amp1.params["test"] = 42
        self.assertNotIn("test", amp2.params)

    def test_snapshot_is_a_copy(self):
        amp = AmpState()
        amp.params["test"] = 42
        snapshot = amp.snapshot()
        self.assertIsInstance(snapshot, AmpState)
        self.assertEqual(snapshot.params, {"test": 42})
        snapshot.params["test"] = 43
        self.assertEqual(amp.params, {"test": 42})


class TestEvent(unittest.TestCase):
    def test_event_is_frozen(self):
        event = Event(EventType.TAP, {"bpm": 120.0})
        with self.assertRaises(FrozenInstanceError):
            event.data = {}


class TestErrors(unittest.TestCase):
    def test_errors_are_amp_errors(self):
        self.assertTrue(issubclass(AmpDisconnected, AmpError))
        self.assertTrue(issubclass(AmpTimeout, AmpError))


if __name__ == "__main__":
    unittest.main()
