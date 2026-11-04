from enum import Enum

from .knob import POSITIONS
from .values import decode_value

BEGIN_LENGTH = 29
SET_VALUE_LENGTH = 37

HEADER = bytes.fromhex("f000010c22054d")
BYTE_HEADER = HEADER + bytes([0x00])

DUMP_REQUEST = bytes.fromhex(
    "f000010c22054d010200000b000b0000000400003c007f7f7f7f0000f7"
)


class MessageKind(Enum):
    """Enum for the different kinds of messages that can be received from the amp."""

    PARAM = "param"
    PRESET_INFO = "preset_info"
    UNKNOWN = "unknown"
    TAP = "tap"
    SAVE = "save"
    PRESET_CHANGE = "preset_change"
    STATUS = "status"


def classify(msg):
    """Classify a message from the amp into a known type, if possible. Returns a tuple of (kind, *args) where kind is a MessageKind and args are additional data depending on the kind."""
    length = len(msg)
    shape = (length, msg[11], msg[13]) if length >= 14 else (length, None, None)

    # Tap message
    if length == 37 and msg[11] == 0x0F and msg[13] == 5:
        bpm = decode_value(msg[26:31]) * 2
        return (MessageKind.TAP, bpm)

    # length 45 messages with msg[11] == 0x07 are parameter messages, save messages, or preset change messages
    if length == 45 and msg[11] == 0x07:
        if msg[13] == 0x04:
            param_id = (msg[22], msg[26], msg[27])
            value = decode_value(msg[35:40])
            return (MessageKind.PARAM, param_id, value)

        if msg[13] == 0x03:
            if msg[26] == 0x7F:
                return (MessageKind.STATUS,)
            elif msg[35] == 1:
                return (MessageKind.SAVE,)
            else:
                return (MessageKind.PRESET_CHANGE, (msg[26] - 8) % POSITIONS)

    # Preset info messages
    if 49 < length < 100 and msg[13] == 1:
        name = bytes(b for b in msg[49:-1] if 32 <= b < 127).decode()
        return (MessageKind.PRESET_INFO, name, msg[40])

    # Default fallback if nothing matches
    return (MessageKind.UNKNOWN, shape)


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

    message = (
        BYTE_HEADER
        + bytes(
            [
                sequence,  # msg[8] sequence number
                0x00,
                0x00,  # msg[9], msg[10]
                0x0F,  # msg[11] message type: set
                0x00,  # msg[12]
                block,  # msg[13] block
                sub,  # msg[14] sub
                0x00,
                0x00,  # msg[15], msg[16]
                param_id,  # msg[17]
                sub,  # msg[18] repeated sub
                0x00,  # msg[19]
                unknown,  # msg[20]
                0x00,  # msg[21]
                0x04,  # msg[22]
                0x00,
                0x00,
                0x00,  # msg[23] to msg[25]
            ]
        )
        + raw5
        + bytes(5)
        + bytes([0xF7])
    )

    if len(message) != SET_VALUE_LENGTH:
        raise ValueError(
            f"SET_VALUE_LENGTH mismatch: {len(message)} != {SET_VALUE_LENGTH}"
        )
    return message


def select_message(value):
    """The 29-byte preset-select message from the app's captures, with `value` at msg[22]."""
    if not 0 <= value <= 0x7F:
        raise ValueError(f"value must be 0 to 127, got {value}")
    body = (
        bytes.fromhex("01 02 00 00 0b 00 0d 00 00 00 04 00 00 00 00")
        + bytes([value])
        + bytes(5)
    )
    message = HEADER + body + bytes([0xF7])
    assert len(message) == 29 and message[22] == value
    return message
