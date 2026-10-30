from enum import Enum
import struct

class MessageKind(Enum):
    """ Enum for the different kinds of messages that can be received from the amp. """
    PARAM = "param"
    PRESET_INFO = "preset_info"
    UNKNOWN = "unknown"
    TAP = "tap"
    SAVE = "save"
    HEARTBEAT = "heartbeat"
    STATUS = "status"

KNOWN_PARAMETERS = {
    (0x6c, 0x72, 3): "Tap (Hold)",

    (0x74, 0x1a, 3): "FX Knob (FX1)", 
    (0x74, 0x1c, 3): "FX Knob (FX2)", 
    (0x74, 0x1e, 3): "FX Knob (FX3)",

    (0x2a, 0x25, 0): "Drive",
    (0x2a, 0x24, 0): "Tone (part)",
    (0x74, 0x24, 3): "Volume",
    (0x74, 0x20, 3): "Reverb",

    (0x74, 0x48, 3): "FX1",
    (0x74, 0x47, 3): "FX2",
    (0x74, 0x46, 3): "FX3",
}

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
