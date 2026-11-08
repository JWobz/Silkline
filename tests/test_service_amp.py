"""Phase 4 tests: AmpService on top of a real Amp and Connection.

The amp is the FakeTransport from helpers.py, answering with real
captures. handle_message itself is tested in test_service_handler.py.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

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
from spiderweb.protocol.values import decode_set_value, encode_set_value
from spiderweb.protocol.dump import DumpCollector, preset_data
from spiderweb.service import AmpService, ConnectionState, EventType
from tests.test_symbols import make_table
from tests.helpers import (
    ACOUSTIC,
    BASS_LONG,
    GAIN_REPORT,
    LONG_0,
    SET_ANSWER,
    AnswersUploads,
    SHORT_0,
    SHORT_5,
    TAP,
    USER_1,
    Events,
    FakeTransport,
    bass_dump,
    chime_dump,
    first_click,
    is_set,
    is_upload_header,
)

GAIN = BY_NAME["gain"]
DRIVE = BY_NAME["drive"]


def a_preset_list_message():
    """ A preset-list entry from the handshake (classified as PRESET_INFO). """
    for msg in chime_dump():
        if classify(msg)[0] == MessageKind.PRESET_INFO:
            return msg
    raise AssertionError("no preset-list message in the capture")


class AnswersDumps:
    """ auto_reply for the fake: answers each dump request with `dump` (changeable), each
    set with the amp's set answer (unless answer_sets is False), the messages in `others`
    with their replies, and nothing else. """
    def __init__(self, dump=(), others=None):
        self.dump = list(dump)
        self.others = others or {}
        self.answer_sets = True

    def __call__(self, msg):
        if msg == DUMP_REQUEST:
            return self.dump
        if is_set(msg):
            return [SET_ANSWER] if self.answer_sets else []
        return self.others.get(msg, [])


class ServiceTest(unittest.TestCase):
    """ Gives each test a fake amp and a service built on it, and always stops it.

    `handshake_dump` is what the amp sends back for the handshake's dump request
    (handshake line 8); `dump` is what it sends for every later dump request.
    `preset_list` maps preset-list requests to the replies the amp sends for them;
    they go in the handshake ahead of the dump request, as in the real one.
    `resource_folder` is where the Line 6 app's files are; None (the default) loads none,
    so models have numbers only.
    """
    def make(self, handshake_dump=(), dump=(), start=True, preset_list=None, resource_folder=None):
        preset_list = preset_list or {}
        self.replies = AnswersDumps(handshake_dump, others=preset_list)
        self.fake = FakeTransport(auto_reply=self.replies)
        self.amps_made = 0
        handshake = list(preset_list) + [DUMP_REQUEST]

        def factory():
            self.amps_made += 1
            return Amp(Connection(handshake, transport_factory=lambda: self.fake))

        self.service = AmpService(amp_factory=factory, resource_folder=resource_folder)
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


def request_for(index):
    """ A short-list preset-list request for `index` (SHORT_5 with msg[22] changed, protocol.md section 4). """
    msg = bytearray(SHORT_5)
    msg[22] = index
    return bytes(msg)


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

    def test_preset_115_is_left_out(self):
        # The amp lists 115 ("DirtyAcoBlues") but never loads it (protocol.md section 8).
        service, fake, events = self.make(preset_list={**self.PRESET_LIST, request_for(115): [USER_1]})
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
            build_set_message(0x0D, DRIVE.block, DRIVE.sub, DRIVE.id, encode_set_value(0.5), DRIVE.namespace),
        ])

    def test_names_are_not_case_sensitive(self):
        service, fake, events = self.make()
        service.set("DRIVE", 0.5)
        self.assertEqual(len(fake.sent), 2)
        self.assertEqual(service.get("Drive"), 0.5)

    def test_set_records_the_value_once_answered(self):
        # The amp never reports a set back (protocol.md section 8), so the service
        # records what it sent once the amp has answered.
        service, fake, events = self.make()
        service.set("drive", 0.5)
        self.assertEqual(service.get("drive"), 0.5)
        self.assertEqual(service.state().params[DRIVE.key], 0.5)

    def test_set_sends_parameter_changed(self):
        service, fake, events = self.make()
        service.set("drive", 0.5)
        changes = events.of(EventType.PARAMETER_CHANGED)
        self.assertEqual([e.data for e in changes], [{"key": DRIVE.key, "name": "Drive", "value": 0.5}])

    def test_an_unanswered_set_changes_nothing(self):
        service, fake, events = self.make()
        self.replies.answer_sets = False
        with self.assertRaises(AmpTimeout):
            service.set("drive", 0.5)
        self.assertIsNone(service.get("drive"))
        self.assertEqual(events.of(EventType.PARAMETER_CHANGED), [])

    def test_a_knob_report_after_a_set_still_counts(self):
        service, fake, events = self.make()
        service.set("gain", 0.5)
        fake.arrive(GAIN_REPORT)                       # the Gain knob turned to about 0.99
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PARAMETER_CHANGED
                                        and e.data["value"] > 0.9))
        self.assertAlmostEqual(service.get("gain"), 0.99, places=2)

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

    def test_each_parameter_has_its_own_range(self):
        service, fake, events = self.make()
        service.set("gate threshold", 50)
        self.assertEqual(service.get("gate threshold"), 50)
        with self.assertRaises(ValueError):
            service.set("gate threshold", 0.5)

    def test_a_switch_takes_0_or_1(self):
        service, fake, events = self.make()
        service.set("stomp on", 1)
        self.assertEqual(service.get("stomp on"), 1)
        sent = len(fake.sent)
        with self.assertRaises(ValueError):
            service.set("stomp on", 0.5)
        self.assertEqual(len(fake.sent), sent)

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

    def test_preset_115_is_refused_at_once(self):
        # Without the check it would wait 4 s for a dump that never comes.
        service, fake, events = self.make(dump=bass_dump())
        start = time.time()
        with self.assertRaises(ValueError):
            service.select_preset(115)
        self.assertLess(time.time() - start, 0.5)
        self.assertEqual(fake.sent, [])

    def test_out_of_range_is_refused_and_sends_nothing(self):
        service, fake, events = self.make(dump=bass_dump())
        for n in (-1, 128):
            with self.assertRaises(ValueError):
                service.select_preset(n)
        self.assertEqual(fake.sent, [])
        self.assertEqual(events.of(EventType.PRESET_CHANGED), [])


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


class TestValuesFromDumps(ServiceTest):
    """ start(), select_preset() and the knob refresh read parameter values from the dump
    they get (protocol.md section 3). Values from test_dump_values.py. """

    def test_start_reads_the_handshake_dump(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        self.assertAlmostEqual(service.get("drive"), 0.9004, places=3)
        self.assertAlmostEqual(service.get("volume"), 0.5922, places=3)
        self.assertEqual(service.get("stomp on"), 0)

    def test_values_from_the_handshake_are_not_events(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        self.assertEqual(events.of(EventType.PARAMETER_CHANGED), [])

    def test_no_dump_means_no_values(self):
        service, fake, events = self.make()
        self.assertIsNone(service.get("drive"))
        self.assertEqual(service.state().params, {})

    def test_select_replaces_the_values(self):
        # The old preset's values belong to the old preset: Bass has Drive, not Gain.
        service, fake, events = self.make(handshake_dump=chime_dump(), dump=bass_dump())
        service.select_preset(0)
        self.assertAlmostEqual(service.get("drive"), 0.6226, places=3)
        self.assertAlmostEqual(service.get("volume"), 0.7022, places=3)
        self.assertNotIn(GAIN.key, service.state().params)        # Chime's Gain is gone

    def test_a_knob_refresh_reads_the_new_dump(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), dump=bass_dump())
        fake.arrive(*first_click())
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PRESET_CHANGED))
        self.assertAlmostEqual(service.get("drive"), 0.6226, places=3)
        self.assertNotIn(GAIN.key, service.state().params)

    def test_a_set_still_overrides(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        service.set("volume", 0.25)
        self.assertEqual(service.get("volume"), 0.25)


def sent_param_id(fake):
    """ The parameter id of the last set the fake was sent (msg[17], protocol.md section 8). """
    return [msg for msg in fake.sent if is_set(msg)][-1][17]


def drive_report():
    """ GAIN_REPORT with the id changed to Drive, 0x26 (id at msg[26]). """
    msg = bytearray(GAIN_REPORT)
    msg[26] = 0x26
    return bytes(msg)


class TestDrivePick(ServiceTest):
    """ "gain" and "drive" both mean whichever of the two the current preset has: Gain
    (0x25) on Chime, Drive (0x26) on Bass (protocol.md section 3, point 5). The dump says
    which; with no dump, the one asked for is sent. """

    def test_chime_gets_0x25(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        service.set("drive", 0.5)
        self.assertEqual(sent_param_id(fake), 0x25)

    def test_bass_gets_0x26(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        service.set("drive", 0.5)
        self.assertEqual(sent_param_id(fake), 0x26)
        self.assertEqual(service.get("drive"), 0.5)
        self.assertNotIn(GAIN.key, service.state().params)

    def test_gain_on_bass_is_sent_as_drive(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        service.set("gain", 0.5)
        self.assertEqual(sent_param_id(fake), 0x26)

    def test_gain_on_chime_is_sent_as_gain(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        service.set("gain", 0.5)
        self.assertEqual(sent_param_id(fake), 0x25)

    def test_no_dump_sends_drive_as_asked(self):
        service, fake, events = self.make()
        service.set("drive", 0.5)
        self.assertEqual(sent_param_id(fake), 0x26)

    def test_no_dump_sends_gain_as_asked(self):
        service, fake, events = self.make()
        service.set("gain", 0.5)
        self.assertEqual(sent_param_id(fake), 0x25)

    def test_after_a_set_the_pick_follows_it(self):
        # With no dump, the one set first is the one params has, so the other follows it.
        service, fake, events = self.make()
        service.set("drive", 0.5)
        service.set("gain", 0.6)
        self.assertEqual(sent_param_id(fake), 0x26)

    def test_get_gain_reads_the_one_the_preset_has(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        self.assertAlmostEqual(service.get("gain"), 0.6226, places=3)

    def test_get_drive_reads_the_drive_the_preset_has(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        self.assertAlmostEqual(service.get("drive"), 0.6226, places=3)     # Bass's Drive

    def test_get_drive_after_a_set(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        service.set("drive", 0.3)
        self.assertEqual(service.get("drive"), 0.3)

    def test_get_drive_follows_a_knob_report(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        fake.arrive(drive_report())
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PARAMETER_CHANGED))
        self.assertAlmostEqual(service.get("drive"), 0.99, places=2)

    def test_the_pick_follows_a_select(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), dump=bass_dump())
        service.set("drive", 0.5)
        self.assertEqual(sent_param_id(fake), 0x25)
        service.select_preset(0)
        service.set("drive", 0.5)
        self.assertEqual(sent_param_id(fake), 0x26)

    def test_the_event_names_the_drive_that_was_set(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        service.set("drive", 0.5)
        change = events.of(EventType.PARAMETER_CHANGED)[-1].data
        self.assertEqual(change["key"], (0x2A, 0x26, 0))
        self.assertEqual(change["name"], "Drive")


def sets_sent(fake):
    """ (param id, value) of every set the fake was sent, in order (msg[17] and msg[26:31]). """
    return [(msg[17], round(decode_set_value(msg[26:31]), 2)) for msg in fake.sent if is_set(msg)]


class TestSetLatest(ServiceTest):
    """ set_latest() for sliders: the newest value per parameter wins, and only the caller
    already sending waits. The fake answers each set after 0.2 s, so a burst piles up. """

    VOLUME, REVERB, FX_KNOB = 0x24, 0x20, 0x1A

    def make_slow(self, delay=0.2, **args):
        service, fake, events = self.make(**args)
        answers = self.replies

        def slow(msg):
            if is_set(msg):
                if answers.answer_sets:
                    timer = threading.Timer(delay, fake.arrive, args=[SET_ANSWER])
                    timer.daemon = True            # a late answer mustn't hold up the test run
                    timer.start()
                return []
            return answers(msg)
        fake.auto_reply = slow
        return service, fake, events

    def first_in_background(self, service, name, value):
        """ Starts a set_latest on another thread (it becomes the sender) and waits until it's sent. """
        t = threading.Thread(target=service.set_latest, args=(name, value))
        t.start()
        deadline = time.time() + 2
        while not sets_sent(self.fake) and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(sets_sent(self.fake), "the first set was never sent")
        return t

    def test_stop_while_sending_drops_the_rest_quietly(self):
        # stop() sets _amp to None while the sender still has values waiting; _send
        # must see that as AmpDisconnected (which _drain handles), not AttributeError.
        service, fake, events = self.make_slow()
        errors = []
        old_hook = threading.excepthook
        threading.excepthook = lambda args: errors.append(args.exc_type)
        try:
            sender = self.first_in_background(service, "volume", 0.1)
            service.set_latest("reverb", 0.3)
            service.stop()
            sender.join(timeout=3)
        finally:
            threading.excepthook = old_hook
        self.assertFalse(sender.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual([pid for pid, _ in sets_sent(fake)], [self.VOLUME])   # reverb never sent

    def test_the_newest_value_wins(self):
        service, fake, events = self.make_slow()
        sender = self.first_in_background(service, "volume", 0.1)
        for value in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            service.set_latest("volume", value)
        sender.join(timeout=3)
        self.assertEqual(sets_sent(fake), [(self.VOLUME, 0.1), (self.VOLUME, 0.9)])
        self.assertEqual(service.get("volume"), 0.9)

    def test_only_the_sender_waits(self):
        service, fake, events = self.make_slow()
        sender = self.first_in_background(service, "volume", 0.1)
        start = time.time()
        service.set_latest("volume", 0.5)
        self.assertLess(time.time() - start, 0.05)
        sender.join(timeout=3)

    def test_two_parameters_in_one_burst(self):
        service, fake, events = self.make_slow()
        sender = self.first_in_background(service, "volume", 0.1)
        service.set_latest("reverb", 0.3)
        service.set_latest("volume", 0.8)
        sender.join(timeout=3)
        self.assertEqual(sorted(sets_sent(fake)), sorted([(self.VOLUME, 0.1), (self.REVERB, 0.3), (self.VOLUME, 0.8)]))
        self.assertEqual((service.get("volume"), service.get("reverb")), (0.8, 0.3))

    def test_the_longest_waiting_goes_first(self):
        service, fake, events = self.make_slow()
        sender = self.first_in_background(service, "volume", 0.1)
        service.set_latest("reverb", 0.3)
        service.set_latest("stomp knob", 0.4)
        sender.join(timeout=3)
        self.assertEqual([pid for pid, _ in sets_sent(fake)], [self.VOLUME, self.REVERB, self.FX_KNOB])

    def test_each_value_sends_parameter_changed(self):
        service, fake, events = self.make_slow()
        sender = self.first_in_background(service, "volume", 0.1)
        service.set_latest("volume", 0.7)
        sender.join(timeout=3)
        self.assertEqual([e.data["value"] for e in events.of(EventType.PARAMETER_CHANGED)], [0.1, 0.7])

    def test_bad_names_and_values_are_refused_up_front(self):
        service, fake, events = self.make()
        for name, value in (("wah", 0.5), ("volume", 1.5), ("tap (hold)", 0.5)):
            with self.assertRaises(ValueError):
                service.set_latest(name, value)
        self.assertEqual(sets_sent(fake), [])

    def test_not_connected_is_refused_up_front(self):
        service, fake, events = self.make(start=False)
        with self.assertRaises(AmpDisconnected):
            service.set_latest("volume", 0.5)

    def test_a_timeout_doesnt_jam_it(self):
        # The error can't reach a caller that has already returned, so it's logged instead.
        service, fake, events = self.make()
        self.replies.answer_sets = False
        service.set_latest("volume", 0.5)              # times out inside, doesn't raise
        self.replies.answer_sets = True
        service.set_latest("volume", 0.6)
        self.assertEqual(service.get("volume"), 0.6)

    def test_an_unplug_drops_the_rest(self):
        service, fake, events = self.make_slow(delay=5)       # the first set is never answered in time
        sender = self.first_in_background(service, "volume", 0.1)
        service.set_latest("reverb", 0.3)
        fake.arrive(OSError(19, "No such device"))
        sender.join(timeout=3)
        self.assertFalse(sender.is_alive())
        self.assertEqual([pid for pid, _ in sets_sent(fake)], [self.VOLUME])   # reverb never sent
        self.assertIsNone(service.get("reverb"))

    def test_drive_is_picked_for_the_preset(self):
        service, fake, events = self.make(handshake_dump=bass_dump())
        service.set_latest("drive", 0.5)
        self.assertEqual(sent_param_id(fake), 0x26)


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



class TestSave(ServiceTest):
    """ save(): a fresh dump, uploaded to the loaded slot, read back, PRESET_SAVED
    (protocol.md section 8, "Save command"). The fake answers uploads like the amp. """

    def make_save(self, **args):
        service, fake, events = self.make(**args)
        self.uploads = AnswersUploads(other=self.replies)
        fake.auto_reply = self.uploads
        return service, fake, events

    def loaded(self):
        """ A service with Bass selected (slot 0), so the slot is known. """
        service, fake, events = self.make_save(handshake_dump=chime_dump(), dump=bass_dump())
        service.select_preset(0)
        fake.sent.clear()
        return service, fake, events

    def test_uploads_the_dumps_preset_to_the_loaded_slot(self):
        service, fake, events = self.loaded()
        service.save()
        self.assertEqual(self.uploads.uploads, [(0, preset_data(collected(bass_dump())))])

    def test_asks_for_a_dump_first_and_reads_it_back_after(self):
        service, fake, events = self.loaded()
        service.save()
        self.assertEqual(fake.sent[0], DUMP_REQUEST)
        self.assertTrue(is_upload_header(fake.sent[1]))
        self.assertEqual(fake.sent[-1], DUMP_REQUEST)

    def test_returns_the_name_and_sends_preset_saved(self):
        service, fake, events = self.loaded()
        self.assertEqual(service.save(), "Bass")
        self.assertEqual(events.of(EventType.PRESET_SAVED)[-1].data, {"number": 0, "name": "Bass"})

    def test_refuses_when_the_slot_isnt_known(self):
        # After the handshake (or a knob move) preset_number is None: saving could
        # overwrite the wrong preset, so nothing is sent.
        service, fake, events = self.make_save(handshake_dump=chime_dump(), dump=chime_dump())
        with self.assertRaises(ValueError):
            service.save()
        self.assertEqual(fake.sent, [])

    def test_not_connected(self):
        service, fake, events = self.make_save(start=False)
        with self.assertRaises(AmpDisconnected):
            service.save()

    def test_an_unanswered_upload_raises_and_sends_no_event(self):
        service, fake, events = self.loaded()
        self.uploads.answer = False
        with self.assertRaises(AmpTimeout):
            service.save()
        self.assertEqual(events.of(EventType.PRESET_SAVED), [])

    def test_a_set_before_saving_is_in_the_saved_dump(self):
        # save() uploads what the amp says it has, so a set is included because the
        # amp's dump includes it (here the fake's dump is fixed, so only the order shows).
        service, fake, events = self.loaded()
        service.set("volume", 0.3)
        fake.sent.clear()
        service.save()
        self.assertEqual(fake.sent[0], DUMP_REQUEST)


def collected(messages):
    """ A complete DumpCollector from a dump's messages. """
    collector = DumpCollector()
    for msg in messages:
        collector.offer(msg)
    assert collector.complete()
    return collector


APP_DATA = Path(__file__).resolve().parent.parent / "app_data"


def made_up_app_data(folder):
    """ A small app_data folder in `folder`: a symbol table naming Chime's and Bass's amp
    and cab, and a .models file each for them. Enough to check the service end to end
    without Line 6's files. """
    names = [f"Symbol{i}" for i in range(0x317)]
    names[0xDC], names[0xBF], names[0x2C1] = "ClassA30TopBoost", "L6TubePreamp", "2x12ClassAStudio57OnAxis"
    (folder / "defaultSymbolTable_Parker.bin").write_bytes(make_table(names))
    (folder / "amps.models").write_text(json.dumps([
        {"symbolicID": "ClassA30TopBoost", "name": "1967 Class A-30 Top Boost"},
        {"symbolicID": "L6TubePreamp", "name": "Tube Instrument Preamp"}]))
    (folder / "cabs.models").write_text(json.dumps([{"symbolicID": "2x12ClassAStudio", "name": "2x12 Class A"}]))
    return folder


class TestModels(ServiceTest):
    """ state().models: each stage's model, from every dump, named with the Line 6 app's
    files when they're there (protocol.md section 10). """

    STAGES = {"gate", "vol", "wah", "stomp", "mod", "delay", "reverb", "amp", "cab", "comp", "eq"}

    def app_data(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return made_up_app_data(Path(tmp.name))

    def test_the_handshake_dump_gives_every_stage(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), resource_folder=self.app_data())
        self.assertEqual(set(service.state().models), self.STAGES)

    def test_named_from_the_files(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), resource_folder=self.app_data())
        models = service.state().models
        self.assertEqual(models["amp"], {"number": 0xDC, "id": "ClassA30TopBoost", "name": "1967 Class A-30 Top Boost"})
        self.assertEqual(models["cab"]["name"], "2x12 Class A")             # the mic is cut off

    def test_a_model_the_files_dont_name(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), resource_folder=self.app_data())
        gate = service.state().models["gate"]
        self.assertEqual((gate["number"], gate["id"], gate["name"]), (0x25E, "Symbol606", None))

    def test_no_files_gives_numbers_only(self):
        service, fake, events = self.make(handshake_dump=chime_dump())          # resource_folder=None
        self.assertEqual(service.state().models["amp"], {"number": 0xDC, "id": None, "name": None})

    def test_a_missing_folder_is_fine(self):
        service, fake, events = self.make(handshake_dump=chime_dump(),
                                          resource_folder=Path(tempfile.gettempdir()) / "no app_data here")
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)
        self.assertEqual(service.state().models["amp"]["id"], None)

    def test_the_folder_can_be_text(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), resource_folder=str(self.app_data()))
        self.assertEqual(service.state().models["amp"]["id"], "ClassA30TopBoost")

    def test_select_replaces_them(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), dump=bass_dump(),
                                          resource_folder=self.app_data())
        service.select_preset(0)
        self.assertEqual(service.state().models["amp"]["name"], "Tube Instrument Preamp")

    def test_a_knob_refresh_replaces_them(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), dump=bass_dump())
        fake.arrive(*first_click())
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PRESET_CHANGED))
        self.assertEqual(service.state().models["amp"]["number"], 0xBF)

    def test_no_handshake_dump_means_no_models(self):
        service, fake, events = self.make()
        self.assertEqual(service.state().models, {})

    def test_a_copy(self):
        service, fake, events = self.make(handshake_dump=chime_dump())
        service.state().models.clear()
        self.assertEqual(set(service.state().models), self.STAGES)

    @unittest.skipUnless((APP_DATA / "amps.models").exists(), "app_data/ isn't here (the Line 6 app's files are never in git)")
    def test_the_real_files(self):
        service, fake, events = self.make(handshake_dump=chime_dump(), resource_folder=APP_DATA)
        names = {stage: m["name"] for stage, m in service.state().models.items()}
        self.assertEqual((names["amp"], names["gate"], names["cab"]),
                         ("1967 Class A-30 Top Boost", "Noise Gate", "2x12 Class A"))


if __name__ == "__main__":
    unittest.main()
