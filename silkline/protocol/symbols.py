"""
symbols.py

The Line 6 app's symbol table: the amp's numbers for models and amp knobs, as names.

protocol.md section 10. The file is the app's own (never committed); see load_symbols.
"""
import struct
from pathlib import Path


def load_symbols(path):
    """The symbol table's names, as a list: names[n] is the name of number n.

    defaultSymbolTable_Parker.bin is the Spider V MkII's (910 names): its numbers
    are the amp's model numbers and its namespace-0 knob ids. Layout: count and
    file size (4 bytes each), then count entries (offset, hash, length), then the
    names. Raises FileNotFoundError if it isn't there, ValueError if the size
    doesn't match (not a symbol table).
    """
    data = Path(path).read_bytes()
    count, size = struct.unpack_from("<II", data, 0)        # two 4-byte numbers at the start
    if size != len(data):
        raise ValueError(f"{path} isn't a symbol table (size {size}, file {len(data)})")
    names_at = 8 + 12 * count                               # the name area follows the entries
    names = []
    for i in range(count):
        offset, _hash, length = struct.unpack_from("<III", data, 8 + 12 * i)
        start = names_at + offset
        names.append(data[start:start + length].decode("latin-1"))
    return names