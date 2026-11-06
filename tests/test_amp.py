"""Tests for spiderweb/amp.py: amp operations on top of a real Connection.

The amp itself is the FakeTransport from test_connection.py, so these check that
Amp sends the right messages and that its replies come back through the connection.
Like the real amp, the fake answers every set (protocol.md section 8) unless a test
says otherwise.
"""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.errors import AmpDisconnected, AmpError, AmpTimeout
from spiderweb.protocol.messages import (
    DUMP_REQUEST,
    build_begin_message,
    build_set_message,
    select_message,
)
from spiderweb.protocol.parameters import BY_NAME
from spiderweb.protocol.values import encode_set_value
from tests.test_connection import FakeTransport, Recorder, capture_messages, replies_to
from tests.test_dump import preset_select_section

HELLO = b"\xf0hello\xf7"
HELLO_REPLY = b"\xf0hello-reply\xf7"
OTHER = b"\xf0other\xf7"
FIRST_SEQ = 0x0C        # protocol.md section 2: our seq starts here after the handshake
# The amp's answer to a set, from captures/set_pace.txt (protocol.md section 8).
SET_ANSWER = bytes.fromhex("f000010c22054d000900000b00010000000400000000000000000000f7")

DRIVE = BY_NAME["drive"]
TAP_HOLD = BY_NAME["tap (hold)"]


def is_set(msg):
    """ A 37-byte set message (the second of a set's two messages). """
    return len(msg) == 37 and msg[11] == 0x0F


def answers_sets(other=None):
    """ auto_reply for the fake: answers every set with SET_ANSWER, and anything else with `other`. """
    other = other or (lambda msg: [])
    return lambda msg: [SET_ANSWER] if is_set(msg) else other(msg)


def chime_dump():
    """ A real capture of the amp answering a dump request (dump chunks mixed with other messages). """
    return capture_messages("chime_Drive.txt")


def bass_dump():
    """ What came back after selecting value 0 (Bass) from the Pi. """
    return preset_select_section("preset_select_2.txt", 0)


def sets_in(sent):
    """ The (begin seq, set seq) pairs in a list of sent messages, checking each begin is followed by its set. """
    pairs = []
    for begin, set_msg in zip(sent[::2], sent[1::2]):
        pairs.append((begin[8], set_msg[8]))
    return pairs


class AmpTest(unittest.TestCase):
    """ Gives each test a fake transport, a real Connection and an Amp, and always closes them.

    The fake answers sets as the amp does; pass answer_sets=False for one that doesn't.
    """
    def make(self, handshake=(), connect=True, answer_sets=True, **fake_args):
        if answer_sets:
            fake_args["auto_reply"] = answers_sets(fake_args.get("auto_reply"))
        self.fake = FakeTransport(**fake_args)
        self.factory_calls = 0
        def factory():
            self.factory_calls += 1
            return self.fake
        self.conn = Connection(list(handshake), transport_factory=factory)
        self.amp = Amp(self.conn)
        self.addCleanup(self.amp.close)
        if connect:
            self.amp.connect()
        return self.amp, self.fake


class TestLoadHandshake(unittest.TestCase):
    def test_the_real_handshake(self):
        lines = load_handshake()
        self.assertEqual(len(lines), 258)
        self.assertTrue(all(isinstance(line, bytes) for line in lines))
        self.assertEqual(lines[0], bytes.fromhex("f07e7f0601f7"))     # device inquiry
        self.assertEqual(lines[7], DUMP_REQUEST)                        # line 8 is the dump trigger

    def test_blank_lines_and_spaces_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "handshake.txt"
            path.write_text("f07e7f0601f7\n\n   \n  f000f7  \n")
            self.assertEqual(load_handshake(path), [bytes.fromhex("f07e7f0601f7"), bytes.fromhex("f000f7")])


class TestConnect(AmpTest):
    def test_making_an_amp_touches_nothing(self):
        amp, fake = self.make(connect=False)
        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(fake.sent, [])

    def test_connect_returns_handshake_replies(self):
        amp, fake = self.make(handshake=[HELLO], connect=False,
                              auto_reply=replies_to({HELLO: [HELLO_REPLY]}))
        self.assertEqual(amp.connect(), [[HELLO_REPLY]])     # one group per handshake line
        self.assertEqual(fake.sent, [HELLO])

    def test_close_closes_the_device(self):
        amp, fake = self.make()
        amp.close()
        self.assertTrue(fake.closed)

    def test_commands_before_connect_fail_fast(self):
        amp, fake = self.make(connect=False)
        with self.assertRaises(AmpDisconnected):
            amp.set_parameter(DRIVE, 0.5)
        with self.assertRaises(AmpDisconnected):
            amp.request_dump(timeout=0.3)


class TestSet(AmpTest):
    def test_set_raw_sends_begin_then_set(self):
        amp, fake = self.make()
        raw5 = bytes([1, 2, 3, 4, 5])
        amp.set_raw(0x2A, 0, 0x25, raw5)
        self.assertEqual(fake.sent, [
            build_begin_message(FIRST_SEQ),
            build_set_message(FIRST_SEQ + 1, 0x2A, 0, 0x25, raw5, 1),
        ])

    def test_set_raw_passes_unknown_through(self):
        amp, fake = self.make()
        raw5 = bytes(5)
        amp.set_raw(0x2A, 0, 0x25, raw5, unknown=3)
        self.assertEqual(fake.sent[1], build_set_message(FIRST_SEQ + 1, 0x2A, 0, 0x25, raw5, 3))

    def test_set_parameter_sends_the_encoded_value(self):
        amp, fake = self.make()
        amp.set_parameter(DRIVE, 0.5)
        self.assertEqual(fake.sent[1], build_set_message(
            FIRST_SEQ + 1, DRIVE.block, DRIVE.sub, DRIVE.id, encode_set_value(0.5)))

    def test_seq_steps_by_two(self):
        amp, fake = self.make()
        for _ in range(3):
            amp.set_parameter(DRIVE, 0.5)
        self.assertEqual(sets_in(fake.sent), [(0x0C, 0x0D), (0x0E, 0x0F), (0x10, 0x11)])

    def test_seq_wraps_round(self):
        amp, fake = self.make()
        for _ in range(60):
            amp.set_parameter(DRIVE, 0.5)        # would raise if seq went past 0x7F
        pairs = sets_in(fake.sent)
        self.assertEqual(pairs[57], (0x7E, 0x7F))
        self.assertEqual(pairs[58], (0x00, 0x01))

    def test_seq_starts_again_after_reconnect(self):
        amp, fake = self.make()
        amp.set_parameter(DRIVE, 0.5)
        amp.close()
        fake.sent.clear()
        amp.connect()
        amp.set_parameter(DRIVE, 0.5)
        self.assertEqual(sets_in(fake.sent), [(FIRST_SEQ, FIRST_SEQ + 1)])

    def test_not_settable_is_refused(self):
        amp, fake = self.make()
        with self.assertRaises(ValueError):
            amp.set_parameter(TAP_HOLD, 0.5)
        self.assertEqual(fake.sent, [])

    def test_out_of_range_is_refused(self):
        amp, fake = self.make()
        for value in (-0.1, 1.1):
            with self.assertRaises(ValueError):
                amp.set_parameter(DRIVE, value)
        self.assertEqual(fake.sent, [])

    def test_sets_from_two_threads_stay_in_pairs(self):
        # Without the set lock the begins and sets of two threads get mixed up.
        amp, fake = self.make()
        def many():
            for _ in range(50):
                amp.set_parameter(DRIVE, 0.5)
        threads = [threading.Thread(target=many) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(len(fake.sent), 200)
        for begin, set_msg in zip(fake.sent[::2], fake.sent[1::2]):
            self.assertEqual(len(begin), 29, "a set message where a begin should be")
            self.assertEqual(len(set_msg), 37, "a begin message where a set should be")
            self.assertEqual(set_msg[8], (begin[8] + 1) % 128)

    def test_a_set_waits_for_the_answer_before_the_next(self):
        # A set sent before the amp has answered the previous one kills all sets
        # (protocol.md section 8), so a set must wait for its answer.
        order = []
        amp, fake = self.make(answer_sets=False)

        def slow_amp(msg):
            order.append("set" if is_set(msg) else "begin")
            if is_set(msg):
                def answer():
                    order.append("answer")
                    fake.arrive(SET_ANSWER)
                threading.Timer(0.2, answer).start()
            return []
        fake.auto_reply = slow_amp
        threads = [threading.Thread(target=amp.set_parameter, args=(DRIVE, 0.5)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        self.assertEqual(order, ["begin", "set", "answer", "begin", "set", "answer"])

    def test_no_answer_times_out(self):
        amp, fake = self.make(answer_sets=False)
        start = time.time()
        with self.assertRaises(AmpTimeout):
            amp.set_parameter(DRIVE, 0.5)
        self.assertLess(time.time() - start, 2.5)
        self.assertEqual(len(fake.sent), 2)            # it was sent, just never answered

    def test_a_set_after_a_timeout_still_moves_seq_on(self):
        amp, fake = self.make(answer_sets=False)
        with self.assertRaises(AmpTimeout):
            amp.set_parameter(DRIVE, 0.5)
        fake.auto_reply = answers_sets()
        amp.set_parameter(DRIVE, 0.5)
        self.assertEqual(sets_in(fake.sent), [(0x0C, 0x0D), (0x0E, 0x0F)])

    def test_the_answer_isnt_passed_to_listeners(self):
        amp, fake = self.make()
        listener = Recorder()
        amp.add_listener(listener)
        amp.set_parameter(DRIVE, 0.5)
        fake.arrive(OTHER)
        self.assertTrue(listener.wait_for())
        self.assertEqual(listener.calls, [OTHER])

    def test_set_from_a_listener_is_refused(self):
        # A set waits for an answer that only the reader thread can deliver.
        amp, fake = self.make()
        errors = []

        def set_from_listener(msg):
            try:
                amp.set_parameter(DRIVE, 0.5)
            except AmpError as e:
                errors.append(e)
        amp.add_listener(set_from_listener)
        fake.arrive(OTHER)
        deadline = time.time() + 2
        while not errors and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(errors), 1)
        self.assertNotIsInstance(errors[0], AmpTimeout)

    def test_set_after_unplug_fails_fast(self):
        amp, fake = self.make()
        lost = Recorder()
        amp.on_lost(lost)
        fake.arrive(OSError("unplugged"))
        self.assertTrue(lost.wait_for())
        with self.assertRaises(AmpDisconnected):
            amp.set_parameter(DRIVE, 0.5)


class TestDump(AmpTest):
    def test_request_dump_returns_the_whole_dump(self):
        amp, fake = self.make(auto_reply=replies_to({DUMP_REQUEST: chime_dump()}))
        dump = amp.request_dump(timeout=2.0)
        self.assertTrue(dump.complete())
        self.assertEqual(dump.name(), "Chime 1: Class-A")
        self.assertEqual(fake.sent, [DUMP_REQUEST])

    def test_no_dump_times_out(self):
        amp, fake = self.make()
        with self.assertRaises(AmpTimeout):
            amp.request_dump(timeout=0.3)

    def test_messages_around_the_dump_still_reach_listeners(self):
        amp, fake = self.make(auto_reply=replies_to({DUMP_REQUEST: [OTHER] + chime_dump()}))
        listener = Recorder()
        amp.add_listener(listener)
        amp.request_dump(timeout=2.0)
        self.assertTrue(listener.wait_for())
        self.assertIn(OTHER, listener.calls)


class TestSelectPreset(AmpTest):
    def test_select_sends_select_then_dump_request(self):
        amp, fake = self.make(auto_reply=replies_to({DUMP_REQUEST: bass_dump()}))
        amp.select_preset(0, timeout=2.0)
        self.assertEqual(fake.sent, [select_message(0), DUMP_REQUEST])

    def test_select_returns_the_new_preset(self):
        amp, fake = self.make(auto_reply=replies_to({DUMP_REQUEST: bass_dump()}))
        dump = amp.select_preset(0, timeout=2.0)
        self.assertTrue(dump.complete())
        self.assertEqual(dump.name(), "Bass")

    def test_select_with_no_dump_times_out(self):
        amp, fake = self.make()
        with self.assertRaises(AmpTimeout):
            amp.select_preset(0, timeout=0.3)

    def test_bad_value_is_refused(self):
        amp, fake = self.make()
        with self.assertRaises(ValueError):
            amp.select_preset(200, timeout=0.3)
        self.assertEqual(fake.sent, [])


class TestRefreshPreset(AmpTest):
    def test_refresh_calls_on_done_with_the_dump(self):
        amp, fake = self.make(auto_reply=replies_to({DUMP_REQUEST: chime_dump()}))
        done = Recorder()
        self.assertTrue(amp.refresh_preset(done, timeout=2.0))
        self.assertTrue(done.wait_for())
        self.assertEqual(done.calls[0].name(), "Chime 1: Class-A")

    def test_refresh_calls_on_done_on_timeout_too(self):
        amp, fake = self.make()
        done = Recorder()
        amp.refresh_preset(done, timeout=0.3)
        self.assertTrue(done.wait_for())
        self.assertFalse(done.calls[0].complete())

    def test_refresh_while_busy_returns_false(self):
        amp, fake = self.make()
        first = Recorder()
        self.assertTrue(amp.refresh_preset(first, timeout=0.5))
        self.assertFalse(amp.refresh_preset(Recorder(), timeout=0.5))
        self.assertEqual(fake.sent, [DUMP_REQUEST])
        self.assertTrue(first.wait_for())

    def test_refresh_from_a_listener(self):
        # How the service will use it: the knob settles, a listener asks for the new name.
        amp, fake = self.make(auto_reply=replies_to({DUMP_REQUEST: chime_dump()}))
        done = Recorder()
        def on_message(msg):
            if msg == OTHER:
                amp.refresh_preset(done, timeout=2.0)
        amp.add_listener(on_message)
        fake.arrive(OTHER)
        self.assertTrue(done.wait_for())
        self.assertEqual(done.calls[0].name(), "Chime 1: Class-A")


class TestPassThrough(AmpTest):
    def test_listeners_get_messages(self):
        amp, fake = self.make()
        listener = Recorder()
        amp.add_listener(listener)
        fake.arrive(OTHER)
        self.assertTrue(listener.wait_for())
        self.assertEqual(listener.calls, [OTHER])

    def test_on_lost_is_called_on_unplug(self):
        amp, fake = self.make()
        lost = Recorder()
        amp.on_lost(lost)
        fake.arrive(OSError("unplugged"))
        self.assertTrue(lost.wait_for())


if __name__ == "__main__":
    unittest.main()
