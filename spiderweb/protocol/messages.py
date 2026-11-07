"""
 messages.py
 
 Handles the messages that is sent and recieved from amp and machine
 
 """

from enum import Enum

from spiderweb.protocol.presets import entry_name

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

def is_set_answer(msg):
    """The 29-byte channel-0 message the amp sends straight after a set (protocol.md section 8)."""
    return len(msg) == 29 and msg[:7] == HEADER and msg[7] == 0 and msg[11] == 0x0B and msg[13] == 0x01

def is_upload_answer(msg):
    """The 29-byte channel-1 message the amp sends after the last piece of an upload."""
    return len(msg) == 29 and msg[:7] == HEADER and msg[7] == 1 and msg[11] == 0x0B and msg[13] == 0x01

class SetAnswer():
    """Collector for request(): complete once the amp has answered a set."""
    def __init__(self):
        self.msg = None

    def offer(self, msg):
        if self.msg is None and is_set_answer(msg):
            self.msg = msg
            return True
        return False

    def complete(self):
        return self.msg is not None
        
class UploadAnswer():
    """Collector for request(): complete once the upload's answer arrives."""
    def __init__(self):
        self._done = False

    def offer(self, msg):
        if is_upload_answer(msg):
            self._done = True
            return True
        return False
    def complete(self):
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


def build_set_message(sequence, block, sub, param_id, raw5, namespace, value_type=FLOAT_VALUE, unknown=1):
    """Build a SysEx message that sets a parameter to a raw five-byte value.

    block and sub go in msg[13] and msg[14], param_id and namespace in msg[17]
    and msg[18]. The namespace is often the same as sub but not always (Reverb
    mix is block 1F sub 3, id 7A in namespace 1). unknown goes in msg[20]; the
    app cycles it 0 to 3 and the amp accepts 1 (protocol.md section 8).
    """
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
                param_id,  # msg[17] id
                namespace,  # msg[18] namespace
                0x00,  # msg[19]
                unknown,  # msg[20] unknown
                0x00,  # msg[21]
                value_type,  # msg[22]
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
