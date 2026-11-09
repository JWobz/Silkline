"""
packing.py

The amp's 7-bit packing, both ways (protocol.md section 3).

SysEx bytes can't have their top bit set, so dumps, uploads and preset lists carry
their data as groups of 8 bytes: a byte of top bits, then 7 bytes without them.
"""


def pack(data):
    """The amp's 7-bit packing (the reverse of unpack).

    Pads data with zeros to a whole group of 7. Each group becomes a byte of
    top bits (data byte k's top bit is 0x40 >> k) and the 7 bytes without them.
    """
    data = data + bytes(-len(data) % 7)
    out = bytearray()
    for g in range(0, len(data), 7):
        group = data[g : g + 7]
        top = 0
        for k, b in enumerate(group):
            if b & 0x80:
                top |= 0x40 >> k
        out.append(top)
        out.extend(b & 0x7F for b in group)
    return bytes(out)


def unpack(msg):
    """Undoes the amp's 7-bit packing of msg[12:-1] and returns the data bytes.

    SysEx bytes can't have their top bit set, so the amp packs 7 data bytes
    into each group of 8: the group's first byte holds their top bits, most
    significant first (data byte k's top bit is 0x40 >> k). The last group can be shorter. The F7 that ends the
    message isn't data.
    """
    body = msg[12:-1]  # removes header
    out = bytearray()
    for start in range(0, len(body), 8):
        group = body[start : start + 8]
        tops = group[0]
        for k, b in enumerate(group[1:]):
            if tops & (0x40 >> k):
                b = b | 0x80
            out.append(b)
    return bytes(out)

def unpack_data(msg):
    """A message's data cut to its real length: msg[10:12] is the length - 1, in two halves.

    unpack() keeps the padding at the end of the last group; this drops it.
    """
    return unpack(msg)[:(msg[10] << 4 | msg[11]) + 1]