
DUMP_CHUNK_LENGTH = 309
DUMP_CHUNK_COUNT = 5

LAST_CHUNK_INDEX = 5  # The last chunk of a dump is usually index 5, but a short preset can end at index 4
NAME_LENGTH_AT = 56  # in dump chunk 0: name length + 1
NAME_START = 61  # in dump chunk 0: first character of the name
PAYLOAD_START = 12  # 7-bit packing groups of 8 bytes start here

def name_from_dump(chunk0):
    """Reads the preset name from the first dump chunk.

    The payload is 7-bit packed in groups of 8 bytes starting at msg[12]: the first
    byte of each group holds high bits, so it is skipped when collecting characters.
    """
    if len(chunk0) != DUMP_CHUNK_LENGTH:
        return None
    count = chunk0[NAME_LENGTH_AT] - 1
    chars = []
    i = NAME_START
    while len(chars) < count and i < len(chunk0) - 1:
        if (i - PAYLOAD_START) % 8 != 0:
            chars.append(chunk0[i])
        i += 1
    return bytes(chars).decode("ascii", errors="replace")

def dump_complete(chunks):
    """A dump ends with its first chunk shorter than 309 bytes (usually index 5, but a
    short preset can end at index 4, e.g. 277 bytes for "Vibe 1: Auto Wah")."""
    return bool(chunks) and len(chunks[-1]) < DUMP_CHUNK_LENGTH