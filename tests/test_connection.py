import threading
import time
import unittest

from silkline.connection import Connection
from silkline.errors import AmpDisconnected, AmpError, AmpTimeout
from silkline.protocol.dump import DumpCollector
from silkline.protocol.messages import DUMP_REQUEST
from tests.helpers import FakeTransport, Recorder, capture_messages, replies_to


HELLO = b"\xf0hello\xf7"
HELLO_REPLY = b"\xf0hello-reply\xf7"
ASK = b"\xf0ask\xf7"
REPLY = b"\xf0R1\xf7"
OTHER = b"\xf0other\xf7"


class Counting:
    """ A collector that takes messages starting with `tag` until it has `n`. """
    def __init__(self, n=1, tag=b"\xf0R"):
        self.n, self.tag, self.chunks = n, tag, []

    def offer(self, msg):
        if self.complete() or not msg.startswith(self.tag):
            return False
        self.chunks.append(msg)
        return True

    def complete(self):
        return len(self.chunks) >= self.n


class ConnectionTest(unittest.TestCase):
    """ Gives each test a fake and a connection, and always closes it. """
    def make(self, handshake=(), **fake_args):
        self.fake = FakeTransport(**fake_args)
        self.conn = Connection(list(handshake), transport_factory=lambda: self.fake)
        self.addCleanup(self.conn.close)
        return self.conn, self.fake


class TestOpenClose(ConnectionTest):
    def test_open_returns_handshake_replies(self):
        conn, fake = self.make(handshake=[HELLO], auto_reply=replies_to({HELLO: [HELLO_REPLY]}))
        self.assertEqual(conn.open(), [[HELLO_REPLY]])
        self.assertEqual(fake.sent, [HELLO])

    def test_replies_are_grouped_by_handshake_line(self):
        # One list per line, in order, so a reply can be matched to the line it answers.
        conn, fake = self.make(handshake=[HELLO, OTHER, ASK],
                               auto_reply=replies_to({HELLO: [HELLO_REPLY], ASK: [REPLY, OTHER]}))
        self.assertEqual(conn.open(), [[HELLO_REPLY], [], [REPLY, OTHER]])

    def test_open_flushes_old_messages(self):
        conn, fake = self.make()
        fake.arrive(OTHER)                      # left over from before we opened
        listener = Recorder()
        conn.add_listener(listener)
        self.assertEqual(conn.open(), [])           # no handshake lines, so no groups
        self.assertFalse(listener.wait_for(timeout=0.4))

    def test_open_starts_the_reader(self):
        conn, fake = self.make()
        conn.open()
        self.assertTrue(conn._thread.is_alive())

    def test_close_stops_the_reader_and_closes(self):
        conn, fake = self.make()
        conn.open()
        thread = conn._thread
        conn.close()
        self.assertFalse(thread.is_alive())
        self.assertTrue(fake.closed)

    def test_close_twice_is_harmless(self):
        conn, fake = self.make()
        conn.open()
        conn.close()
        conn.close()

    def test_close_without_open_is_harmless(self):
        conn, fake = self.make()
        conn.close()

    def test_close_from_a_listener(self):
        # A listener runs on the reader thread, so close() must not join itself.
        conn, fake = self.make()
        conn.open()
        thread = conn._thread
        listener = Recorder(action=lambda msg: conn.close())
        conn.add_listener(listener)
        fake.arrive(OTHER)
        self.assertTrue(listener.wait_for())
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(fake.closed)

    def test_reopen_after_close(self):
        conn, fake = self.make()
        conn.open()
        conn.close()
        conn.open()
        listener = Recorder()
        conn.add_listener(listener)
        fake.arrive(OTHER)
        self.assertTrue(listener.wait_for())

    def test_missing_device_raises_the_real_error(self):
        def no_amp():
            raise OSError("no amp")
        conn = Connection([], transport_factory=no_amp)
        with self.assertRaises(OSError):
            conn.open()
        self.assertIsNone(conn._thread)

    def test_failed_handshake_closes_the_transport(self):
        conn, fake = self.make(handshake=[HELLO])
        fake.fail_send = True
        with self.assertRaises(OSError):
            conn.open()
        self.assertTrue(fake.closed)
        self.assertIsNone(conn._thread)


class TestListeners(ConnectionTest):
    def test_messages_go_to_listeners(self):
        conn, fake = self.make()
        listener = Recorder()
        conn.add_listener(listener)
        conn.open()
        fake.arrive(OTHER)
        self.assertTrue(listener.wait_for())
        self.assertEqual(listener.calls, [OTHER])

    def test_a_failing_listener_does_not_stop_the_others(self):
        conn, fake = self.make()
        def broken(msg):
            raise RuntimeError("boom")
        listener = Recorder()
        conn.add_listener(broken)
        conn.add_listener(listener)
        conn.open()
        fake.arrive(OTHER, OTHER)
        self.assertTrue(listener.wait_for(2))
        self.assertTrue(conn._thread.is_alive())


class TestSendAndLost(ConnectionTest):
    def test_send_writes_to_the_transport(self):
        conn, fake = self.make()
        conn.open()
        conn.send(ASK)
        self.assertEqual(fake.sent, [ASK])

    def test_send_before_open_fails_fast(self):
        conn, fake = self.make()
        with self.assertRaises(AmpDisconnected):
            conn.send(ASK)

    def test_send_failure_reports_lost(self):
        conn, fake = self.make()
        lost = Recorder()
        conn.on_lost(lost)
        conn.open()
        fake.fail_send = True
        with self.assertRaises(AmpDisconnected):
            conn.send(ASK)
        self.assertTrue(lost.wait_for())
        self.assertIsInstance(lost.calls[0], OSError)

    def test_read_failure_reports_lost_and_ends_the_reader(self):
        conn, fake = self.make()
        lost = Recorder()
        conn.on_lost(lost)
        conn.open()
        thread = conn._thread
        fake.arrive(OSError("unplugged"))
        self.assertTrue(lost.wait_for())
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_lost_is_reported_once(self):
        conn, fake = self.make()
        lost = Recorder()
        conn.on_lost(lost)
        conn.open()
        fake.arrive(OSError("unplugged"))
        self.assertTrue(lost.wait_for())
        fake.fail_send = True
        with self.assertRaises(AmpDisconnected):
            conn.send(ASK)
        self.assertEqual(len(lost.calls), 1)

    def test_a_failing_lost_callback_does_not_stop_the_others(self):
        conn, fake = self.make()
        def broken(error):
            raise RuntimeError("boom")
        lost = Recorder()
        conn.on_lost(broken)
        conn.on_lost(lost)
        conn.open()
        fake.arrive(OSError("unplugged"))
        self.assertTrue(lost.wait_for())


class TestRequest(ConnectionTest):
    def test_request_returns_the_filled_collector(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        conn.open()
        collector = Counting()
        self.assertIs(conn.request([ASK], collector, timeout=1.0), collector)
        self.assertEqual(collector.chunks, [REPLY])

    def test_replies_are_not_given_to_listeners(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        listener = Recorder()
        conn.add_listener(listener)
        conn.open()
        conn.request([ASK], Counting(), timeout=1.0)
        self.assertFalse(listener.wait_for(timeout=0.3))

    def test_other_messages_during_a_request_still_reach_listeners(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [OTHER, REPLY]}))
        listener = Recorder()
        conn.add_listener(listener)
        conn.open()
        conn.request([ASK], Counting(), timeout=1.0)
        self.assertTrue(listener.wait_for())
        self.assertEqual(listener.calls, [OTHER])

    def test_request_with_several_messages_and_replies(self):
        table = {ASK: [b"\xf0R1\xf7"], HELLO: [b"\xf0R2\xf7", b"\xf0R3\xf7"]}
        conn, fake = self.make(auto_reply=replies_to(table))
        conn.open()
        collector = conn.request([ASK, HELLO], Counting(n=3), timeout=1.0)
        self.assertEqual(fake.sent, [ASK, HELLO])
        self.assertEqual(len(collector.chunks), 3)

    def test_no_reply_times_out(self):
        conn, fake = self.make()
        conn.open()
        start = time.time()
        with self.assertRaises(AmpTimeout):
            conn.request([ASK], Counting(), timeout=0.3)
        self.assertLess(time.time() - start, 1.5)

    def test_request_works_again_after_a_timeout(self):
        conn, fake = self.make()
        conn.open()
        with self.assertRaises(AmpTimeout):
            conn.request([ASK], Counting(), timeout=0.3)
        fake.auto_reply = replies_to({ASK: [REPLY]})
        self.assertTrue(conn.request([ASK], Counting(), timeout=1.0).complete())

    def test_send_failure_during_request_releases_it(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        conn.open()
        fake.fail_send = True
        with self.assertRaises(AmpDisconnected):
            conn.request([ASK], Counting(), timeout=1.0)
        self.assertIsNone(conn._pending)
        self.assertFalse(conn._request_lock.locked())

    def test_request_from_a_listener_is_refused(self):
        # The knob trap: the reader can't wait for a reply only it can read.
        conn, fake = self.make()
        errors = Recorder()
        def asks(msg):
            try:
                conn.request([ASK], Counting(), timeout=1.0)
            except AmpError as e:
                errors(e)
        conn.add_listener(asks)
        conn.open()
        fake.arrive(OTHER)
        self.assertTrue(errors.wait_for())
        self.assertTrue(conn._thread.is_alive())

    def test_unplug_during_request_does_not_wait_out_the_timeout(self):
        conn, fake = self.make()
        conn.open()
        threading.Timer(0.2, fake.arrive, args=[OSError("unplugged")]).start()
        start = time.time()
        with self.assertRaises(AmpError):
            conn.request([ASK], Counting(), timeout=5.0)
        self.assertLess(time.time() - start, 2.0)

    def test_close_during_request_does_not_wait_out_the_timeout(self):
        conn, fake = self.make()
        conn.open()
        threading.Timer(0.2, conn.close).start()
        start = time.time()
        with self.assertRaises(AmpError):
            conn.request([ASK], Counting(), timeout=5.0)
        self.assertLess(time.time() - start, 3.0)


class TestRequestAsync(ConnectionTest):
    def test_on_done_is_called_with_the_collector(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        conn.open()
        done = Recorder()
        collector = Counting()
        self.assertTrue(conn.request_async([ASK], collector, done, timeout=1.0))
        self.assertTrue(done.wait_for())
        self.assertIs(done.calls[0], collector)
        self.assertTrue(collector.complete())

    def test_on_done_runs_on_the_reader_thread(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        conn.open()
        done = Recorder()
        conn.request_async([ASK], Counting(), done, timeout=1.0)
        self.assertTrue(done.wait_for())
        self.assertIs(done.threads[0], conn._thread)

    def test_on_done_is_called_on_timeout_too(self):
        conn, fake = self.make()
        conn.open()
        done = Recorder()
        conn.request_async([ASK], Counting(), done, timeout=0.3)
        self.assertTrue(done.wait_for())
        self.assertFalse(done.calls[0].complete())

    def test_busy_returns_false(self):
        conn, fake = self.make()
        conn.open()
        first = Recorder()
        self.assertTrue(conn.request_async([ASK], Counting(), first, timeout=0.5))
        self.assertFalse(conn.request_async([ASK], Counting(), Recorder(), timeout=0.5))
        self.assertEqual(fake.sent, [ASK])          # the second one sent nothing
        self.assertTrue(first.wait_for())

    def test_can_be_started_from_a_listener(self):
        # The safe way to ask the amp something from the reader thread.
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        done = Recorder()
        conn.add_listener(lambda msg: conn.request_async([ASK], Counting(), done, timeout=1.0))
        conn.open()
        fake.arrive(OTHER)
        self.assertTrue(done.wait_for())
        self.assertTrue(done.calls[0].complete())


def within(limit, fn, *args, **kwargs):
    """ Run fn on another thread. Returns ("ok", result) or ("raised", error),
    or ("hung", None) if it hasn't finished after `limit` seconds, so a jam
    fails the test instead of freezing the whole run. """
    outcome = ["hung", None]
    def run():
        try:
            outcome[:] = ["ok", fn(*args, **kwargs)]
        except Exception as e:
            outcome[:] = ["raised", e]
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(limit)
    return tuple(outcome)


class Broken(Counting):
    """ A collector whose offer() blows up, like a parser meeting an odd message. """
    def offer(self, msg):
        raise IndexError("bad chunk")


class TestAfterLost(ConnectionTest):
    def lose(self, conn, fake):
        conn.open()
        thread = conn._thread
        fake.arrive(OSError("unplugged"))
        thread.join(timeout=2)

    def test_send_after_lost_fails_fast(self):
        conn, fake = self.make()
        self.lose(conn, fake)
        with self.assertRaises(AmpDisconnected):
            conn.send(ASK)
        self.assertEqual(fake.sent, [])

    def test_request_after_lost_fails_fast(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        self.lose(conn, fake)
        result, error = within(1.0, conn.request, [ASK], Counting(), timeout=5.0)
        self.assertEqual(result, "raised")
        self.assertIsInstance(error, AmpDisconnected)

    def test_requests_after_lost_do_not_jam(self):
        conn, fake = self.make()
        self.lose(conn, fake)
        for attempt in range(2):
            result, error = within(2.0, conn.request, [ASK], Counting(), timeout=0.3)
            self.assertEqual(result, "raised", f"request {attempt + 1} hung")
        self.assertFalse(conn._request_lock.locked())
        self.assertIsNone(conn._pending)

    def test_request_cleans_up_when_nobody_rings_the_bell(self):
        # The reader is gone but nothing reported it: request() must still let go.
        conn, fake = self.make()
        conn.open()
        conn._stop_flag.set()
        conn._thread.join(timeout=2)
        result, error = within(3.0, conn.request, [ASK], Counting(), timeout=0.3)
        self.assertEqual(result, "raised")
        self.assertIsInstance(error, AmpTimeout)
        self.assertFalse(conn._request_lock.locked())
        self.assertIsNone(conn._pending)


class TestReaderSurvives(ConnectionTest):
    def test_a_broken_collector_does_not_kill_the_reader(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        conn.open()
        result, error = within(2.0, conn.request, [ASK], Broken(), timeout=1.0)
        self.assertEqual(result, "raised")
        self.assertIsInstance(error, AmpError)
        self.assertTrue(conn._thread.is_alive())

    def test_a_broken_collector_finishes_its_request_straight_away(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        conn.open()
        start = time.time()
        within(6.0, conn.request, [ASK], Broken(), timeout=5.0)
        self.assertLess(time.time() - start, 2.0)

    def test_requests_and_listeners_work_after_a_broken_collector(self):
        conn, fake = self.make(auto_reply=replies_to({ASK: [REPLY]}))
        listener = Recorder()
        conn.add_listener(listener)
        conn.open()
        within(2.0, conn.request, [ASK], Broken(), timeout=1.0)
        result, collector = within(2.0, conn.request, [ASK], Counting(), timeout=1.0)
        self.assertEqual(result, "ok")
        self.assertTrue(collector.complete())
        fake.arrive(OTHER)
        self.assertTrue(listener.wait_for())

    def test_an_unexpected_reader_error_is_reported_as_lost(self):
        # Not an OSError: the reader must still say why it stopped.
        conn, fake = self.make()
        lost = Recorder()
        conn.on_lost(lost)
        conn.open()
        fake.arrive(ValueError("something odd"))
        self.assertTrue(lost.wait_for())
        self.assertIsInstance(lost.calls[0], ValueError)


class TestOpenTwice(ConnectionTest):
    def test_open_twice_is_refused(self):
        conn, fake = self.make()
        conn.open()
        first = conn._thread
        with self.assertRaises(AmpError):
            conn.open()
        self.assertIs(conn._thread, first)
        self.assertFalse(fake.closed)

    def test_only_one_reader_after_open_twice(self):
        conn, fake = self.make()
        conn.open()
        try:
            conn.open()
        except AmpError:
            pass
        readers = [t for t in threading.enumerate() if t.name == "amp-reader" and t.is_alive()]
        self.assertEqual(len(readers), 1)


class TestRealDump(ConnectionTest):
    def test_dump_request_from_a_capture(self):
        # The amp answers the dump request with a real capture (dump chunks mixed with other messages).
        messages = capture_messages("chime_Drive.txt")
        conn, fake = self.make(auto_reply=replies_to({DUMP_REQUEST: messages}))
        conn.open()
        dump = conn.request([DUMP_REQUEST], DumpCollector(), timeout=2.0)
        self.assertEqual(dump.name(), "Chime 1: Class-A")


if __name__ == "__main__":
    unittest.main()
