from dataclasses import dataclass

from spiderweb.protocol.messages import FLOAT_VALUE, SWITCH_VALUE
from spiderweb.protocol.values import encode_set_value, encode_switch


@dataclass(frozen=True)
class Parameter:
    """A parameter the amp knows: where it is and how to address it.

    block and sub name the block (msg[13], msg[14] of a set), id and namespace
    the parameter inside it (msg[17], msg[18]). The namespace is often the same
    as sub but not always. key (block, id, namespace) is how values are stored in
    AmpState.params; the amp's reports carry the same three.

    kind is "float" (a value from low to high, 0 to 1 for most) or "switch" (an
    on/off: 0 or 1). settable is False for parameters that are only reported.
    """
    name: str
    block: int
    sub: int
    id: int
    namespace: int
    kind: str = "float"     # "float" or "switch"
    low: float = 0.0
    high: float = 1.0
    settable: bool = False

    @property
    def key(self):
        return (self.block, self.id, self.namespace)

    def encode(self, value):
        """Checks a value for this parameter and returns (raw5, value_type) for a set.

        A switch takes 0 or 1 (or False / True) and is sent as 01/00 with value type
        SWITCH_VALUE (msg[22] = 03, as the app sends); a float takes low to high and
        is sent with FLOAT_VALUE (04). Raises ValueError for anything else.
        """
        if self.kind == "switch":
            if value not in (0, 1):
                raise ValueError(f"param switch value not 0/1, got {value} ")
            raw5 = encode_switch(value)
            value_type = SWITCH_VALUE
        else:
            if not (self.low <= value <= self.high):
                raise ValueError(f"param float value out of range, got {value} ")
            raw5 = encode_set_value(value)
            value_type = FLOAT_VALUE
        return (raw5, value_type)


PARAMETERS = [
    # Amp (2A:0). A model has Gain or Drive, not both (see _resolve).
    Parameter("Gain",     0x2A, 0, 0x25, 0, settable=True),
    Parameter("Drive",    0x2A, 0, 0x26, 0, settable=True),
    Parameter("Bass",     0x2A, 0, 0x21, 0, settable=True),
    Parameter("Mid",      0x2A, 0, 0x23, 0, settable=True),
    Parameter("Treble",   0x2A, 0, 0x24, 0, settable=True),
    Parameter("Presence", 0x2A, 0, 0x27, 0, settable=True),
    # Panel (74:3)
    Parameter("Volume",       0x74, 3, 0x24, 3, settable=True),
    Parameter("Reverb",       0x74, 3, 0x20, 3, settable=True),
    Parameter("Stomp Knob",   0x74, 3, 0x1A, 3, settable=True),
    Parameter("Mod Knob",     0x74, 3, 0x1C, 3, settable=True),
    Parameter("Delay Knob",   0x74, 3, 0x1E, 3, settable=True),
    # Stage on/off (74:3)
    Parameter("Gate On",   0x74, 3, 0x4D, 3, kind="switch", settable=True),
    Parameter("Wah On",    0x74, 3, 0x51, 3, kind="switch", settable=True),
    Parameter("Stomp On",  0x74, 3, 0x48, 3, kind="switch", settable=True),
    Parameter("Mod On",    0x74, 3, 0x47, 3, kind="switch", settable=True),
    Parameter("Comp On",   0x74, 3, 0x4A, 3, kind="switch", settable=True),
    Parameter("EQ On",     0x74, 3, 0x4B, 3, kind="switch", settable=True),
    Parameter("Vol On",    0x74, 3, 0x49, 3, kind="switch", settable=True),
    Parameter("Delay On",  0x74, 3, 0x46, 3, kind="switch", settable=True),
    Parameter("Reverb On", 0x74, 3, 0x50, 3, kind="switch", settable=True),
    # Noise gate (5E:2)
    Parameter("Gate Threshold", 0x5E, 2, 0x60, 2, low=14, high=77, settable=True),
    Parameter("Gate Decay",     0x5E, 2, 0x0A, 0, settable=True),
    # Volume pedal (04:3)
    Parameter("Vol Min", 0x04, 3, 0x09, 3, settable=True),
    Parameter("Vol Max", 0x04, 3, 0x0A, 3, settable=True),
    # Compressor (23:3)
    Parameter("Comp Threshold", 0x23, 3, 0x63, 2, settable=True),
    Parameter("Comp Gain",      0x23, 3, 0x25, 0, settable=True),
    # EQ (25:3)
    Parameter("EQ Low Freq",       0x25, 3, 0x07, 0, settable=True),
    Parameter("EQ Low Gain",       0x25, 3, 0x73, 2, settable=True),
    Parameter("EQ Low-Mid Freq",   0x25, 3, 0x76, 2, settable=True),
    Parameter("EQ Low-Mid Gain",   0x25, 3, 0x79, 2, settable=True),
    Parameter("EQ High-Mid Freq",  0x25, 3, 0x7B, 2, settable=True),
    Parameter("EQ High-Mid Gain",  0x25, 3, 0x25, 0, settable=True),
    Parameter("EQ High Freq",      0x25, 3, 0x7F, 2, settable=True),
    Parameter("EQ High Gain",      0x25, 3, 0x02, 2, settable=True),
    # Reverb (1F:3), as seen on a spring model
    Parameter("Reverb Time", 0x1F, 3, 0x0A, 0, settable=True),
    Parameter("Reverb Tone", 0x1F, 3, 0x46, 2, settable=True),
    Parameter("Reverb Mix",  0x1F, 3, 0x7A, 1, settable=True),
    Parameter("Tap (Hold)", 0x6C, 3, 0x72, 3),
]

KNOWN_PARAMETERS = {p.key: p.name for p in PARAMETERS}
BY_NAME = {p.name.lower(): p for p in PARAMETERS}

# Dump record (block, sub, record id) -> wire key (block, id, sub). protocol.md section 3.
DUMP_RECORDS = {
    (0x74, 3, 0x26): (0x74, 0x1A, 3),  # Stomp
    (0x74, 3, 0x28): (0x74, 0x48, 3),  # Stomp on
    (0x74, 3, 0x2A): (0x74, 0x1C, 3),  # Mod
    (0x74, 3, 0x2C): (0x74, 0x47, 3),  # Mod on
    (0x74, 3, 0x2E): (0x74, 0x1E, 3),  # Delay
    (0x74, 3, 0x30): (0x74, 0x46, 3),  # Delay on
    (0x74, 3, 0x32): (0x74, 0x20, 3),  # Reverb
    (0x74, 3, 0x3C): (0x74, 0x24, 3),  # Volume
    (0x2A, 0, 0x1C): (0x2A, 0x21, 0),  # Bass
    (0x2A, 0, 0x1D): (0x2A, 0x23, 0),  # Mid
    (0x74, 3, 0x3D): (0x74, 0x4A, 3),  # Comp
    (0x2A, 0, 0x1E): (0x2A, 0x24, 0),  # Treble
    (0x2A, 0, 0x1F): (0x2A, 0x25, 0),  # Gain
    (0x2A, 0, 0x33): (0x2A, 0x26, 0),  # Drive
    (0x2A, 0, 0x20): (0x2A, 0x27, 0),  # Presence
}