"""Phase 6 tests: AmpService keeps itself connected (protocol.md section 9).

The amp is a FakeTransport, and every connection gets a new one, as after a real
replug. The fake can be missing (AmpNotFound, as when it's off or unplugged), not
ready (no preset names in the handshake, as straight after power-on), or deaf to
sets (as after a set sent too soon, protocol.md section 8).

The API these expect (the phase 6 walkthrough):
  AmpService(amp_factory, reconnect_delays=(...))   seconds between failed attempts
  keep_connected()                                  connects in the background, and again after any loss
  stop()                                            ends that, and closes the amp
"""
import threading
import time
import unittest

from spiderweb.amp import Amp
from spiderweb.connection import Connection
from spiderweb.errors import AmpError, AmpNotFound, AmpTimeout
from spiderweb.protocol.messages import DUMP_REQUEST
from spiderweb.service import AmpService, ConnectionState, EventType
from tests.helpers import (
    ACOUSTIC,
    GAIN_REPORT,
    SET_ANSWER,
    SHORT_5,
    Events,
    FakeTransport,
    capture_messages,
    is_set,
)

FAST = (0.05, 0.1, 0.2)            # reconnect delays for tests
WAIT = 3.0                          # how long a test waits for something to happen


class FakeAmps:
    """ The amp_factory for these tests: a new FakeTransport for every connection.

    missing: how many more connections fail with AmpNotFound
    presets_ready: whether the handshake's preset-list request gets an entry
    sets_answered: whether sets get the amp's answer
    """
    HANDSHAKE = [SHORT_5, DUMP_REQUEST]          # one preset-list request, then the dump trigger

    def __init__(self, missing=0, presets_ready=True):
        self.missing = missing
        self.presets_ready = presets_ready
        self.sets_answered = True
        self.fakes = []
        self.attempts = []                       # time of every connection attempt
        self.lock = threading.Lock()

    def answer(self, msg):
        if msg == SHORT_5:
            return [ACOUSTIC] if self.presets_ready else []
        if msg == DUMP_REQUEST:
            return capture_messages("chime_Drive.txt")
        if is_set(msg):
            return [SET_ANSWER] if self.sets_answered else []
        return []

    def transport(self):
        with self.lock:
            self.attempts.append(time.time())
            if self.missing > 0:
                self.missing -= 1
                raise AmpNotFound("no amp (test)")
            fake = FakeTransport(auto_reply=self.answer)
            self.fakes.append(fake)
            return fake

    def __call__(self):
        return Amp(Connection(list(self.HANDSHAKE), transport_factory=self.transport))

    @property
    def current(self):
        return self.fakes[-1]


class ReconnectTest(unittest.TestCase):
    def make(self, **amp_args):
        self.amps = FakeAmps(**amp_args)
        self.service = AmpService(amp_factory=self.amps, reconnect_delays=FAST)
        self.events = Events()
        self.service.on_change(self.events)
        self.addCleanup(self.service.stop)
        return self.service, self.amps, self.events

    def connections(self):
        """ How many CONNECTED events so far. """
        return self.events.connection_states().count(ConnectionState.CONNECTED)

    def wait_connected(self, count=1):
        ok = self.events.wait_for(lambda e: self.connections() >= count, WAIT)
        self.assertTrue(ok, f"expected {count} connection(s), got {self.connections()}: "
                            f"{self.events.connection_states()}")

    def lose(self):
        """ Unplug: the current connection's read fails, as on the real amp. """
        self.amps.current.arrive(OSError(19, "No such device"))


class TestKeepConnected(ReconnectTest):
    def test_it_connects(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        self.assertEqual(service.presets(), {5: "Acoustic"})
        self.assertEqual(service.state().preset_name, "Chime 1: Class-A")

    def test_it_returns_straight_away(self):
        # The server calls it at boot, even with the amp off.
        service, amps, events = self.make(missing=1000)
        start = time.time()
        service.keep_connected()
        self.assertLess(time.time() - start, 0.5)

    def test_it_waits_for_an_amp_that_isnt_there_yet(self):
        service, amps, events = self.make(missing=3)
        service.keep_connected()
        self.wait_connected()
        self.assertEqual(len(amps.attempts), 4)

    def test_failed_attempts_back_off(self):
        service, amps, events = self.make(missing=5)
        service.keep_connected()
        self.wait_connected()
        gaps = [b - a for a, b in zip(amps.attempts, amps.attempts[1:])]
        # FAST is 0.05, 0.1, 0.2, then 0.2 again: each gap at least its delay.
        for gap, delay in zip(gaps, (0.05, 0.1, 0.2, 0.2, 0.2)):
            self.assertGreaterEqual(gap, delay * 0.9, gaps)

    def test_calling_it_twice_keeps_one_connection(self):
        service, amps, events = self.make()
        service.keep_connected()
        service.keep_connected()
        self.wait_connected()
        time.sleep(0.3)
        self.assertEqual(len(amps.fakes), 1)


class TestReconnect(ReconnectTest):
    def test_a_lost_amp_is_reconnected(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        self.lose()
        self.wait_connected(2)
        self.assertEqual(len(amps.fakes), 2)
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)

    def test_the_loss_is_reported_with_its_error(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        self.lose()
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                                        and "error" in e.data, WAIT))
        lost = [e for e in events.of(EventType.CONNECTION_CHANGED) if "error" in e.data][0]
        self.assertEqual(lost.data["state"], ConnectionState.DISCONNECTED)
        self.assertIn("No such device", lost.data["error"])

    def test_the_old_device_is_closed(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        first = amps.current
        self.lose()
        self.wait_connected(2)
        self.assertTrue(first.closed)
        self.assertFalse(amps.current.closed)

    def test_unplugged_for_a_while(self):
        # Lost, then missing for a few attempts (the cable is out), then back.
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        amps.missing = 3
        self.lose()
        self.wait_connected(2)
        self.assertEqual(len(amps.fakes), 2)

    def test_lost_again_after_a_reconnect(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        for count in (2, 3):
            self.lose()
            self.wait_connected(count)
        self.assertEqual(len(amps.fakes), 3)

    def test_stale_state_is_cleared(self):
        # After a power-cycle the amp has reloaded its preset: old values are wrong, and
        # the new handshake's dump gives the real ones (test_dump_values.py).
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        service.select_preset(4)          # first: the Chime capture includes a Drive report
        service.set("drive", 0.5)
        self.assertEqual(service.get("drive"), 0.5)
        self.lose()
        self.wait_connected(2)
        self.assertAlmostEqual(service.get("drive"), 0.9004, places=3)   # from the new dump, not 0.5
        self.assertIsNone(service.state().preset_number)
        self.assertEqual(service.state().preset_name, "Chime 1: Class-A")   # from the new handshake

    def test_messages_after_a_reconnect_are_handled(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        self.lose()
        self.wait_connected(2)
        amps.current.arrive(GAIN_REPORT)
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.PARAMETER_CHANGED, WAIT))


class TestNotReady(ReconnectTest):
    def test_no_preset_names_means_not_ready(self):
        # Straight after power-on the handshake gets the dump but no preset names.
        service, amps, events = self.make(presets_ready=False)
        with self.assertRaises(AmpError):
            service.start()
        self.assertEqual(service.state().connection, ConnectionState.DISCONNECTED)
        self.assertTrue(amps.current.closed)

    def test_it_tries_again_until_the_names_come(self):
        service, amps, events = self.make(presets_ready=False)
        service.keep_connected()
        self.assertTrue(events.wait_for(lambda e: len(amps.fakes) >= 2, WAIT))
        amps.presets_ready = True
        self.wait_connected()
        self.assertEqual(service.presets(), {5: "Acoustic"})

    def test_a_handshake_without_a_preset_list_is_fine(self):
        # Only a handshake that asks for the list needs names back.
        service, amps, events = self.make(presets_ready=False)
        amps.HANDSHAKE = [DUMP_REQUEST]
        service.start()
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)
        self.assertEqual(service.presets(), {})


class TestSetTimeout(ReconnectTest):
    def test_an_unanswered_set_raises_and_reconnects(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        amps.sets_answered = False
        with self.assertRaises(AmpTimeout):
            service.set("drive", 0.5)
        amps.sets_answered = True
        self.wait_connected(2)
        self.assertEqual(len(amps.fakes), 2)
        service.set("drive", 0.5)                       # sets work again on the new connection
        self.assertEqual(service.get("drive"), 0.5)

    def test_the_reconnect_says_why(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        amps.sets_answered = False
        with self.assertRaises(AmpTimeout):
            service.set("drive", 0.5)
        self.assertTrue(events.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                                        and e.data["state"] == ConnectionState.DISCONNECTED
                                        and "error" in e.data, WAIT))


class TestStop(ReconnectTest):
    def supervisors(self):
        return [t for t in threading.enumerate() if t.name == "amp-supervisor" and t.is_alive()]

    def test_stop_ends_it(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        service.stop()
        self.assertEqual(service.state().connection, ConnectionState.DISCONNECTED)
        self.assertTrue(amps.current.closed)
        self.assertEqual(self.supervisors(), [])

    def test_no_reconnect_after_stop(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        service.stop()
        time.sleep(0.5)
        self.assertEqual(len(amps.fakes), 1)
        self.assertEqual(self.connections(), 1)

    def test_stop_while_waiting_for_the_amp_is_quick(self):
        service, amps, events = self.make(missing=1000)
        service.keep_connected()
        time.sleep(0.3)
        start = time.time()
        service.stop()
        self.assertLess(time.time() - start, 1.0)
        self.assertEqual(self.supervisors(), [])
        attempts = len(amps.attempts)
        time.sleep(0.4)
        self.assertEqual(len(amps.attempts), attempts)        # nothing more after stop

    def test_keep_connected_again_after_stop(self):
        service, amps, events = self.make()
        service.keep_connected()
        self.wait_connected()
        service.stop()
        service.keep_connected()
        self.wait_connected(2)
        self.assertEqual(len(amps.fakes), 2)


class TestStartAgain(ReconnectTest):
    """ 6a: start() itself, without keep_connected(). """

    def test_start_after_a_loss_closes_the_old_device(self):
        service, amps, events = self.make()
        service.start()
        first = amps.current
        self.lose()
        self.assertTrue(events.wait_for(lambda e: e.data.get("state") == ConnectionState.DISCONNECTED, WAIT))
        service.start()
        self.assertTrue(first.closed)
        self.assertEqual(service.state().connection, ConnectionState.CONNECTED)

    def test_two_starts_at_once_make_one_connection(self):
        service, amps, events = self.make()
        threads = [threading.Thread(target=service.start) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=WAIT)
        self.assertEqual(len(amps.fakes), 1)
        self.assertEqual(self.connections(), 1)


if __name__ == "__main__":
    unittest.main()
