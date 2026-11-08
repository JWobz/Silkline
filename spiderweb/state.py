"""What AmpService knows and tells: AmpState, the Event it sends, and their kinds.

Plain data only; nothing here talks to the amp.
"""
from dataclasses import dataclass, field, replace
from enum import Enum


class ConnectionState(Enum):
    """Whether the service is talking to the amp."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class EventType(Enum):
    """What an Event is about. The data each one carries:

    CONNECTION_CHANGED  {"state": ConnectionState}, plus "error" (a repr) when the amp was lost
    PRESET_CHANGED      {"number": select value, or None after a knob move, "name": str}
    PARAMETER_CHANGED   {"key": (block, id, namespace), "name": str or None if unknown, "value": float, or 0 / 1 for a switch}
    KNOB_MOVED          {"position": 0 to 15, once the preset knob has settled}
    TAP                 {"bpm": float}
    SAVE_PRESSED        {}
    PRESET_SAVED        {"number": slot, "name": str}   after save()
    """

    CONNECTION_CHANGED = "connection_changed"
    PRESET_CHANGED = "preset_changed"
    PRESET_SAVED = "preset_saved"
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
    (block, id, namespace) to its last value: a float, or 0 / 1 for a switch.
    models maps each stage ("amp", "cab", "stomp"...) to its model,
    {"number": n, "id": str or None, "name": str or None}; both are replaced
    from every dump.
    """

    connection: ConnectionState = ConnectionState.DISCONNECTED
    preset_number: int | None = None
    preset_name: str | None = None
    knob_position: int | None = None
    params: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)
    bpm: float | None = None

    def snapshot(self):
        """Returns a copy, params included, that is safe to keep and change."""
        return replace(self, params=self.params.copy(), models=self.models.copy())


@dataclass(frozen=True)
class Event:
    """Something that happened, sent to on_change() callbacks. See EventType for data."""

    event_type: EventType
    data: dict
