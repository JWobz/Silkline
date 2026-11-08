"""
dump.py

 
"""

import struct

from spiderweb.protocol.parameters import DUMP_RECORDS
from spiderweb.protocol.presets import unpack

from .messages import HEADER

DUMP_CHUNK_LENGTH = 309

LAST_CHUNK_INDEX = 5  # The last chunk of a dump is usually index 5, but a short preset can end at index 4
NAME_LENGTH_AT = 56  # in dump chunk 0: name length + 1
NAME_START = 61  # in dump chunk 0: first character of the name
PAYLOAD_START = 12  # 7-bit packing groups of 8 bytes start here

# The blocks people pick a model for, by the name used for their on/off parameter
# ("Stomp On"...). The panel (74:3) and 21:3 are left out. protocol.md section 8.
STAGES = {
    (0x2A, 0): "amp",
    (0x22, 3): "cab",
    (0x23, 3): "comp",
    (0x25, 3): "eq",
    (0x04, 3): "vol",
    (0x5E, 2): "gate",
    (0x0C, 3): "wah",
    (0x19, 3): "stomp",
    (0x1B, 3): "mod",
    (0x1D, 3): "delay",
    (0x1F, 3): "reverb"
}

class DumpCollector:
    """Collects one preset dump's chunks (protocol.md section 3), as request() wants.

    offer() each message; complete() is True once the last, short chunk is in.
    Then name() is the preset's name, data() the whole dump and stream() the full
    chunks only (records and read_values use it). chunks are the raw messages.
    """

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

    def stream(self):
        """The dump's data: each full chunk unpacked, its first 256 bytes kept, joined."""
        return b"".join(unpack(chunk)[:256] for chunk in self.chunks if len(chunk) == DUMP_CHUNK_LENGTH)

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

    def data(self):
        """Every chunk unpacked and cut to its real length (msg[10:12], length - 1), joined.

        Unlike stream(), it keeps the last, short chunk, so it holds the whole dump:
        a 12-byte header (01 00 00 00, a length, 00 00 00 00) and then the preset.
        """
        out = bytearray()
        for chunk in self.chunks:
            real = (chunk[10] << 4 | chunk[11]) + 1
            out += unpack(chunk)[:real]
        return bytes(out)
    
def read_values(dump):
    """The known parameters' values in a dump, as {wire key: value}."""
    return {DUMP_RECORDS[key]: value for key, value in records(dump.data()).items() if key in DUMP_RECORDS}

def stage_models(dump):
    """Each stage's model number in a dump, as {stage: model}, e.g. {"amp": 0xDC, ...}.

    Only the blocks in STAGES; an incomplete dump gives fewer, an empty one {}.
    """
    return {STAGES[key]: value for key, value in block_models(dump.data()).items() if key in STAGES}

def records(stream):
    """Every parameter record, as {(block, sub, record_id): value}."""
    out, o = {}, 0
    while o + 30 <= len(stream):
        a, b, c = stream[o:o+10], stream[o+10:o+20], stream[o+20: o+30]
        is_block_start = (a[0] == 3 and a[3] == 0x80 and b[0] == 5 and b[3] == 0x80 and c[0] == 6 and c[3] == 0x80)
        if not is_block_start:
            o += 1
            continue
        block_word = int.from_bytes(a[6:10], "little")
        block, sub = block_word & 0xFF, block_word >> 8
        count = int.from_bytes(c[6:10], "little")
        o += 30
        for _ in range(count):
            r = stream[o:o+10]
            if len(r) < 10:
                break
            if r[4] not in (1, 2, 3):
                break
            raw = r[6:10]
            value = struct.unpack("<f", raw)[0] if r[4] == 3 else int.from_bytes(raw, "little")
            out[(block, sub, r[0])] = value
            o += 10
    return out

def block_models(data):
    """Each block's model number, as {(block, sub): model}.

    The model is the value of the 05 info record at the block's start (protocol.md
    section 3); the symbol table names it (symbols.py). Give it dump.data(), not
    stream(): the last blocks can be in the short last chunk.
    """
    out, o = {}, 0
    while o + 30 <= len(data):
        a, b, c = data[o:o+10], data[o+10:o+20], data[o+20: o+30]    
        is_block_start = (a[0] == 3 and a[3] == 0x80 and b[0] == 5 and b[3] == 0x80 and c[0] == 6 and c[3] == 0x80)
        if not is_block_start:
            o += 1
            continue
        block_word = int.from_bytes(a[6:10], "little")
        block, sub = block_word & 0xFF, block_word >> 8
        model = int.from_bytes(b[6:10], "little")
        out[(block, sub)] = model
        o += 30
    return out

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

def preset_data(dump):
    """The preset inside a dump, as save() uploads it: the data after the 12-byte header.

    The header's length counts the bytes after it: 4 zero bytes and the preset.
    """
    data = dump.data()
    length = int.from_bytes(data[4:8], "little")
    return data[12:12 + length -4]