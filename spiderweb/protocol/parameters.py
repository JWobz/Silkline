from dataclasses import dataclass


@dataclass(frozen=True)
class Parameter:
    name: str
    block: int
    sub: int
    id: int
    settable: bool = False

    @property
    def key(self):
        return (self.block, self.id, self.sub)


PARAMETERS = [
    Parameter("Drive", 0x2A, 0, 0x25, settable=True),
    Parameter("Drive (alt)", 0x2A, 0, 0x26, settable=True),
    Parameter("Tone (part)", 0x2A, 0, 0x24, settable=True),
    Parameter("Volume", 0x74, 3, 0x24, settable=True),
    Parameter("Reverb", 0x74, 3, 0x20, settable=True),
    Parameter("Reverb (mix)", 0x1F, 1, 0x7A, settable=True),
    Parameter("FX1", 0x74, 3, 0x48, settable=True),
    Parameter("FX2", 0x74, 3, 0x47, settable=True),
    Parameter("FX3", 0x74, 3, 0x46, settable=True),
    Parameter("FX Knob (FX1)", 0x74, 3, 0x1A, settable=True),
    Parameter("FX Knob (FX2)", 0x74, 3, 0x1C, settable=True),
    Parameter("FX Knob (FX3)", 0x74, 3, 0x1E, settable=True),
    Parameter("Tap (Hold)", 0x6C, 3, 0x72, settable=False),
]

KNOWN_PARAMETERS = {p.key: p.name for p in PARAMETERS}
BY_NAME = {p.name.lower(): p for p in PARAMETERS}