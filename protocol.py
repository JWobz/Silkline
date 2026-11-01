from dataclasses import dataclass
from enum import Enum
import struct

BYTE_HEADER = bytes.fromhex("F0 00 01 0C 22 05 4D 00")
BEGIN_LENGTH = 29
SET_VALUE_LENGTH = 37


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


PARAMETERS = {
    Parameter("Drive", 0x2A, 0, 0x25, settable=True),
    Parameter("Tone (part)", 0x2A, 0, 0x24, settable=True),
    Parameter("Volume", 0x74, 3, 0x24, settable=True),
    Parameter("Reverb", 0x74, 3, 0x20, settable=True),
    Parameter("FX1", 0x74, 3, 0x48, settable=True),
    Parameter("FX2", 0x74, 3, 0x47, settable=True),
    Parameter("FX3", 0x74, 3, 0x46, settable=True),
    Parameter("FX Knob (FX1)", 0x74, 3, 0x1A, settable=True),
    Parameter("FX Knob (FX2)", 0x74, 3, 0x1C, settable=True),
    Parameter("FX Knob (FX3)", 0x74, 3, 0x1E, settable=True),
    Parameter("Tap (Hold)", 0x6C, 3, 0x72, settable=False),
}   

KNOWN_PARAMETERS = {p.key: p.name for p in PARAMETERS}   # watch.py keeps working
BY_NAME = {p.name.lower(): p for p in PARAMETERS}

class MessageKind(Enum):
    """ Enum for the different kinds of messages that can be received from the amp. """
    PARAM = "param"
    PRESET_INFO = "preset_info"
    UNKNOWN = "unknown"
    TAP = "tap"
    SAVE = "save"
    HEARTBEAT = "heartbeat"
    STATUS = "status"

def encode_value(value):
    """ Turn a float into a five byte value. """
    if not (0 <= value <= 1):
        raise ValueError(f"Value must be between 0 and 1, got {value}")
    
    # Convert the float to a 4-byte representation
    float_bytes = struct.pack('<f', value)
    
    # Extract the third and fourth bytes
    third = float_bytes[2]
    top = float_bytes[3]
    
    # Determine the flag based on the third byte
    flag = 0x20 if (third & 0x80) else 0x00
    third = third & 0x7F
    
    # Create the five-byte sequence
    return bytes([0x00, flag, 0x00, third, top])

def encode_set_value(value):
    """ Turn a float into the five bytes the amp expects in a set message. """
    if not (0 <= value <= 1):
        raise ValueError(f"Value must be between 0 and 1, got {value}")
    float_bytes = struct.pack('<f', value)
    third, top = float_bytes[2], float_bytes[3]
    flag = 0x40 if (third & 0x80) else 0x00
    return bytes([0x00, 0x00, flag, third & 0x7F, top])

def decode_value(value):
    """ Turn the five byte value into a float. """
    flag = value[1]
    third = value[3]
    top = value[4]

    if (flag & 0x20):
        third |= 0x80
        
    # Create the four-byte sequence for struct.unpack
    float_bytes = b'\x00\x00' + bytes([third]) + bytes([top])
    return struct.unpack('<f', float_bytes)[0]

def decode_set_value(raw5):
    """ Turn the five bytes of a set message into a float. """
    b2 = raw5[3] | (0x80 if raw5[2] & 0x40 else 0)
    return struct.unpack('<f', bytes([0, 0, b2, raw5[4]]))[0]


def build_begin_message(sequence):
    """Build the first SysEx message in a parameter-set operation."""
    if not 0 <= sequence < 0x80:
        raise ValueError(f"Sequence must be between 0 and 127, got {sequence}")

    message = (
        BYTE_HEADER
        + bytes([sequence])
        + bytes.fromhex("00 00 07 00 0A 00 00 00 10")
        + bytes(10)
        + bytes([0xF7])
    )
    if len(message) != BEGIN_LENGTH:
        raise ValueError(f"BEGIN_LENGTH mismatch: {len(message)} != {BEGIN_LENGTH}")
    return message


def build_set_message(sequence, block, sub, param_id, raw5, unknown=1):
    """Build a SysEx message that sets a parameter to a raw five-byte value."""
    if not 0 <= sequence < 0x80:
        raise ValueError(f"Sequence must be between 0 and 127, got {sequence}")
    if len(raw5) != 5:
        raise ValueError(f"raw5 must contain exactly 5 bytes, got {len(raw5)}")

    message = BYTE_HEADER + bytes([
        sequence,               # msg[8] sequence number
        0x00, 0x00,              # msg[9], msg[10]
        0x0F,                    # msg[11] message type: set
        0x00,                    # msg[12]
        block,                   # msg[13] block
        sub,                     # msg[14] sub
        0x00, 0x00,              # msg[15], msg[16]
        param_id,                # msg[17]
        sub,                     # msg[18] repeated sub
        0x00,                    # msg[19]
        unknown,                 # msg[20]
        0x00,                    # msg[21]
        0x04,                    # msg[22]
        0x00, 0x00, 0x00,        # msg[23] to msg[25]
    ]) + raw5 + bytes(5) + bytes([0xF7])

    if len(message) != SET_VALUE_LENGTH:
        raise ValueError(f"SET_VALUE_LENGTH mismatch: {len(message)} != {SET_VALUE_LENGTH}")
    return message


def classify(msg):
    """ Classify a message from the amp into a known type, if possible. Returns a tuple of (kind, *args) where kind is a MessageKind and args are additional data depending on the kind. """
    length = len(msg)
    shape = (length, msg[11], msg[13]) if length >= 14 else (length, None, None)

    # Tap message
    if length == 37 and msg[11] == 0x0f and msg[13] == 5:
        bpm = decode_value(msg[26:31]) * 2
        return (MessageKind.TAP, bpm)

    # Length 45 messages (Params, Status, Save, Heartbeat)
    if (length == 45 and msg[11] == 0x07):
        if msg[13] == 0x04:
            param_id = (msg[22], msg[26], msg[27])
            value = decode_value(msg[35:40])
            return (MessageKind.PARAM, param_id, value)
        
        if msg[13] == 0x03:
            if msg[26] == 0x7F:
                return (MessageKind.STATUS,)
            elif msg[35] == 1:
                return (MessageKind.SAVE,)
            return (MessageKind.HEARTBEAT, msg[26])

    # Preset info messages
    if 49 < length < 100 and msg[13] == 1:
        name = bytes(b for b in msg[49:-1] if 32 <= b < 127).decode()
        return (MessageKind.PRESET_INFO, name, msg[40])

    # Default fallback if nothing matches
    return (MessageKind.UNKNOWN, shape)
