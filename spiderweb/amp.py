"""
amp.py

The amp's commands, on top of one Connection: connect, sets, preset selects,
dumps and uploads (protocol.md sections 2 to 8).

Amp knows how to build each request and what answer to wait for. It keeps the
set counter (seq) and the upload counter, and lets one set or upload through at
a time. AmpService is its only user; nothing above it talks to the amp directly.
"""

import threading
import time
from pathlib import Path

from spiderweb.connection import Connection
from spiderweb.logger import Logger
from spiderweb.protocol.dump import DumpCollector
from spiderweb.protocol.messages import (
    DUMP_REQUEST,
    FIRST_SEQUENCE,
    FLOAT_VALUE,
    SetAnswer,
    UploadAnswer,
    build_begin_message,
    build_set_message,
    select_message,
)
from spiderweb.protocol.upload import build_upload

HANDSHAKE_PATH = Path(__file__).parent / "handshake.txt"

SET_TIMEOUT = 1.0
UPLOAD_TIMEOUT = 2.0  # seconds; the app's save was answered in about 0.1 s
DUMP_TIMEOUT = 4.0  # seconds to wait for a dump

def load_handshake(path=HANDSHAKE_PATH):
    """Reads the handshake file: one hex message per line, blank lines skipped.

    Returns the messages as a list of bytes, in order, ready for Connection.
    """
    messages = []
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                messages.append(bytes.fromhex(stripped))
    return messages



class Amp:
    """The amp's operations: set parameters, select presets and read dumps.

    Amp only builds messages and hands them to a Connection; the connection
    does the reading. Replies that aren't part of a request (parameter
    reports, knob moves, taps) go to the listeners added with add_listener().
    Sets, selects and dumps wait for the amp, so call them from your own
    thread, not from a listener.
    """
    def __init__(self, connection:Connection):
        self._logger = Logger(prefix="Amp")
        self._connection = connection
        self._seq = FIRST_SEQUENCE
        self._upload_seq = 0x10 
        self._set_lock = threading.Lock()

    @property
    def handshake_lines(self):
        """The handshake lines connect() sends; its replies come back in the same order."""
        return self._connection.handshake_lines

    def connect(self):
        """Opens the connection and runs the handshake.

        Returns the amp's replies to the handshake: one list of replies per
        line, in the order of handshake_lines. Starts the sequence number
        again, because each handshake resets the amp's counters.
        Raises AmpNotFound if no amp is plugged in.
        """
        replies = self._connection.open()
        self._seq = FIRST_SEQUENCE
        self._upload_seq = 0x10
        return replies

    def close(self):
        """Stops the reader and closes the device. Safe to call more than once."""
        self._connection.close()

    def upload(self, slot, data):
        """Sends data to the amp as an upload and waits for its answer (protocol.md section 8, "Uploads").

        slot is a preset number (a save) or upload.EDIT_BUFFER (the live preset, v1.1).
        The header uses the upload counter and the pieces the next number, so it
        moves on by 2; it's separate from the set counter. Pieces go 10 ms apart, as
        the app sends them. Holds the set lock, so no set gets in between. Raises
        AmpTimeout if the amp doesn't answer within UPLOAD_TIMEOUT, AmpDisconnected
        if not connected.
        """
        with self._set_lock:
            msgs = build_upload(self._upload_seq, slot, data)
            self._upload_seq = (self._upload_seq + 2) % 128
            self._connection.request(msgs, UploadAnswer(), UPLOAD_TIMEOUT, gap=0.01)

    def _set_raw(self, block, sub, param_id, raw5, namespace, value_type=FLOAT_VALUE, unknown=1):
        """Sets a parameter to a raw five-byte value (protocol.md section 8).

        block, sub, param_id and namespace say which parameter (see
        build_set_message); the namespace can differ from sub.

        Sends a begin message and then a set message, numbered seq and seq + 1,
        and waits for the amp's answer (the value itself is never reported back).
        A set sent before the previous one is answered makes the amp ignore all
        later sets, so the lock keeps one set at a time, from any thread.
        Blocks until answered, so don't call it from a listener (AmpError).
        Raises AmpTimeout if there is no answer within SET_TIMEOUT (sets are then
        probably dead until a new handshake), AmpDisconnected if not connected.
        """    
        with self._set_lock:
            msgs = [build_begin_message(self._seq),
                    build_set_message(self._seq+1, block, sub, param_id, raw5, namespace, value_type, unknown)]
            self._seq = (self._seq + 2) % 128   
            self._connection.request(msgs, SetAnswer(), SET_TIMEOUT)
    
    def select_preset(self, value, timeout=DUMP_TIMEOUT):
        """Loads preset `value` (an index into the amp's preset list) and returns its dump.

        Only loads the preset; nothing is saved. Waits for the whole dump, so
        call it from your own thread, not from a listener. Raises AmpTimeout
        if the dump doesn't arrive within `timeout` seconds, and ValueError
        for a value outside 0 to 127.
        """
        self._connection.send(select_message(value))
        time.sleep(0.2)
        return self.request_dump(timeout)
        
    def set_parameter(self, param, value):
        """Sets a Parameter (from protocol.parameters) to a value (see Parameter.encode).

        Returns once the amp has answered (see _set_raw). Raises ValueError, and
        sends nothing, if the parameter can't be set or the value is out of range.
        """
        if not param.settable:
            raise ValueError(f"Parameter {param.name} is not settable.")
        raw5, value_type = param.encode(value)
        self._set_raw(param.block, param.sub, param.id , raw5, param.namespace, value_type)

    def refresh_preset(self, on_done, timeout=DUMP_TIMEOUT):
        """Asks for the current preset's dump without waiting for it.

        The version to use from inside a listener, e.g. when the preset knob
        settles. Later, on the reader thread, calls on_done(collector), also
        on a timeout, so check collector.complete() before using it.
        Returns False, and sends nothing, if another request is in progress.
        """
        return self._connection.request_async([DUMP_REQUEST], DumpCollector(), on_done, timeout)

    def request_dump(self, timeout=DUMP_TIMEOUT):
        """Asks for the current preset's dump and waits for all of it.

        Returns a complete DumpCollector (dump.name() is the preset name).
        Raises AmpTimeout if it doesn't arrive within `timeout` seconds.
        Not allowed from a listener: use refresh_preset() there.
        """
        return self._connection.request([DUMP_REQUEST], DumpCollector(), timeout)
    
    def add_listener(self, callback):
        """Calls callback(message) for every message from the amp that isn't a reply to a request.

        Runs on the reader thread, so keep it quick and don't call request_dump()
        or select_preset() from it.
        """
        self._connection.add_listener(callback)

    def on_lost(self, callback):
        """Calls callback(error) once when the amp stops responding (unplugged, or a read or send fails)."""
        self._connection.on_lost(callback)
    
