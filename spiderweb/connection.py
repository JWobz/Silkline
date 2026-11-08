"""
connection.py

The connection to the amp: the handshake, one reader thread, and requests.

Connection owns the transport. open() sends the handshake; then a reader thread
(amp-reader) reads everything. A message goes to the waiting request's collector
if it takes it, and to every listener otherwise. Only one request waits at a time.
Amp builds on this; nothing above Amp uses it directly.
"""

import threading
import time
from dataclasses import dataclass

from spiderweb.errors import AmpDisconnected, AmpError, AmpTimeout
from spiderweb.logger import Logger
from spiderweb.transport import AmpTransport, find_device


@dataclass
class _Pending:
    """The request waiting for its reply: what collects it, until when, and who to tell."""
    collector: object
    deadline: float
    on_finish: callable


class Connection:
    """Talks to the amp over one transport, with a reader thread while open.

    handshake_lines are sent by open(), one at a time, each followed by a read.
    transport_factory makes the transport (tests pass a fake). Messages that no
    request takes go to the listeners (add_listener), on the reader thread. When the
    amp stops answering (a read or a send fails) the on_lost callbacks run once.
    """

    def __init__(self, handshake_lines, transport_factory=lambda: AmpTransport(find_device())):
        self._logger = Logger(prefix="Connection")
        self._handshake_lines = handshake_lines
        self._transport_factory = transport_factory
        self._transport = None
        self._thread = None
        self._stop_flag = threading.Event()
        self._listeners = []

        self._send_lock = threading.Lock()
        self._lost_callbacks = []
        self._is_lost = False

        self._request_lock = threading.Lock()
        self._pending = None
        self._pending_lock = threading.Lock()

    @property
    def handshake_lines(self):
        """The handshake lines open() sends, in order."""
        return self._handshake_lines

    def open(self):
        """Opens the transport, sends the handshake and starts the reader thread.

        Waiting messages are read and dropped first. Returns the replies, one list per
        handshake line. If anything fails, the transport is closed and the error
        raised. Raises AmpError if already open.
        """
        if self._transport is not None:
            raise AmpError("already open")
        self._is_lost = False
        try:
            self._transport = self._transport_factory()
            self._transport.read_messages(quiet=0.2, limit=1)  # flush messages
            replies = []
            for line in self._handshake_lines:
                self._transport.send(line)
                replies.append(self._transport.read_messages())
        except Exception:
            if self._transport is not None:
                self._transport.close()
                self._transport = None
            raise

        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run, name="amp-reader", daemon=True
        )
        self._thread.start()
        return replies

    def _run(self):
        """The reader thread: hands each message to the waiting request or the listeners.

        A listener that raises is logged and the others still run. A failed read ends
        the thread and reports the amp as lost (_handle_lost).
        """
        try:
            while not self._stop_flag.is_set():
                for message in self._transport.read(0.2):
                    if self._offer_to_pending(message):
                        continue
                    for listener in self._listeners:
                        try:
                            listener(message)
                        except Exception as e:
                            self._logger.error(f"Error running listener: {e!r}")
                self._check_deadline()
        except OSError as e:
            self._logger.error(f"Read Failed (OS): {e!r}")
            self._handle_lost(e)
        except Exception as e:
            self._logger.error(f"Read Failed: {e!r}")
            self._handle_lost(e)


    def close(self):
        """Stops the reader thread, ends a waiting request and closes the transport.

        Safe to call more than once, and from the reader thread itself (it then
        doesn't wait for itself).
        """
        self._stop_flag.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
            with self._pending_lock:
                note = self._pending
            if note is not None:
                self._finish(note)
        if self._transport is None:
            return

        self._transport.close()
        self._thread = None
        self._transport = None

    def send(self, msg):
        """Sends one message. Safe from any thread.

        Raises AmpDisconnected if not open or the amp is lost; a failed send also
        reports the amp as lost.
        """
        if self._transport is None or self._is_lost:
            raise AmpDisconnected("not connected")
        try:
            with self._send_lock:
                self._transport.send(msg)
        except OSError as e:
            self._handle_lost(e)
            raise AmpDisconnected(str(e)) from e

    def request(self, msgs, collector, timeout, gap=0):
        """Sends msgs and waits until collector is complete (it is offered every message that arrives).

        gap is a pause in seconds between messages (uploads use 0.01, as the app does).
        Returns the collector. Raises AmpTimeout if it isn't complete within timeout,
        AmpError from the reader thread (use request_async there).
        """
        if threading.current_thread() is self._thread:
            raise AmpError("request() can't be called from the reader thread; use request_async()")
        self._request_lock.acquire()
        bell = threading.Event()
        with self._pending_lock:
            note = _Pending(collector, time.time() + timeout, lambda c: bell.set())
            self._pending = note
        for i, msg in enumerate(msgs):
            if i and gap:
                time.sleep(gap)
            try:
                self.send(msg)
            except Exception:
                self._finish(note)
                raise
        if not bell.wait(timeout+1):
            self._finish(note)
        if not collector.complete():
            raise AmpTimeout(f"no complete reply within {timeout}s")
        return collector

    def request_async(self, msgs, collector, on_done, timeout):
        """Like request(), but returns at once; on_done(collector) is called when it ends.

        It ends when collector is complete or timeout passes (check
        collector.complete()), on the reader thread. Allowed from the reader thread.
        Returns False, sending nothing, if another request is waiting.
        """
        if not self._request_lock.acquire(blocking=False):
            return False
        note = _Pending(collector, time.time() + timeout, on_done)
        with self._pending_lock:
            self._pending = note
        for msg in msgs:
            try:
                self.send(msg)
            except Exception:
                self._finish(note)
                raise
        return True

    def add_listener(self, callback):
        """callback(msg) for every message no request takes, on the reader thread."""
        self._listeners.append(callback)

    def on_lost(self, callback):
        """callback(error) once when the amp is lost (a read or send failed)."""
        self._lost_callbacks.append(callback)

    def _handle_lost(self, error):
        """Ends a waiting request and runs the on_lost callbacks, the first time only."""
        with self._pending_lock:
            note = self._pending
        if note is not None:
            self._finish(note)
        if self._is_lost:
            return
        self._is_lost = True
        for callback in self._lost_callbacks:
            try:
                callback(error)
            except Exception as e:
                self._logger.error(f"Handle Lost error: {e!r}")

    def _offer_to_pending(self, message):
        """Offers a message to the waiting request's collector. True if it took it.

        A collector that raises is logged and its request ended, so one bad
        collector can't stop the reader.
        """
        with self._pending_lock:
            note = self._pending
            if note is None:
                return False
            try:
                taken = note.collector.offer(message)
                finished = taken and note.collector.complete()
            except Exception as e:
                self._logger.error(f"Error with offer: {e!r} ")
                taken, finished = True, True
        if finished:
            self._finish(note)
        return taken

    def _check_deadline(self):
        """Ends the waiting request if its timeout has passed (the reader checks often)."""
        with self._pending_lock:
            note = self._pending
            expired = note is not None and time.time() > note.deadline
        if expired:
            self._finish(note)

    def _finish(self, note):
        """Ends a request once: frees the request slot and calls its on_finish.

        Called from several places (reply, timeout, close, lost); only the first call
        for a request does anything.
        """
        with self._pending_lock:
            if self._pending is not note:
                return
            self._pending = None
        self._request_lock.release()
        note.on_finish(note.collector)
