"""
connection.py

Handles the connection between amp and PC 
"""

import threading
import time
from dataclasses import dataclass

from spiderweb.errors import AmpDisconnected, AmpError, AmpTimeout
from spiderweb.logger import Logger
from spiderweb.transport import AmpTransport, find_device


@dataclass
class Pending:
    collector: object
    deadline: float
    on_finish: callable


class Connection:
    def __init__(
        self, handshake_lines, transport_factory=lambda: AmpTransport(find_device())
    ):
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
        if self._transport is None or self._is_lost:
            raise AmpDisconnected("not connected")
        try:
            with self._send_lock:
                self._transport.send(msg)
        except OSError as e:
            self._handle_lost(e)
            raise AmpDisconnected(str(e)) from e

    def request(self, msgs, collector, timeout):
        if threading.current_thread() is self._thread:
            raise AmpError("request() can't be called from the reader thread; use request_async()")
        self._request_lock.acquire()
        bell = threading.Event()
        with self._pending_lock:
            note = Pending(collector, time.time() + timeout, lambda c: bell.set())
            self._pending = note
        for msg in msgs:
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
        if not self._request_lock.acquire(blocking=False):
            return False
        note = Pending(collector, time.time() + timeout, on_done)
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
        self._listeners.append(callback)

    def on_lost(self, callback):
        self._lost_callbacks.append(callback)

    def _handle_lost(self, error):
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
        with self._pending_lock:
            note = self._pending
            expired = note is not None and time.time() > note.deadline
        if expired:
            self._finish(note)

    def _finish(self, note):
        with self._pending_lock:
            if self._pending is not note:
                return
            self._pending = None
        self._request_lock.release()
        note.on_finish(note.collector)
