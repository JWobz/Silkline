"""Phase 4 tests: AmpService on top of a real Amp and Connection.

The amp is the FakeTransport from test_connection.py, answering with real
captures. handle_message itself is tested in test_service_handler.py.
"""
import threading
import unittest

from spiderweb.amp import Amp
from spiderweb.connection import Connection
from spiderweb.errors import AmpDisconnected, AmpTimeout
from spiderweb.protocol.messages import (
    DUMP_REQUEST,
    MessageKind,
    build_begin_message,
    build_set_message,
    classify,
    select_message,
)
from spiderweb.protocol.parameters import BY_NAME
from spiderweb.protocol.values import encode_set_value
from spiderweb.service import AmpService, ConnectionState, EventType
from tests.test_connection import FakeTransport, capture_messages
from tests.test_dump import preset_select_section
from tests.test_presets import ACOUSTIC, BASS_LONG, LONG_0, SHORT_0, SHORT_5, USER_1

TAP = bytes.fromhex("f000010c22054d003f00000f0005000000080000020004000000767a401d420000000000f7")       # 157 bpm
DRIVE_REPORT = bytes.fromhex(
    "f000010c22054d0008000107000400000010000000002a0000002500010000040000007f407e7e3f00000000f7")   # Drive, about 0.99
DRIVE = BY_NAME["drive"]


def chime_dump():
    """ A real dump of Chime 1: Class-A, mixed with other messages. """
    return capture_messages("chime_Drive.txt")


def bass_dump():
    """ What came back after selecting value 0 (Bass) from the Pi. """
    return preset_select_section("preset_select_2.txt", 0)


def first_click():
    """ One preset-knob click from preset_clicks.txt: its preset-change messages, up to the status message. """
    messages, seen_change = [], False
    for msg in capture_messages("preset_clicks.txt"):
        kind = classify(msg)[0]
        if kind == MessageKind.PRESET_CHANGE:
            seen_change = True
        if seen_change:
            messages.append(msg)
            if kind == MessageKind.STATUS:
                return messages
    raise AssertionError("no click found in preset_clicks.txt")


def a_preset_list_message():
    """ A preset-list entry from the handshake (classified as PRESET_INFO). """
    for msg in chime_dump():
        if classify(msg)[0] == MessageKind.PRESET_INFO:
            return msg
    raise AssertionError("no preset-list message in the capture")


class Events:
    """ A thread-safe on_change callback that keeps every event and can wait for one. """
    def __init__(self):
        self.events = []
        self._arrived = threading.Condition()

    def __call__(self, event):
        with self._arrived:
            self.events.append(event)
            self._arrived.notify_all()

    def of(self, event_type):
        with self._arrived:
            return [e for e in self.events if e.event_type == event_type]

    def wait_for(self, check, timeout=2.0):
        with self._arrived:
            return self._arrived.wait_for(lambda: any(check(e) for e in self.events), timeout)

    def connection_states(self):
        return [e.data["state"] for e in self.of(EventType.CONNECTION_CHANGED)]


class AnswersDumps:
    """ auto_reply for the fake: answers each dump request with `dump` (changeable),
    the messages in `others` with their replies, and nothing else. """
    def __init__(self, dump=(), others=None):
        self.dump = list(dump)
        self.others = others or {}

    def __call__(self, msg):
        if msg == DUMP_REQUEST:
            return self.dump
        return self.others.get(msg, [])


class ServiceTest(unittest.TestCase):
    """ Gives each test a fake amp and a service built on it, and always stops it.

    `handshake_dump` is what the amp sends back for the handshake's dump request
    (handshake line 8); `dump` is what it sends for every later dump request.
    `preset_list` maps preset-list requests to the replies the amp sends for them;
    they go in the handshake ahead of the dump request, as in the real one.
    """
    def make(self, handshake_dump=(), dump=(), start=True, preset_list=None):
        preset_list = preset_list or {}
        self.replies = AnswersDumps(handshake_dump, others=preset_list)
        self.fake = FakeTransport(auto_reply=self.replies)
        self.amps_made = 0
        handshake = list(preset_list) + [DUMP_REQUEST]

        def factory():
            self.amps_made += 1
            return Amp(Connection(handshake, transport_factory=lambda: self.fake))

        self.service = AmpService(amp_factory=factory)
        self.events = Events()
        self.service.on_change(self.events)
        self.addCleanup(self.service.stop)
        if start:
            self.service.start()
        self.replies.dump = list(dump)       # from now on, later dump requests get this
        self.fake.sent.clear()
        return self.service, self.fake, self.events

    def sync(self):
        """ Waits until the reader has handled everything sent so far (a tap goes last). """
        count = len(self.events.of(EventType.TAP))
        self.fake.arrive(TAP)
        self.assertTrue(self.events.wait_for(lambda e: len(self.events.of(EventType.TAP)) > count))


class TestStartStop(ServiceTest):
    def test_start_connects(self):
        service, fake, events = self.make()
        self.assertEqual(events.connection_states(), [ConnectionState.CONNECTING, ConnectionState.CONNECTED])
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)

    def test_making_a_service_touches_nothing(self):
        service, fake, events = self.make(start=False)
        self.assertEqual(self.amps_made, 0)
        self.assertEqual(events.events, [])

    def test_preset_name_comes_from_the_handshake_dump(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        self.assertEqual(service.state().preset_name, "Chime 1: Class-A")
        self.assertEqual(fake.sent, [])               # no extra dump request needed

    def test_no_dump_in_the_handshake_is_fine(self):
        service, fake, events = self.make()
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)
        self.assertIsNone(service.state().preset_name)

    def test_handshake_replies_are_not_handled_as_events(self):
        # The handshake capture is full of parameter reports; they set up the session, they aren't changes.
        service, fake, events = self.make(handshake_dump=chime_dump())
        self.assertEqual(events.of(EventType.PARAMETER_CHANGED), [])

    def test_messages_after_start_are_handled(self):
        service, fake, events = self.make()
        fake.arrive(TAP)
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.TAP))
        self.assertAlmostEqual(service.state().bpm, 157.0)

    def test_start_twice_does_nothing(self):
        service, fake, events = self.make()
        service.start()
        self.assertEqual(self.amps_made, 1)
        self.assertEqual(events.connection_states(), [ConnectionState.CONNECTING, ConnectionState.CONNECTED])

    def test_failed_start_ends_disconnected_and_can_be_retried(self):
        service, fake, events = self.make(start=False)
        fake.fail_send = True                          # the handshake can't be sent
        with self.assertRaises(OSError):
            service.start()
        self.assertEqual(service.state().connection, ConnectionState.DISCONNECTED)
        self.assertEqual(events.connection_states()[-1], ConnectionState.DISCONNECTED)
        fake.fail_send = False
        service.start()
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)

    def test_stop_disconnects_and_closes(self):
        service, fake, events = self.make()
        service.stop()
        self.assertTrue(fake.closed)
        self.assertEqual(service.state().connection, ConnectionState.DISCONNECTED)
        self.assertEqual(events.connection_states()[-1], ConnectionState.DISCONNECTED)

    def test_stop_twice_is_harmless(self):
        service, fake, events = self.make()
        service.stop()
        service.stop()
        self.assertEqual(events.connection_states().count(ConnectionState.DISCONNECTED), 1)

    def test_stop_without_start_is_harmless(self):
        service, fake, events = self.make(start=False)
        service.stop()
        self.assertEqual(events.events, [])


class TestPresets(ServiceTest):
    # Short index 0 gets no reply (as on the real amp), so its name comes from the long list.
    PRESET_LIST = {SHORT_0: [], LONG_0: [BASS_LONG], SHORT_5: [TAP, ACOUSTIC]}

    def test_no_presets_before_start(self):
        service, fake, events = self.make(start=False, preset_list=self.PRESET_LIST)
        self.assertEqual(service.presets(), {})

    def test_presets_come_from_the_handshake(self):
        service, fake, events = self.make(preset_list=self.PRESET_LIST)
        self.assertEqual(service.presets(), {0: "Bass", 5: "Acoustic"})
        self.assertEqual(fake.sent, [])               # nothing extra asked for after the handshake

    def test_presets_dont_need_the_handshake_dump(self):
        # No dump came back, so no preset name, but the list is still there.
        service, fake, events = self.make(preset_list=self.PRESET_LIST)
        self.assertIsNone(service.state().preset_name)
        self.assertEqual(service.presets(), {0: "Bass", 5: "Acoustic"})

    def test_presets_and_preset_name_together(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), preset_list=self.PRESET_LIST)
        self.assertEqual(service.state().preset_name, "Chime 1: Class-A")
        self.assertEqual(service.presets(), {0: "Bass", 5: "Acoustic"})

    def test_a_handshake_without_a_preset_list_gives_none(self):
        service, fake, events = self.make()
        self.assertEqual(service.presets(), {})

    def test_presets_returns_a_copy(self):
        service, fake, events = self.make(preset_list=self.PRESET_LIST)
        service.presets()[0] = "changed"
        service.presets().clear()
        self.assertEqual(service.presets(), {0: "Bass", 5: "Acoustic"})

    def test_preset_list_entries_after_start_are_ignored(self):
        service, fake, events = self.make(preset_list=self.PRESET_LIST)
        fake.arrive(USER_1)
        self.sync()
        self.assertEqual(service.presets(), {0: "Bass", 5: "Acoustic"})
        self.assertEqual(events.of(EventType.PRESET_CHANGED), [])

    def test_restart_after_stop(self):
        service, fake, events = self.make()
        service.stop()
        service.start()
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)
        fake.arrive(TAP)
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.TAP))


class TestSetGet(ServiceTest):
    def test_set_sends_the_parameter(self):
        service, fake, events = self.make()
        service.set("drive", 0.5)
        self.assertEqual(fake.sent, [
            build_begin_message(0x0C),
            build_set_message(0x0D, DRIVE.block, DRIVE.sub, DRIVE.id, encode_set_value(0.5)),
        ])

    def test_names_are_not_case_sensitive(self):
        service, fake, events = self.make()
        service.set("DRIVE", 0.5)
        self.assertEqual(len(fake.sent), 2)
        self.assertIsNone(service.get("Drive"))

    def test_state_changes_when_the_amp_reports_not_when_we_send(self):
        service, fake, events = self.make()
        service.set("drive", 0.5)
        self.assertIsNone(service.get("drive"))        # nothing reported yet
        fake.arrive(DRIVE_REPORT)
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PARAMETER_CHANGED))
        self.assertAlmostEqual(service.get("drive"), 0.99, places=2)
        self.assertEqual(events.of(EventType.PARAMETER_CHANGED)[0].data["name"], "Drive")

    def test_unknown_name_is_refused(self):
        service, fake, events = self.make()
        with self.assertRaises(ValueError):
            service.set("wah", 0.5)
        with self.assertRaises(ValueError):
            service.get("wah")
        self.assertEqual(fake.sent, [])

    def test_not_settable_is_refused(self):
        service, fake, events = self.make()
        with self.assertRaises(ValueError):
            service.set("tap (hold)", 0.5)
        self.assertEqual(fake.sent, [])

    def test_out_of_range_is_refused(self):
        service, fake, events = self.make()
        with self.assertRaises(ValueError):
            service.set("drive", 1.5)
        self.assertEqual(fake.sent, [])

    def test_set_before_start_fails_fast(self):
        service, fake, events = self.make(start=False)
        with self.assertRaises(AmpDisconnected):
            service.set("drive", 0.5)

    def test_get_before_start_is_none(self):
        service, fake, events = self.make(start=False)
        self.assertIsNone(service.get("drive"))


class TestSelectPreset(ServiceTest):
    def test_select_returns_the_name(self):
        service, fake, events = self.make(dump=bass_dump())
        self.assertEqual(service.select_preset(0), "Bass")
        self.assertEqual(fake.sent, [select_message(0), DUMP_REQUEST])

    def test_select_updates_state(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), dump=bass_dump())
        service.select_preset(0)
        state = service.state()
        self.assertEqual(state.preset_number, 0)
        self.assertEqual(state.preset_name, "Bass")

    def test_select_emits_preset_changed(self):
        service, fake, events = self.make(dump=bass_dump())
        service.select_preset(0)
        changed = events.of(EventType.PRESET_CHANGED)
        self.assertEqual(changed[-1].data, {"number": 0, "name": "Bass"})

    def test_select_with_no_dump_times_out_and_changes_nothing(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        with self.assertRaises(AmpTimeout):
            service.select_preset(0)
        self.assertEqual(service.state().preset_name, "Chime 1: Class-A")
        self.assertEqual(events.of(EventType.PRESET_CHANGED), [])

    def test_select_before_start_fails_fast(self):
        service, fake, events = self.make(start=False)
        with self.assertRaises(AmpDisconnected):
            service.select_preset(0)


class TestKnobRefresh(ServiceTest):
    def test_a_knob_click_refreshes_the_name(self):
        service, fake, events = self.make(dump=chime_dump())
        fake.arrive(*first_click())
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PRESET_CHANGED))
        self.assertEqual(events.of(EventType.PRESET_CHANGED)[0].data, {"number": None, "name": "Chime 1: Class-A"})
        self.assertEqual(service.state().preset_name, "Chime 1: Class-A")

    def test_a_knob_click_still_reports_the_position(self):
        service, fake, events = self.make(dump=chime_dump())
        fake.arrive(*first_click())
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.KNOB_MOVED))
        self.assertEqual(service.state().knob_position, events.of(EventType.KNOB_MOVED)[0].data["position"])

    def test_a_knob_click_asks_for_a_dump(self):
        service, fake, events = self.make(dump=chime_dump())
        fake.arrive(*first_click())
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PRESET_CHANGED))
        self.assertEqual(fake.sent, [DUMP_REQUEST])

    def test_knob_refresh_clears_the_select_number(self):
        # The number is a select value; after a knob move we don't know it any more.
        service, fake, events = self.make(dump=bass_dump())
        service.select_preset(0)
        self.replies.dump = chime_dump()
        fake.arrive(*first_click())
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PRESET_CHANGED
                                        and e.data["name"] == "Chime 1: Class-A"))
        self.assertIsNone(service.state().preset_number)

    def test_preset_list_messages_do_not_change_the_name(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        fake.arrive(a_preset_list_message())
        self.sync()
        self.assertEqual(service.state().preset_name, "Chime 1: Class-A")
        self.assertEqual(events.of(EventType.PRESET_CHANGED), [])


class TestLost(ServiceTest):
    def test_unplug_disconnects(self):
        service, fake, events = self.make()
        fake.arrive(OSError("unplugged"))
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                                        and e.data["state"] == ConnectionState.DISCONNECTED))
        self.assertEqual(service.state().connection, ConnectionState.DISCONNECTED)

    def test_the_event_says_why(self):
        service, fake, events = self.make()
        fake.arrive(OSError("unplugged"))
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                                        and "error" in e.data))
        lost = [e for e in events.of(EventType.CONNECTION_CHANGED) if "error" in e.data][0]
        self.assertIn("unplugged", lost.data["error"])

    def test_commands_after_unplug_fail_fast(self):
        service, fake, events = self.make()
        fake.arrive(OSError("unplugged"))
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                                        and e.data["state"] == ConnectionState.DISCONNECTED))
        with self.assertRaises(AmpDisconnected):
            service.set("drive", 0.5)
        with self.assertRaises(AmpDisconnected):
            service.select_preset(0)

    def test_stop_after_unplug_still_closes(self):
        service, fake, events = self.make()
        fake.arrive(OSError("unplugged"))
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                                        and e.data["state"] == ConnectionState.DISCONNECTED))
        service.stop()
        self.assertTrue(fake.closed)

    def test_start_again_after_unplug(self):
        service, fake, events = self.make()
        fake.arrive(OSError("unplugged"))
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                                        and e.data["state"] == ConnectionState.DISCONNECTED))
        service.stop()
        service.start()
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)


if __name__ == "__main__":
    unittest.main()
