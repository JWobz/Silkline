"""
upload.py

Uploads: sending data to the amp (a save, or a type change in v1.1).
protocol.md section 8, "Uploads".
"""

from spiderweb.protocol.packing import pack

HEADER = bytes.fromhex("f000010c22054d")
EDIT_BUFFER = 0xFFFFFFFF  # "slot" for the live preset (type changes, v1.1)
_CHANNEL = 0x01  # uploads go on channel 1, like dumps
_PIECE = 210  # data bytes per message



def _upload_message(counter, index, data):
    """One channel-1 message: counter, index, length - 1 in two halves, packed data, F7."""
    n = len(data) - 1
    return (
        HEADER
        + bytes([_CHANNEL, counter, index, n >> 4, n & 0x0F])
        + pack(data)
        + b"\xf7"
    )


def build_upload(counter, slot, data):
    """All the messages of an upload: a header, then the data in 210-byte pieces.

    The header's data is four little-endian 32-bit numbers: 12, len + 8, slot, len.
    The pieces all use counter + 1, numbered 0, 1, 2... slot is a preset number,
    or EDIT_BUFFER.
    """
    header = b"".join(
        n.to_bytes(4, "little") for n in (12, len(data) + 8, slot, len(data))
    )
    messages = [_upload_message(counter, 0, header)]
    for i in range(0, len(data), _PIECE):
        messages.append(
            _upload_message((counter + 1) % 128, i // _PIECE, data[i : i + _PIECE])
        )
    return messages
