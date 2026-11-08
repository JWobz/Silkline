"""
service.py

The amp as the rest of the program sees it (docs/api.md).

AmpService owns one Amp: it keeps the amp's state up to date from the
messages it sends, turns them into Events for on_change() callbacks, and
offers the commands the server will use (set, get, select_preset, presets).
keep_connected() keeps it connected through unplugs, power-cycles and dead
sets (protocol.md sections 8 and 9).

Threads: commands run on the caller's thread. handle_message, _on_preset_dump
and _handle_lost run on the connection's reader thread, and so do the
callbacks they trigger. Reconnecting runs on the "amp-supervisor" thread.
Two locks: _lifecycle_lock keeps start() and stop() one at a time, and
_threading_lock guards the state. Events are only sent outside _threading_lock.
"""

import threading
from pathlib import Path

from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.errors import AmpDisconnected, AmpError, AmpTimeout
from spiderweb.logger import Logger
from spiderweb.protocol.dump import (
    DumpCollector,
    preset_data,
    read_values,
    stage_models,
)
from spiderweb.protocol.knob import settle_position
from spiderweb.protocol.messages import MessageKind, classify
from spiderweb.protocol.models import load_model_names, model_name
from spiderweb.protocol.parameters import BY_NAME, KNOWN_PARAMETERS
from spiderweb.protocol.presets import UNLOADABLE, preset_list_request, preset_names
from spiderweb.protocol.symbols import load_symbols
from spiderweb.state import AmpState, ConnectionState, Event, EventType

APP_DATA_FOLDER = Path(__file__).resolve().parent.parent / "app_data"   # the Line 6 app's res folder, never committed
RECONNECT_DELAYS = (1, 2, 5, 10, 30)   # seconds between failed connects; the last one repeats
GAIN = BY_NAME["gain"]
DRIVE = BY_NAME["drive"]

def default_amp():
    """The real amp: found on USB, opened with the recorded handshake."""
    return Amp(Connection(load_handshake()))

class AmpService:
    """The one owner of the amp: its state, its events and its commands.

    amp_factory makes a new Amp for every start(); tests pass one that builds
    an Amp on a fake transport. reconnect_delays are the waits between failed
    connects in keep_connected(), with the last one repeated; tests pass short ones.
    resource_folder holds the Line 6 app's files (its res folder, protocol.md
    section 10), which name each stage's model in state().models. Without them
    (a missing folder is logged, or None) models have numbers only.
    """

    def __init__(self, amp_factory=default_amp, reconnect_delays=RECONNECT_DELAYS, resource_folder=APP_DATA_FOLDER):
        self._logger = Logger(prefix="AmpService")
        self._state = AmpState()
        self._amp = None
        self._resource_folder = None
        self.amp_factory = amp_factory
        self._threading_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stopping = threading.Event()
        self._wake = threading.Event()
        self._supervisor = None
        self._reconnect_delays = reconnect_delays
        self._handshake_replies = []
        self._callbacks = []
        self._knob_candidates = []
        self._presets = {}
        self._pending = {}                      # set_latest: param key -> (param, value) not sent yet
        self._pending_lock = threading.Lock()
        self._draining = False                  # True while a set_latest caller is sending
        self._symbols = []
        self._model_names = {}

        if resource_folder is not None:
            self._resource_folder = Path(resource_folder)
        if self._resource_folder is not None:
            try: self._symbols = load_symbols(self._resource_folder / "defaultSymbolTable_Parker.bin")
            except FileNotFoundError: self._logger.warning("Cannot find symbols file")
            try: self._model_names = load_model_names(self._resource_folder) 
            except FileNotFoundError: self._logger.warning("Cannot find models file")

    def set_connection(self, new_state: ConnectionState):
        """Records the connection state and sends CONNECTION_CHANGED."""
        with self._threading_lock:
            self._state.connection = new_state
        self._emit(EventType.CONNECTION_CHANGED, {"state": new_state})


    def start(self):
        """Makes the amp, connects and runs the handshake. Does nothing unless DISCONNECTED.

        Closes an amp left over from a loss first. The preset name comes from
        the dump the handshake asks for, and the preset list (presets()) from
        its preset-list requests, so no extra request is needed. Handshake
        replies aren't treated as changes. Parameter values and preset_number
        are cleared, because after a power-cycle the amp has reloaded its preset.
        On failure it closes what it opened, ends DISCONNECTED and re-raises:
        AmpNotFound if no amp is plugged in, AmpError if the handshake asked for
        the preset list and got no names (straight after power-on the amp isn't
        ready for it yet, protocol.md section 9). start() can then be tried again.
        One start() or stop() runs at a time.
        """
        with self._lifecycle_lock:
            if self._state.connection != ConnectionState.DISCONNECTED:
                return
            if self._amp is not None:
                self._amp.close()
                self._amp = None
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
                presets = {i: name for i, name in presets.items() if i not in UNLOADABLE}
                asked = any(preset_list_request(line) for line in self._amp.handshake_lines)
                if asked and not presets:
                    raise AmpError("no preset list in handshake (amp not ready yet?)")
                with self._threading_lock:
                    self._presets = presets
                    self._state.preset_number = None
                    if collector.complete():
                        self._state.preset_name = collector.name()
                        self._state.params = read_values(collector)
                        self._state.models = self._models(collector)
                    else:
                        self._state.params = {}
                        self._state.models = {}

            except Exception:
                if self._amp is not None:
                    self._amp.close()
                    self._amp = None
                self.set_connection(ConnectionState.DISCONNECTED)
                raise

            self.set_connection(ConnectionState.CONNECTED)
        

    def stop(self):
        """Ends keep_connected(), closes the amp and ends DISCONNECTED.

        Waits (up to 5 s) for the supervisor thread to finish first, outside the
        lifecycle lock, because the supervisor may be inside start() waiting for it.
        Sends DISCONNECTED only if the state wasn't already DISCONNECTED (after a
        loss it is). Safe to call more than once, or before start().
        """
        self._stopping.set()
        self._wake.set()
        supervisor = self._supervisor
        if supervisor is not None and supervisor is not threading.current_thread():
            supervisor.join(timeout=5)
        self._supervisor = None
        self._wake.clear()
        with self._lifecycle_lock:
            if self._amp is None:
                return
            self._amp.close()
            self._amp = None
            if self._state.connection != ConnectionState.DISCONNECTED:
                self.set_connection(ConnectionState.DISCONNECTED)

    def keep_connected(self):
        """Connects in the background, and reconnects whenever the amp is lost.

        Returns straight away, even with no amp plugged in. The "amp-supervisor"
        thread calls start() until it works, waiting reconnect_delays between
        tries, then sleeps until the connection is lost or a set goes unanswered,
        and starts again. Watch CONNECTION_CHANGED events to follow it. Does
        nothing if it's already running; stop() ends it.
        """
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._stopping.clear()
        self._supervisor = threading.Thread(target=self._supervise, name="amp-supervisor", daemon=True)
        self._supervisor.start()

    def _supervise(self):
        """The supervisor thread's loop (see keep_connected).

        After a failed start() it waits the next delay (stop() cuts the wait
        short); after a good one the delays start again from the first. _wake is
        set by _handle_lost, _reconnect_soon and stop().
        """
        delays = iter(self._reconnect_delays)
        while not self._stopping.is_set():
            if self.state().connection != ConnectionState.CONNECTED:
                try:
                    self.start()
                    delays = iter(self._reconnect_delays)
                except Exception as e:
                    self._logger.warning(f"connect failed {e!r}")
                    self._stopping.wait(next(delays, self._reconnect_delays[-1]))
                    continue
            self._wake.wait()
            self._wake.clear()

    def _models(self, dump):
        """Each stage's model in a dump: {stage: {"number", "id", "name"}}.

        number is what the amp sends; id the symbol table's name for it and name
        the .models files' name, each None without the Line 6 files (or for a
        model they don't know).
        """
        models = {}
        for stage, number in stage_models(dump).items():
            symbol = name = None
            if (number < len(self._symbols)):
                symbol = self._symbols[number]
                name = model_name(symbol, self._model_names)
            models[stage] = {"number": number, "id": symbol, "name": name} 
        return models
    
    def _resolve(self, param):
        """The parameter a name really means: Gain and Drive are the same knob.

        Each amp model has either Gain (0x25) or Drive (0x26) (protocol.md section 3,
        point 5), and the preset's dump puts only that one in params. So "gain" and
        "drive" both mean whichever one params has. If it has neither or both (no
        dump yet), the one asked for is returned. A set records its value in params,
        so after a set with no dump the other name follows it. Every other parameter
        is returned as it is.
        """
        if param not in (GAIN, DRIVE):
            return param
        with self._threading_lock:
            params = self._state.params
            if DRIVE.key in params and GAIN.key not in params:
                return DRIVE
            if GAIN.key in params and DRIVE.key not in params:
                return GAIN
            return param

    def get(self, name):
        """A parameter's value: from the latest dump, or a later set or knob report.

        Floats (0 to 1 for most, the parameter's low to high for others), or 0 / 1 for
        on/off switches. "gain" and "drive" read whichever of the two the current preset
        uses (see _resolve). None for a parameter that has no
        value yet. Raises ValueError for an unknown name. Works when not connected.
        """
        param = BY_NAME.get(name.lower())
        if param is None:
            raise ValueError("Cannot find parameter to get")
        param = self._resolve(param)
        with self._threading_lock:
            return self._state.params.get(param.key) 
        
    def set(self, name, value):
        """Sets a parameter by name (any case, e.g. "volume") to a value.

        The value must suit the parameter (Parameter.encode): low to high for a float
        (0 to 1 for most), 0 or 1 (or False / True) for an on/off switch. "gain" and
        "drive" set whichever of the two the current preset uses (see _resolve), and
        the event names that one. Waits for the amp's answer, then records the value and sends
        PARAMETER_CHANGED. The amp never reports a set back (protocol.md
        section 8), so what was sent is what get() shows; later knob turns
        still come in through handle_message. Don't call it from an on_change
        callback. Raises AmpDisconnected if not connected, AmpTimeout if the
        amp doesn't answer (the state is then unchanged, and because sets are
        then probably dead, protocol.md section 8, the supervisor is asked to
        reconnect), ValueError for an unknown or unsettable parameter or a value
        out of range.
        """
        param = self._check(name, value)
        self._send(param, value)

    def _check(self, name, value):
        """The Parameter to set for a name, checked before anything is sent.

        Raises AmpDisconnected if not connected, ValueError for an unknown or
        unsettable name or a value that doesn't suit the parameter (Parameter.encode).
        "gain" and "drive" come back as whichever one the current preset uses (see
        _resolve), and the value is checked against that one.
        """
        if self._amp is None:
            raise AmpDisconnected("not connected")
        param = BY_NAME.get(name.lower())
        if param is None:
            raise ValueError("Cannot find parameter to set")
        if not param.settable:
            raise ValueError(f"{param.name} can't be set")
        
        param = self._resolve(param)
        param.encode(value)
        return param

    def _send(self, param, value):
        """One set: waits for the amp's answer, then records the value and sends PARAMETER_CHANGED.

        If the amp doesn't answer, sets are probably dead (protocol.md section 8):
        it asks the supervisor to reconnect and re-raises the AmpTimeout.
        """     
        try:
            amp = self._amp
            if amp is None:
                raise AmpDisconnected("not connected")
            amp.set_parameter(param, value)
        except AmpTimeout:
            self._logger.warning("set not answered; reconnecting")
            self._reconnect_soon()
            raise        
        with self._threading_lock:
            self._state.params[param.key] = value
        self._emit(EventType.PARAMETER_CHANGED, {"key": param.key, "name": param.name, "value": value})

    def set_latest(self, name, value):
        """Sets a parameter like set(), but for sliders: the newest value wins.

        If a set is already being sent, the value waits in _pending, replacing any
        older value for the same parameter, and this returns straight away. The
        caller that is sending sends it next (see _drain). So a burst of slider
        moves becomes a few sets: the first, and the newest each time the amp answers.

        Bad names and values (ValueError) and not being connected (AmpDisconnected)
        are raised here, before anything waits. Errors while sending can't reach a
        caller that has already returned, so they're logged; a timeout also starts
        a reconnect. Don't call it from an on_change callback: it may send.
        """
        param = self._check(name, value)
        with self._pending_lock:
            self._pending[param.key] = (param, value)
            if self._draining:
                return
            self._draining = True
        self._drain()

    def _drain(self):
        """Sends what's in _pending, one set at a time, until it's empty (set_latest's sender).

        Takes the parameter that has waited longest first, so one busy slider can't
        hold up another. A value is taken out inside _pending_lock and sent outside
        it, so other callers can keep adding while the amp answers. _draining is
        only changed under the lock. After AmpDisconnected the rest is dropped,
        because nothing can be sent.
        """
        while True:
            with self._pending_lock:
                if not self._pending:
                    self._draining = False
                    return
                key = next(iter(self._pending))
                param, value = self._pending.pop(key)
            try:
                self._send(param, value)
            except AmpDisconnected:
                with self._pending_lock:
                    self._pending.clear()
                    self._draining = False
                return
            except AmpError as e:
                self._logger.warning(f"set_latest {param.name}: {e!r}")    # a timeout already reconnects

    def select_preset(self, n):
        """Loads preset n (an index into the amp's preset list) and returns its name.

        Waits for the preset's dump (up to amp.DUMP_TIMEOUT), then updates the
        state and sends PRESET_CHANGED. Nothing is saved on the amp. Don't call it
        from an on_change callback. Raises AmpDisconnected if not connected,
        AmpTimeout if no dump comes back (the state is then unchanged).
        """
        if self._amp is None:
            raise AmpDisconnected("not connected")
        if n in UNLOADABLE:
            raise ValueError(f"preset {n} can't be loaded on this amp")
        if not 0 <= n <= 127:
            raise ValueError(f"preset {n} is outside amp range")
        dump = self._amp.select_preset(n)
        name = dump.name()
        with self._threading_lock:
            self._state.preset_number = n
            self._state.preset_name = name
            self._state.params = read_values(dump)
            self._state.models = self._models(dump)
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

        Most events arrive on the reader thread, so keep callbacks quick and don't
        call set(), set_latest() or select_preset() from one: they wait for the amp.
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
                self._state.params = read_values(dump)
                self._state.models = self._models(dump)
            self._emit(EventType.PRESET_CHANGED, {"number": None, "name": name})
        else:
            self._logger.warning("Preset dump is incomplete")

    def _handle_lost(self, error):
        """Called once by the connection when the amp stops responding (reader thread).

        Ends DISCONNECTED, says why in the event and wakes the supervisor, if
        keep_connected() is running. Keeps the amp so the next start() or stop()
        can close it; it can't be closed here, on its own reader thread.
        """
        with self._threading_lock:
            self._state.connection = ConnectionState.DISCONNECTED
        self._emit(EventType.CONNECTION_CHANGED, {"state": ConnectionState.DISCONNECTED, "error": repr(error)})
        self._wake.set()

    def presets(self):
        """Every preset's name, as {index: name}, read from the handshake by start().

        index is the value select_preset() takes. Returns a copy, so changing it
        changes nothing here. Empty before the first start(); kept after stop(),
        and read again by the next start(). Safe from any thread.
        """
        with self._threading_lock:
            return dict(self._presets)

    def _reconnect_soon(self):
        """After an unanswered set: ends DISCONNECTED and wakes the supervisor to reconnect.

        Like _handle_lost, but for a connection that still reads fine and only
        ignores sets. Without keep_connected() nothing reconnects; call start().
        """
        with self._threading_lock:
            self._state.connection = ConnectionState.DISCONNECTED
        self._emit(EventType.CONNECTION_CHANGED, {"state": ConnectionState.DISCONNECTED, "error": "set timed out"})
        self._wake.set()      

    def save(self):
        """Saves the preset as it is now (every set included) into the loaded slot, and returns its name.

        Takes a fresh dump of the edit buffer, uploads its preset data to the slot
        select_preset() loaded, reads it back (a warning is logged if the values
        differ) and sends PRESET_SAVED. It overwrites that preset on the amp; it
        can't be undone. Don't call it from an on_change callback.
        Raises AmpDisconnected if not connected, ValueError if the slot isn't known
        (after the handshake or a knob move: select a preset first), AmpTimeout if
        the amp doesn't answer (no event is sent then).
        """
        amp = self._amp
        if amp is None:
            raise AmpDisconnected("not connected")
        with self._threading_lock:
            n = self._state.preset_number
        if n is None:
            raise ValueError("save: which slot is loaded isn't known; select a preset first")
        dump = amp.request_dump()
        amp.upload(n, preset_data(dump))
        dump_after = amp.request_dump()
        if read_values(dump_after) != read_values(dump):
            self._logger.warning("save: the preset read back differs from what was saved")
        self._emit(EventType.PRESET_SAVED, {"number": n, "name": dump.name()})
        return dump.name()