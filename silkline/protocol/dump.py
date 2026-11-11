"""
dump.py

Preset dumps: collecting one from the amp, and reading what's in it
(protocol.md section 3).

A dump is the loaded preset, sent in chunks on channel 1. DumpCollector gathers
them; records() and read_values() read the parameter values, stage_models()
each stage's model, and preset_data() the preset as save() uploads it.
"""

import struct

from silkline.protocol.packing import unpack_data
from silkline.protocol.parameters import DUMP_RECORDS

from .messages import HEADER

DUMP_CHUNK_LENGTH = 309

_LAST_CHUNK_INDEX = 5  # The last chunk of a dump is usually index 5, but a short preset can end at index 4
_NAME_LENGTH_AT = 56  # in dump chunk 0: name length + 1
_NAME_START = 61  # in dump chunk 0: first character of the name
_PAYLOAD_START = 12  # 7-bit packing groups of 8 bytes start here

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
            accepted = _is_first_dump_chunk(msg)
        else:
            accepted = not self.complete() and _is_dump_chunk(msg, self.chunks[0][8])

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
        count = chunk0[_NAME_LENGTH_AT] - 1
        chars = []
        i = _NAME_START
        while len(chars) < count and i < len(chunk0) - 1:
            if (i - _PAYLOAD_START) % 8 != 0:
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
            out += unpack_data(chunk)
        return bytes(out)
    
def read_values(dump):
    """The known parameters' values in a dump, as {wire key: value}."""
    return {DUMP_RECORDS[key]: value for key, value in records(dump.data()).items() if key in DUMP_RECORDS}

def read_tempo(dump):
    """The preset's tempo in BPM (header record 3, protocol.md section 3), or None."""
    data, name = dump.data(), dump.name()
    if not name:
        return None
    at = data.find(name.encode())
    if at < 0:
        return None
    start = at + len(name) + 1
    for o in range(start, start + 80, 10):
        r = data[o:o+10]
        if len(r) == 10 and r[0] == 3 and r[4] == 3:
            return struct.unpack("<f", r[6:10])[0]  
    return None

def stage_models(dump):
    """Each stage's model number in a dump, as {stage: model}, e.g. {"amp": 0xDC, ...}.

    Only the blocks in STAGES; an incomplete dump gives fewer, an empty one {}.
    """
    return {STAGES[key]: value for key, value in block_models(dump.data()).items() if key in STAGES}

def records(data):
    """Every parameter record, as {(block, sub, record_id): value}.

    Float for type 03, a whole number otherwise; a block's records stop early at any
    other type. Give it dump.data().
    """
    out = {}
    for block, sub, model, count, o in _find_blocks(data):
        for _ in range(count):
            r = data[o:o+10]
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
    return {(block, sub): model for block, sub, model, _, _ in _find_blocks(data)}
    

def _find_blocks(data):
    """Every block start in a dump's data, in order, as (block, sub, model, count, start).

    A block starts with three info records (protocol.md section 3): 03 its block
    and sub, 05 its model, 06 how many records follow. start is where the first of
    those records is. records() and block_models() are built on this.
    """
    out, o = [], 0
    while o + 30 <= len(data):
        a, b, c = data[o:o+10], data[o+10:o+20], data[o+20: o+30]    
        is_block_start = (a[0] == 3 and a[3] == 0x80 and b[0] == 5 and b[3] == 0x80 and c[0] == 6 and c[3] == 0x80)
        if not is_block_start:
            o += 1
            continue
        block_word = int.from_bytes(a[6:10], "little")
        block, sub = block_word & 0xFF, block_word >> 8
        model = int.from_bytes(b[6:10], "little")
        count = int.from_bytes(c[6:10], "little")
        out.append((block, sub, model, count, o + 30))
        o += 30
    return out


def _is_first_dump_chunk(msg):
    """ Chunk 0: 309 bytes on channel 1, index 0, with 0F 0F at msg[10:12]. """
    return (len(msg) == DUMP_CHUNK_LENGTH and msg[:7] == HEADER
            and msg[7] == 0x01 and msg[9] == 0 and msg[10:12] == b"\x0f\x0f")

def _is_dump_chunk(msg, counter):
    """True if `msg` is a later chunk (index 1 to 5) of the dump with this counter.

    Every chunk of one dump shares chunk 0's counter (msg[8]). The last chunk's size
    varies (45 bytes with 01 08, 53 bytes with 01 0F, or a short 277-byte chunk 4),
    so chunks are matched by counter and index, not by shape.
    """
    return (len(msg) > 12 and msg[:7] == HEADER and msg[7] == 0x01
                    and msg[8] == counter and 1 <= msg[9] <= _LAST_CHUNK_INDEX)

def preset_data(dump):
    """The preset inside a dump, as save() uploads it: the data after the 12-byte header.

    The header's length counts the bytes after it: 4 zero bytes and the preset.
    """
    data = dump.data()
    length = int.from_bytes(data[4:8], "little")
    return data[12:12 + length -4]