import unittest

from silkline.service import AmpService, EventType
from tests.helpers import capture_messages as read_capture

# Real messages from the captures (see protocol.md).
TAP = "f000010c22054d003f00000f0005000000080000020004000000767a401d420000000000f7"
SAVE = "f000010c22054d00450001070003000000100000000002000000080000000002000000010000000000000000f7"
REVERB_LOW = "f000010c22054d005700010700040000001000000000740300002003010000040000000c400b0b3f00000000f7"   # about 0.543
REVERB_JITTER = "f000010c22054d006000010700040000001000000000740300002003010000040000000e400d0d3f00000000f7"  # about 0.551
AMP_02 = "f000010c22054d000b000107000400000010000000002a000000020000000004000000514031034d00000000f7"


class Recorder:
    """ A callback that keeps every event it receives. """
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)

    def of(self, event_type):
        return [e for e in self.events if e.event_type == event_type]


def make_service():
    service = AmpService()
    recorder = Recorder()
    service.on_change(recorder)
    return service, recorder


class TestHandleMessage(unittest.TestCase):
    def test_preset_clicks_give_sixteen_guesses(self):
        # Each click's status message settles a guess (the bounce rule); the position
        # itself now waits for the preset's dump (test_service_amp.TestKnobRefresh).
        service, recorder = make_service()
        guesses = []
        for msg in read_capture("preset_clicks.txt"):
            before = service._knob_candidates[:]
            service._handle_message(msg)
            if before and not service._knob_candidates:
                guesses.append(service._knob_guess)
                service._state.knob_position = service._knob_guess    # what the dump would set
        self.assertEqual(guesses, list(range(1, 16)) + [0])

    def test_small_jitter_is_ignored(self):
        service, recorder = make_service()
        service._handle_message(bytes.fromhex(REVERB_LOW))
        service._handle_message(bytes.fromhex(REVERB_JITTER))
        changes = recorder.of(EventType.PARAMETER_CHANGED)
        self.assertEqual(len(changes), 1)                      # only the first report
        self.assertEqual(changes[0].data["key"], (0x74, 0x20, 3))
        self.assertEqual(changes[0].data["name"], "Reverb")

    def test_big_change_is_reported(self):
        service, recorder = make_service()
        service._handle_message(bytes.fromhex(REVERB_LOW))
        bigger = bytearray.fromhex(REVERB_LOW)
        bigger[38] = 0x30                                      # third value byte: about 0.69
        service._handle_message(bytes(bigger))
        values = [e.data["value"] for e in recorder.of(EventType.PARAMETER_CHANGED)]
        self.assertEqual(len(values), 2)
        self.assertAlmostEqual(service.state().params[(0x74, 0x20, 3)], values[-1])

    def test_amp_02_is_ignored(self):
        service, recorder = make_service()
        service._handle_message(bytes.fromhex(AMP_02))
        self.assertEqual(recorder.events, [])
        self.assertNotIn((0x2A, 0x02, 0), service.state().params)

    def test_tap_sets_bpm(self):
        service, recorder = make_service()
        service._handle_message(bytes.fromhex(TAP))
        taps = recorder.of(EventType.TAP)
        self.assertEqual(len(taps), 1)
        self.assertAlmostEqual(taps[0].data["bpm"], 157.0)
        self.assertAlmostEqual(service.state().bpm, 157.0)

    def test_save_pressed(self):
        service, recorder = make_service()
        service._handle_message(bytes.fromhex(SAVE))
        self.assertEqual([e.event_type for e in recorder.events], [EventType.SAVE_PRESSED])

    def test_failing_callback_does_not_stop_others(self):
        service = AmpService()

        def broken(event):
            raise RuntimeError("boom")

        recorder = Recorder()
        service.on_change(broken)
        service.on_change(recorder)
        service._handle_message(bytes.fromhex(SAVE))
        self.assertEqual(len(recorder.events), 1)

    def test_callback_can_read_state(self):
        # If events were emitted while holding the lock, this would hang forever.
        service = AmpService()
        seen = []
        service.on_change(lambda event: seen.append(service.state().bpm))
        service._handle_message(bytes.fromhex(TAP))
        self.assertAlmostEqual(seen[0], 157.0)


if __name__ == "__main__":
    unittest.main()