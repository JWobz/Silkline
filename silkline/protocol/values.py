"""
values.py

The five value bytes of sets and reports (protocol.md sections 7 and 8).

A float is sent as its top 16 bits, split so no byte is above 0x7F; an on/off
as 01 / 00. Reports put the same top bits in a slightly different place.
"""
import struct


def encode_set_value(value):
    """A float as the 4 value bytes of a set message (little-endian; packed later).

    The whole float is sent, and any value works: build_set_message packs the top
    bits, the sign bit included.
    """
    return struct.pack("<f", value)


def encode_switch(on):
    """The 4 value bytes of an on/off set: the number 1 for on, 0 for off."""
    return struct.pack("<I", 1 if on else 0)


def decode_value(value):
    """Turn the five byte value into a float."""
    flag = value[1]
    third = value[3]
    top = value[4]

    if flag & 0x20:
        third |= 0x80

    # Create the four-byte sequence for struct.unpack
    float_bytes = b"\x00\x00" + bytes([third]) + bytes([top])
    return struct.unpack("<f", float_bytes)[0]


def decode_set_value(raw5):
    """Turn the five bytes of a set message into a float."""
    b2 = raw5[3] | (0x80 if raw5[2] & 0x40 else 0)
    return struct.unpack("<f", bytes([0, 0, b2, raw5[4]]))[0]
