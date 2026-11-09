"""
messages.py

Handles the messages that are sent and received between the amp and the machine
"""

from enum import Enum
import struct

from silkline.protocol.packing import pack
from silkline.protocol.presets import entry_name

from .knob import POSITIONS
from .values import decode_value

BEGIN_LENGTH = 29
SET_VALUE_LENGTH = 37

FIRST_SEQUENCE = 0x0C
FLOAT_VALUE = 0x04
SWITCH_VALUE = 0x03

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


def _is_set_answer(msg):
    """The 29-byte channel-0 message the amp sends straight after a set (protocol.md section 8)."""
    return (
        len(msg) == 29
        and msg[:7] == HEADER
        and msg[7] == 0
        and msg[11] == 0x0B
        and msg[13] == 0x01
    )


def _is_upload_answer(msg):
    """The 29-byte channel-1 message the amp sends after the last piece of an upload."""
    return (
        len(msg) == 29
        and msg[:7] == HEADER
        and msg[7] == 1
        and msg[11] == 0x0B
        and msg[13] == 0x01
    )


class SetAnswer:
    """Collector for request(): complete once the amp has answered a set."""

    def __init__(self):
        self.msg = None

    def offer(self, msg):
        """Takes the first set answer (_is_set_answer). True if it took msg."""
        if self.msg is None and _is_set_answer(msg):
            self.msg = msg
            return True
        return False

    def complete(self):
        """True once the answer has arrived."""
        return self.msg is not None


class UploadAnswer:
    """Collector for request(): complete once the upload's answer arrives."""

    def __init__(self):
        self._done = False

    def offer(self, msg):
        """Takes the upload's answer (_is_upload_answer). True if it took msg."""
        if _is_upload_answer(msg):
            self._done = True
            return True
        return False

    def complete(self):
        """True once the answer has arrived."""
        return self._done


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

    # Preset-list entries from the handshake (protocol.md section 4, "Preset list")
    name = entry_name(msg)
    if name is not None:
        return (MessageKind.PRESET_INFO, name)

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


def build_set_message(sequence, block, sub, symbol, value_type, value):
    """Build the SysEx message that sets a parameter (protocol.md section 8).

    Its data is four little-endian numbers, packed like a dump: the block word
    (block | sub << 8), the parameter's symbol (Parameter.symbol, e.g. 0x324 for
    Volume), value_type (FLOAT_VALUE or SWITCH_VALUE) and value, its 4 bytes
    (values.encode_set_value or encode_switch), then 5 zeros. Packing carries every
    top bit, so symbols of 0x80 and more (EQ Hi Shelf Gain, 0x282) and whole floats
    go across. Raises ValueError for a sequence outside 0 to 127 or a value that
    isn't 4 bytes.
    """
    if not 0 <= sequence < 0x80:
        raise ValueError(f"Sequence must be between 0 and 127, got {sequence}")
    if len(value) != 4:
        raise ValueError(f"Incorrect value length, got {len(value)}")

    data = struct.pack("<III", block | sub << 8, symbol, value_type) + value + bytes(5)
    message = BYTE_HEADER + bytes([sequence, 0x00, 0x00, 0x0f]) + pack(data) + b"\xf7"
    if len(message) != SET_VALUE_LENGTH:
        raise ValueError(f"SET_VALUE_LENGTH mismatch: {len(message)} != {SET_VALUE_LENGTH}")
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
