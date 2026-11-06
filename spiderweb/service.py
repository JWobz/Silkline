"""
service.py

The amp as the rest of the program sees it (docs/api.md).

AmpService owns one Amp: it keeps the amp's state up to date from the
messages it sends, turns them into Events for on_change() callbacks, and
offers the commands the server will use (set, get, select_preset, presets).

Threads: commands run on the caller's thread. handle_message, _on_preset_dump
and _handle_lost run on the connection's reader thread, and so do the
callbacks they trigger.
"""

import threading
from dataclasses import dataclass, field, replace
from enum import Enum

from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.errors import AmpDisconnected
from spiderweb.logger import Logger
from spiderweb.protocol.dump import DumpCollector
from spiderweb.protocol.knob import settle_position
from spiderweb.protocol.messages import MessageKind, classify
from spiderweb.protocol.parameters import BY_NAME, KNOWN_PARAMETERS
from spiderweb.protocol.presets import preset_names


class ConnectionState(Enum):
    """Whether the service is talking to the amp."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class EventType(Enum):
    """What an Event is about. The data each one carries:

    CONNECTION_CHANGED  {"state": ConnectionState}, plus "error" (a repr) when the amp was lost
    PRESET_CHANGED      {"number": select value, or None after a knob move, "name": str}
    PARAMETER_CHANGED   {"key": (block, id, sub), "name": str or None if unknown, "value": 0 to 1}
    KNOB_MOVED          {"position": 0 to 15, once the preset knob has settled}
    TAP                 {"bpm": float}
    SAVE_PRESSED        {}
    """
    CONNECTION_CHANGED = "connection_changed"
    PRESET_CHANGED = "preset_changed"
    PARAMETER_CHANGED = "parameter_changed"
    KNOB_MOVED = "knob_moved"
    TAP = "tap"
    SAVE_PRESSED = "save_pressed"


@dataclass
class AmpState:
    """Everything the service knows about the amp. None means "not known yet".

    preset_number is the select value of the last select_preset(); it goes back
    to None when the preset knob moves, because which value each knob position
    loads isn't known (protocol.md section 11). params maps a parameter key
    (block, id, sub) to its last reported value, 0 to 1.
    """
    connection: ConnectionState = ConnectionState.DISCONNECTED
    preset_number: int | None = None
    preset_name: str | None = None
    knob_position: int | None = None
    params: dict = field(default_factory=dict)
    bpm: float | None = None

    def snapshot(self):
        """Returns a copy, params included, that is safe to keep and change."""
        return replace(self, params=self.params.copy())


@dataclass(frozen=True)
class Event:
    """Something that happened, sent to on_change() callbacks. See EventType for data."""
    event_type: EventType
    data: dict

def default_amp():
    """The real amp: found on USB, opened with the recorded handshake."""
    return Amp(Connection(load_handshake()))

class AmpService:
    """The one owner of the amp: its state, its events and its commands.

    amp_factory makes the Amp when start() is called; tests pass one that
    builds an Amp on a fake transport.
    """

    def __init__(self, amp_factory=default_amp):
        self._logger = Logger(prefix="AmpService")
        self._state = AmpState()
        self._amp = None
        self.amp_factory = amp_factory
        self._threading_lock = threading.Lock()
        self._handshake_replies = []
        self._callbacks = []
        self._knob_candidates = []
        self._presets = {}

    def set_connection(self, new_state: ConnectionState):
        """Records the connection state and sends CONNECTION_CHANGED."""
        with self._threading_lock:
            self._state.connection = new_state
        self._emit(EventType.CONNECTION_CHANGED, {"state": new_state})


    def start(self):
        """Makes the amp, connects and runs the handshake. Does nothing if already started.

        The preset name comes from the dump the handshake asks for, and the
        preset list (presets()) from its preset-list requests, so no extra
        request is needed. Handshake replies aren't treated as changes.
        On failure it closes what it opened, ends DISCONNECTED and re-raises
        (AmpNotFound if no amp is plugged in); start() can then be tried again.
        """
        if self._state.connection != ConnectionState.DISCONNECTED:
            return
        self.set_connection(ConnectionState.CONNECTING)
        try:
            self._amp = self.amp_factory()
            self._amp.add_listener(self.handle_message)
            self._amp.on_lost(self._handle_lost)
            self._handshake_replies = self._amp.connect()
            collector = DumpCollector()
            for lines in self._handshake_replies:
                for reply in lines:
                    collector.offer(reply)
            presets = preset_names(self._amp.handshake_lines, self._handshake_replies)
            with self._threading_lock:
                self._presets = presets
                if collector.complete():
                    self._state.preset_name = collector.name()
        except Exception:
            if self._amp is not None:
                self._amp.close()
                self._amp = None
            self.set_connection(ConnectionState.DISCONNECTED)
            raise

        self.set_connection(ConnectionState.CONNECTED)

    def stop(self):
        """Closes the amp and ends DISCONNECTED. Safe to call more than once, or before start()."""
        if self._amp is None:
            return
        self._amp.close()
        self._amp = None
        self.set_connection(ConnectionState.DISCONNECTED)

    def set(self, name, value):
        """Sets a parameter by name (any case, e.g. "drive") to a value from 0 to 1.

        Doesn't change the state itself: the amp reports the new value back and
        handle_message records it, so get() shows it a moment later.
        Raises AmpDisconnected if not connected, ValueError for an unknown or
        unsettable parameter or a value out of range.
        """
        if self._amp is None:
            raise AmpDisconnected("not connected")
        param = BY_NAME.get(name.lower())
        if param is None:
            raise ValueError("Cannot find parameter to set")
        self._amp.set_parameter(param, value)

    def get(self, name):
        """The last value the amp reported for a parameter (0 to 1), or None if none yet.

        Raises ValueError for an unknown name. Works when not connected.
        """
        param = BY_NAME.get(name.lower())
        if param is None:
            raise ValueError("Cannot find parameter to get")
        with self._threading_lock:
            return self._state.params.get(param.key) 

    def select_preset(self, n):
        """Loads preset n (an index into the amp's preset list) and returns its name.

        Waits for the preset's dump (up to amp.DUMP_TIMEOUT), then updates the
        state and sends PRESET_CHANGED. Nothing is saved on the amp. Don't call it
        from an on_change callback. Raises AmpDisconnected if not connected,
        AmpTimeout if no dump comes back (the state is then unchanged).
        """
        if self._amp is None:
            raise AmpDisconnected("not connected")
        dump = self._amp.select_preset(n)
        name = dump.name()
        with self._threading_lock:
            self._state.preset_number = n
            self._state.preset_name = name
        self._emit(EventType.PRESET_CHANGED, {"number": n, "name": name})
        return name

    def _emit(self, event_type, data):
        """Sends an Event to every callback. One failing callback doesn't stop the others.

        Call it after leaving the lock, so a callback can call state().
        """
        event = Event(event_type, data)
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                self._logger.error(f"Callback failed: {e!r}")

    def state(self):
        """A copy of the current AmpState. Safe from any thread."""
        with self._threading_lock:
            return self._state.snapshot()

    def on_change(self, callback):
        """Calls callback(event) for every Event.

        Most events arrive on the reader thread, so keep callbacks quick and
        don't call select_preset() from one.
        """
        self._callbacks.append(callback)

    def handle_message(self, msg):
        """Updates the state from one message and sends the events it causes.

        The connection's listener, so it runs on the reader thread.
        - Parameter reports count only when they move by 0.02 or more (knob jitter),
          and 2A/02 is ignored (protocol.md section 7).
        - Preset-knob positions bounce while it turns; the position is settled at
          the status message that follows, and then the new preset's name is asked
          for with refresh_preset (the waiting kind isn't allowed here).
        - Everything else (preset-list entries, unknown shapes) is ignored.
        The state changes inside the lock; the amp is asked and events are sent after it.
        """
        classified_message = classify(msg)
        events = []
        knob_settled = False

        with self._threading_lock:
            match classified_message[0]:
                case MessageKind.PARAM:
                    if classified_message[1] == (0x2A, 0x02, 0):
                        return

                    param_id, param_value = classified_message[1:]
                    if (
                        param_id not in self._state.params
                        or abs(self._state.params[param_id] - param_value) >= 0.02
                    ):
                        events.append(
                            (
                                EventType.PARAMETER_CHANGED,
                                {
                                    "key": param_id,
                                    "name": KNOWN_PARAMETERS.get(param_id),
                                    "value": param_value,
                                },
                            )
                        )
                        self._state.params[param_id] = param_value
                case MessageKind.PRESET_CHANGE:
                    preset_value = classified_message[1]
                    self._knob_candidates.append(preset_value)
                case MessageKind.STATUS:
                    if not self._knob_candidates:
                        return
                    knob_position = settle_position(
                        self._knob_candidates, self._state.knob_position
                    )
                    self._state.knob_position = knob_position
                    self._knob_candidates = []
                    events.append((EventType.KNOB_MOVED, {"position": knob_position}))
                    knob_settled = True
                case MessageKind.TAP:
                    bpm = classified_message[1]
                    self._state.bpm = bpm
                    events.append((EventType.TAP, {"bpm": bpm}))
                case MessageKind.SAVE:
                    events.append((EventType.SAVE_PRESSED, {}))
                case _:
                    return
                
        if knob_settled and self._amp is not None:  
            if not self._amp.refresh_preset(self._on_preset_dump):
                self._logger.warning("busy, preset name not refreshed")

        for event_type, event_data in events:
            self._emit(event_type, event_data)

    def _on_preset_dump(self, dump):
        """on_done for the refresh after a knob move (reader thread).

        A complete dump sets the preset name, clears preset_number and sends
        PRESET_CHANGED. An incomplete one (timed out) changes nothing.
        """
        if dump.complete():
            name = dump.name()
            with self._threading_lock:
                self._state.preset_name = name
                self._state.preset_number = None
            self._emit(EventType.PRESET_CHANGED, {"number": None, "name": name})
        else:
            self._logger.warning("Preset dump is incomplete")

    def _handle_lost(self, error):
        """Called once by the connection when the amp stops responding.

        Ends DISCONNECTED and says why in the event. Keeps the amp so stop()
        can still close it. (Reconnecting comes in phase 6.)
        """
        with self._threading_lock:
            self._state.connection = ConnectionState.DISCONNECTED
        self._emit(EventType.CONNECTION_CHANGED, {"state": ConnectionState.DISCONNECTED, "error": repr(error)})
        

    def presets(self):
        """Every preset's name, as {index: name}, read from the handshake by start().

        index is the value select_preset() takes. Returns a copy, so changing it
        changes nothing here. Empty before the first start(); kept after stop(),
        and read again by the next start(). Safe from any thread.
        """
        with self._threading_lock:
            return dict(self._presets)