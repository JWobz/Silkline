"""
parameters.py

The parameters the API can set and read, by name (protocol.md section 8).

PARAMETERS lists them; BY_NAME finds one by its lower-case name and
KNOWN_PARAMETERS names a wire key. DUMP_RECORDS says which dump record holds
each one's value (protocol.md section 3).
"""
from dataclasses import dataclass

from silkline.protocol.messages import FLOAT_VALUE, SWITCH_VALUE
from silkline.protocol.values import encode_set_value, encode_switch


@dataclass(frozen=True)
class Parameter:
    """A parameter the amp knows: where it is and how to address it.

    block and sub name the block (msg[13], msg[14] of a set), id and namespace
    the parameter inside it (msg[17], msg[18]). The namespace is often the same
    as sub but not always. key (block, id, namespace) is how values are stored in
    AmpState.params; the amp's reports carry the same three.

    kind is "float" (a value from low to high, 0 to 1 for most) or "switch" (an
    on/off: 0 or 1). record is the dump record holding its value, in its block (the
    "...State" symbol of the same name, protocol.md section 8), or None if no dump has
    it; DUMP_RECORDS is built from it. settable is False for parameters that are only
    reported.
    """
    name: str
    block: int
    sub: int
    id: int
    namespace: int
    kind: str = "float"     # "float" or "switch"
    record: int | None = None
    low: float = 0.0
    high: float = 1.0
    settable: bool = False
    
    @property
    def key(self):
        """(block, id, namespace): how the amp's reports and AmpState.params name it."""
        return (self.block, self.id, self.namespace)

    @property
    def symbol(self):
        """The parameter's symbol, namespace << 8 | id: what a set message names it by."""
        return self.namespace << 8 | self.id
    
    def encode(self, value):
        """Checks a value for this parameter and returns (value bytes, value_type) for a set.

        A switch takes 0 or 1 (or False / True) and is sent as the number 1 / 0 with
        SWITCH_VALUE (3, as the app sends); a float takes low to high and is sent
        whole with FLOAT_VALUE (4). Raises ValueError for anything else.
        """
        if self.kind == "switch":
            if value not in (0, 1):
                raise ValueError(f"param switch value not 0/1, got {value} ")
            value = encode_switch(value)
            value_type = SWITCH_VALUE
        else:
            if not (self.low <= value <= self.high):
                raise ValueError(f"param float value out of range, got {value} ")
            value = encode_set_value(value)
            value_type = FLOAT_VALUE
        return (value, value_type)

PARAMETERS = [
    # Amp (2A:0). A model has Gain or Drive, not both (see _resolve).
    Parameter("Gain",     0x2A, 0, 0x25, 0, record=0x1F, settable=True),
    Parameter("Drive",    0x2A, 0, 0x26, 0, record=0x33, settable=True),
    Parameter("Bass",     0x2A, 0, 0x21, 0, record=0x1C, settable=True),
    Parameter("Mid",      0x2A, 0, 0x23, 0, record=0x1D, settable=True),
    Parameter("Treble",   0x2A, 0, 0x24, 0, record=0x1E, settable=True),
    Parameter("Presence", 0x2A, 0, 0x27, 0, record=0x20, settable=True),
    # Panel (74:3)
    Parameter("Volume",       0x74, 3, 0x24, 3, record=0x3C, settable=True),
    Parameter("Reverb",       0x74, 3, 0x20, 3, record=0x32, settable=True),
    Parameter("Stomp Knob",   0x74, 3, 0x1A, 3, record=0x26, settable=True),
    Parameter("Mod Knob",     0x74, 3, 0x1C, 3, record=0x2A, settable=True),
    Parameter("Delay Knob",   0x74, 3, 0x1E, 3, record=0x2E, settable=True),
    # Stage on/off (74:3)
    Parameter("Gate On",   0x74, 3, 0x4D, 3, kind="switch", record=0x38, settable=True),
    Parameter("Wah On",    0x74, 3, 0x51, 3, kind="switch", record=0x3B, settable=True),
    Parameter("Stomp On",  0x74, 3, 0x48, 3, kind="switch", record=0x28, settable=True),
    Parameter("Mod On",    0x74, 3, 0x47, 3, kind="switch", record=0x2C, settable=True),
    Parameter("Comp On",   0x74, 3, 0x4A, 3, kind="switch", record=0x3D, settable=True),
    Parameter("EQ On",     0x74, 3, 0x4B, 3, kind="switch", record=0x3E, settable=True),
    Parameter("Vol On",    0x74, 3, 0x49, 3, kind="switch", record=0x3A, settable=True),
    Parameter("Delay On",  0x74, 3, 0x46, 3, kind="switch", record=0x30, settable=True),
    Parameter("Reverb On", 0x74, 3, 0x50, 3, kind="switch", record=0x34, settable=True),
    # Noise gate (5E:2)
    Parameter("Gate Threshold", 0x5E, 2, 0x60, 2, record=0x5F, low=14, high=77, settable=True),
    Parameter("Gate Decay",     0x5E, 2, 0x0A, 0, record=0x21, settable=True),
    # Volume pedal (04:3)
    Parameter("Vol Min", 0x04, 3, 0x09, 3, record=0x06, settable=True),
    Parameter("Vol Max", 0x04, 3, 0x0A, 3, record=0x07, settable=True),
    # Compressor (23:3)
    Parameter("Comp Threshold", 0x23, 3, 0x63, 2, record=0x62, settable=True),
    Parameter("Comp Gain",      0x23, 3, 0x25, 0, record=0x1F, settable=True),
    # EQ (25:3)
    Parameter("EQ Low Freq",       0x25, 3, 0x07, 0, record=0x6A, settable=True),
    Parameter("EQ Low Gain",       0x25, 3, 0x73, 2, record=0x6B, settable=True),
    Parameter("EQ Low-Mid Freq",   0x25, 3, 0x76, 2, record=0x6C, settable=True),
    Parameter("EQ Low-Mid Gain",   0x25, 3, 0x79, 2, record=0x6D, settable=True),
    Parameter("EQ High-Mid Freq",  0x25, 3, 0x7B, 2, record=0x6E, settable=True),
    Parameter("EQ High-Mid Gain",  0x25, 3, 0x25, 0, record=0x1F, settable=True),
    Parameter("EQ High Freq",      0x25, 3, 0x7F, 2, record=0x6F, settable=True),
    Parameter("EQ High Gain",      0x25, 3, 0x82, 2, record=0x70, settable=True),
    # Reverb (1F:3), as seen on a spring model
    Parameter("Reverb Time", 0x1F, 3, 0x0A, 0, record=0x21, settable=True),
    Parameter("Reverb Tone", 0x1F, 3, 0x46, 2, record=0x45, settable=True),
    Parameter("Reverb Mix",  0x1F, 3, 0x7A, 1, record=0x75, settable=True),
    # Only reported, never set, and not in the dump
    Parameter("Tap (Hold)", 0x6C, 3, 0x72, 3),
]

KNOWN_PARAMETERS = {p.key: p.name for p in PARAMETERS}
BY_NAME = {p.name.lower(): p for p in PARAMETERS}
DUMP_RECORDS = {(p.block, p.sub, p.record): p.key for p in PARAMETERS if p.record is not None}