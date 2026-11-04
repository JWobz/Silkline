import threading
from dataclasses import dataclass, field, replace
from enum import Enum

from spiderweb.logger import Logger
from spiderweb.protocol.knob import settle_position
from spiderweb.protocol.messages import MessageKind, classify
from spiderweb.protocol.parameters import KNOWN_PARAMETERS


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"

class EventType(Enum):
    CONNECTION_CHANGED = "connection_changed"
    PRESET_CHANGED = "preset_changed"
    PARAMETER_CHANGED = "parameter_changed"
    KNOB_MOVED = "knob_moved"
    TAP = "tap"
    SAVE_PRESSED = "save_pressed"

@dataclass
class AmpState:
    connection: ConnectionState = ConnectionState.DISCONNECTED
    preset_number: int | None = None
    preset_name: str | None = None
    knob_position: int | None = None
    params: dict = field(default_factory=dict)
    bpm: float | None = None
    
    def snapshot(self):
        """Return a snapshot of the current amp state."""
        return replace(self, params=self.params.copy()) 

@dataclass(frozen=True)
class Event:
    event_type: EventType
    data: dict


class AmpError(Exception):
    """Custom exception for amp-related errors."""

class AmpDisconnected(AmpError):
    """Exception raised when the amp is disconnected."""

class AmpTimeout(AmpError):
    """Exception raised when a timeout occurs while communicating with the amp."""


class AmpService:
    """Service class to manage amp state and events."""
    
    def __init__(self): 
        self.logger = Logger(prefix="AmpService")
        self._state = AmpState()
        self._threading_lock = threading.Lock()
        self.callbacks = []
        self.knob_candidates = []
        

    def _emit(self, event_type, data):
        event = Event(event_type, data)
        for callback in self.callbacks:
            try: 
                callback(event)
            except Exception as e:
                self.logger.error(f"Callback failed: {e!r}")

    def state(self):
        with self._threading_lock:
            return self._state.snapshot()

    def on_change(self, callback):
        self.callbacks.append(callback)

    def handle_message(self, msg):
        classified_message = classify(msg)
        events = []

        with self._threading_lock:
            match classified_message[0]:
                case MessageKind.PARAM:
                    if classified_message[1] == (0x2A, 0x02, 0):
                        return
                    
                    param_id, param_value = classified_message[1:]
                    if param_id not in self._state.params or abs(self._state.params[param_id] - param_value) >= 0.02:
                        events.append((EventType.PARAMETER_CHANGED, {"key": param_id, "name": KNOWN_PARAMETERS.get(param_id), "value": param_value}))
                        self._state.params[param_id] = param_value
                case MessageKind.PRESET_CHANGE:
                    preset_value = classified_message[1]
                    self.knob_candidates.append(preset_value)
                case MessageKind.STATUS:
                    if not self.knob_candidates:
                        return
                    knob_position = settle_position(self.knob_candidates, self._state.knob_position)
                    self._state.knob_position = knob_position
                    self.knob_candidates = []
                    events.append((EventType.KNOB_MOVED, {"position": knob_position}))
                case MessageKind.TAP:
                    bpm = classified_message[1]
                    self._state.bpm = bpm
                    events.append((EventType.TAP, {"bpm": bpm}))
                case MessageKind.SAVE:
                    events.append((EventType.SAVE_PRESSED, {}))
                case MessageKind.PRESET_INFO:
                    param_name, _ = classified_message[1:]
                    if self._state.preset_name != param_name:
                        self._state.preset_name = param_name
                        events.append((EventType.PRESET_CHANGED, {"name": param_name}))
                case _:
                    return

        for event_type, event_data in events:
            self._emit(event_type, event_data)

            
