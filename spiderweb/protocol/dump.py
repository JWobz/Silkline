from .messages import HEADER

DUMP_CHUNK_LENGTH = 309

LAST_CHUNK_INDEX = 5  # The last chunk of a dump is usually index 5, but a short preset can end at index 4
NAME_LENGTH_AT = 56  # in dump chunk 0: name length + 1
NAME_START = 61  # in dump chunk 0: first character of the name
PAYLOAD_START = 12  # 7-bit packing groups of 8 bytes start here

class DumpCollector:
    def __init__(self):
        self.chunks = []

    def offer(self, msg):
        """Takes `msg` if it belongs to this dump. Returns True if it was taken.

        Before the first chunk arrives, only a first chunk is taken. After that, only later
        chunks of the same dump are taken, until the dump is complete. Anything else
        (other messages, or chunks of a different dump) is refused, so the caller can pass
        it on.
        """
        accepted = False
        if not self.chunks:
            accepted = is_first_dump_chunk(msg)
        else:
            accepted = not self.complete() and is_dump_chunk(msg, self.chunks[0][8])

        if accepted:
            self.chunks.append(msg)
        return accepted

    def complete(self):
        """A dump ends with its first chunk shorter than 309 bytes (usually index 5, but a
            short preset can end at index 4, e.g. 277 bytes for "Vibe 1: Auto Wah")."""
        return bool(self.chunks) and len(self.chunks[-1]) < DUMP_CHUNK_LENGTH

    def name(self):
        """Reads the preset name from the first dump chunk.

        The payload is 7-bit packed in groups of 8 bytes starting at msg[12]: the first
        byte of each group holds high bits, so it is skipped when collecting characters.
        """
        if not self.chunks:
            return None
        
        chunk0 = self.chunks[0]
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
    

def is_first_dump_chunk(msg):
    """ Chunk 0: 309 bytes on channel 1, index 0, with 0F 0F at msg[10:12]. """
    return (len(msg) == DUMP_CHUNK_LENGTH and msg[:7] == HEADER
            and msg[7] == 0x01 and msg[9] == 0 and msg[10:12] == b"\x0f\x0f")

def is_dump_chunk(msg, counter):
    """True if `msg` is a later chunk (index 1 to 5) of the dump with this counter.

    Every chunk of one dump shares chunk 0's counter (msg[8]). The last chunk's size
    varies (45 bytes with 01 08, 53 bytes with 01 0F, or a short 277-byte chunk 4),
    so chunks are matched by counter and index, not by shape.
    """
    return (len(msg) > 12 and msg[:7] == HEADER and msg[7] == 0x01
                    and msg[8] == counter and 1 <= msg[9] <= LAST_CHUNK_INDEX)