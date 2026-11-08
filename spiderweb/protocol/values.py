"""The five value bytes of sets and reports (protocol.md sections 7 and 8).

A float is sent as its top 16 bits, split so no byte is above 0x7F; an on/off
as 01 / 00. Reports put the same top bits in a slightly different place.
"""
import struct


def encode_set_value(value):
    """Turn a float into the five bytes the amp expects in a set message.

    Only the float's top 16 bits are sent. Values above 1 are fine (the gate threshold
    is sent as 14 to 77); negative values are refused, because the sign bit would
    land in the top byte, above 0x7F.
    """
    if value < 0:
        raise ValueError(f"Value must not be negative, got {value}")
    float_bytes = struct.pack("<f", value)
    third, top = float_bytes[2], float_bytes[3]
    flag = 0x40 if (third & 0x80) else 0x00
    return bytes([0x00, 0x00, flag, third & 0x7F, top])


def encode_switch(on):
    """The five value bytes of an on/off set: 01 for on, 00 for off, then zeros."""
    return bytes([1 if on else 0, 0, 0, 0, 0])


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
