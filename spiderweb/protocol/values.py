import struct


def encode_set_value(value):
    """Turn a float into the five bytes the amp expects in a set message."""
    if not (0 <= value <= 1):
        raise ValueError(f"Value must be between 0 and 1, got {value}")
    float_bytes = struct.pack("<f", value)
    third, top = float_bytes[2], float_bytes[3]
    flag = 0x40 if (third & 0x80) else 0x00
    return bytes([0x00, 0x00, flag, third & 0x7F, top])


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