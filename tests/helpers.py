"""Shared test helpers: real messages, capture loaders and the fake amp.

Everything here is used by more than one test file. A helper only one file needs
stays in that file.
"""
import queue
import threading
from pathlib import Path

from spiderweb.protocol.messages import MessageKind, classify
from spiderweb.protocol.presets import unpack
from spiderweb.service import EventType

CAPTURES = Path(__file__).resolve().parent.parent / "captures"


# --- real messages (protocol.md) ------------------------------------------------

TAP = bytes.fromhex("f000010c22054d003f00000f0005000000080000020004000000767a401d420000000000f7")   # 157 bpm
GAIN_REPORT = bytes.fromhex(
    "f000010c22054d0008000107000400000010000000002a0000002500010000040000007f407e7e3f00000000f7")   # Gain (2A:25), about 0.99
# The amp's answer to a set, from captures/set_pace.txt (section 8).
SET_ANSWER = bytes.fromhex("f000010c22054d000900000b00010000000400000000000000000000f7")
# The amp's answer to a whole upload (the save), from captures/windows/save.txt (section 8).
UPLOAD_ANSWER = bytes.fromhex("f000010c22054d013600000b00010000000400000000000000000000f7")

# Preset-list entries from captures/handshake_replies.txt (section 4). More are in test_presets.py.
ACOUSTIC = bytes.fromhex(                     # short layout
    "f000010c22054d01040001080001000000110000000000000000090000000041636f75730074696300000000f7")
USER_1 = bytes.fromhex(                       # short layout
    "f000010c22054d010c00010600010000000f0000000000000000070000000055736572200031000000000000f7")
BASS_LONG = bytes.fromhex(                    # long layout
    "f000010c22054d012f00020400010000001d00000100000000000938002500000000007d18375c4f6204000000050000004261730073000000000000f7")

# Preset-list requests from spiderweb/handshake.txt (lines 17, 21 and 61).
SHORT_0 = bytes.fromhex("f000010c22054d010300000b00060000000400000000000000000000f7")
SHORT_5 = bytes.fromhex("f000010c22054d010700000b00060000000400000000050000000000f7")
LONG_0 = bytes.fromhex("f000010c22054d012f00000b000e0000000400000000000000000000f7")


def is_set(msg):
    """ A 37-byte set message (the second of a set's two messages), on channel 0.

    An upload's header is also 37 bytes with 0F at msg[11], but on channel 1. """
    return len(msg) == 37 and msg[7] == 0 and msg[11] == 0x0F


# --- captures ---------------------------------------------------------------------

def capture_messages(name):
    """ Every hex message in a capture file (the last word of each line; other lines skipped). """
    messages = []
    for line in (CAPTURES / name).read_text().splitlines():
        words = line.split()
        if not words:
            continue
        try:
            messages.append(bytes.fromhex(words[-1]))
        except ValueError:
            continue
    return messages


def preset_select_section(name, value):
    """ The messages logged under 'value N:' in a tools/preset_select.py log. """
    messages, inside = [], False
    for line in (CAPTURES / name).read_text().splitlines():
        if line.startswith("value"):
            inside = line.split(":")[0].split()[1] == str(value)
            continue
        if inside and line.strip():
            messages.append(bytes.fromhex(line.strip()))
    return messages


def chime_dump():
    """ A real dump of Chime 1: Class-A, mixed with other messages (as the amp answers a dump request). """
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


# --- the fake amp -------------------------------------------------------------------

class FakeTransport:
    """ Stands in for AmpTransport.

    Everything the "amp" sends goes through one queue. Tests put messages (or an
    exception, which is raised by the read) into it with `arrive()`. `auto_reply`
    is called with each sent message and returns the messages the amp answers with.
    """
    def __init__(self, auto_reply=None):
        self.incoming = queue.Queue()
        self.sent = []
        self.auto_reply = auto_reply or (lambda msg: [])
        self.fail_send = False
        self.closed = False

    def arrive(self, *items):
        for item in items:
            self.incoming.put(item)

    def send(self, msg):
        if self.fail_send:
            raise OSError("send failed")
        self.sent.append(msg)
        self.arrive(*self.auto_reply(msg))

    def read_messages(self, quiet=0.05, limit=1.0):
        """ Handshake-style read: everything waiting right now. """
        msgs = []
        while True:
            try:
                item = self.incoming.get_nowait()
            except queue.Empty:
                return msgs
            if isinstance(item, Exception):
                raise item
            msgs.append(item)

    def read(self, timeout):
        try:
            item = self.incoming.get(timeout=timeout)
        except queue.Empty:
            return []
        if isinstance(item, Exception):
            raise item
        return [item]

    def close(self):
        self.closed = True


def replies_to(table):
    """ auto_reply from a dict: sent message -> list of replies. """
    return lambda msg: table.get(msg, [])


def answers_sets(other=None):
    """ auto_reply for the fake: answers every set with SET_ANSWER, and anything else with `other`. """
    other = other or (lambda msg: [])
    return lambda msg: [SET_ANSWER] if is_set(msg) else other(msg)


def is_upload_header(msg):
    """ An upload's first message (protocol.md section 8, "Uploads"): 37 bytes on channel 1,
    16 bytes of data (msg[10:12] = 00 0F) that start 0C 00 00 00. """
    return (len(msg) == 37 and msg[7] == 1 and msg[9:12] == b"\x00\x00\x0f"
            and unpack(msg)[:4] == b"\x0c\x00\x00\x00")


class AnswersUploads:
    """ auto_reply for the fake that answers an upload as the amp does: once, with
    UPLOAD_ANSWER, after the piece that completes the length given in the header.
    Everything else goes to `other`. `uploads` keeps (slot, data) of each finished one;
    set `answer` to False for an amp that never answers. """
    def __init__(self, other=None):
        self.other = other or (lambda msg: [])
        self.uploads = []
        self.answer = True
        self._left = None

    def __call__(self, msg):
        if is_upload_header(msg):
            head = unpack(msg)
            self._slot = int.from_bytes(head[8:12], "little")
            self._left = int.from_bytes(head[12:16], "little")
            self._data = bytearray()
            return []
        if self._left and msg[7] == 1 and len(msg) > 20:
            piece = unpack(msg)[:(msg[10] << 4 | msg[11]) + 1]
            self._data += piece
            self._left -= len(piece)
            if self._left <= 0:
                self._left = None
                self.uploads.append((self._slot, bytes(self._data)))
                return [UPLOAD_ANSWER] if self.answer else []
            return []
        return self.other(msg)


# --- callbacks that record ------------------------------------------------------------

class Recorder:
    """ A callback that keeps every call's argument, and can wait for some to arrive. """
    def __init__(self, action=None):
        self.calls = []
        self.threads = []
        self.action = action
        self._arrived = threading.Condition()

    def __call__(self, arg):
        if self.action:
            self.action(arg)
        with self._arrived:
            self.calls.append(arg)
            self.threads.append(threading.current_thread())
            self._arrived.notify_all()

    def wait_for(self, count=1, timeout=2.0):
        with self._arrived:
            return self._arrived.wait_for(lambda: len(self.calls) >= count, timeout)


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
