"""
presets.py

The amp's preset list: the name of every preset, which the amp sends during
the handshake (protocol.md section 4, "Preset list").

The handshake asks for every preset twice, in two lists: kind 0x06, the short
list (indexes 0 to 127), and kind 0x0E, the long list (0 to 114). Each answer is
an entry holding one name, in the short or the long layout. An entry doesn't say
which preset it's for, so it is matched to the request it answers by handshake
line; the message counters drift, so they can't be used.
"""


def unpack(msg):
    """Undoes the amp's 7-bit packing of msg[12:-1] and returns the data bytes.

    SysEx bytes can't have their top bit set, so the amp packs 7 data bytes
    into each group of 8: the group's first byte holds their top bits, bit k
    for data byte k. The last group can be shorter. The F7 that ends the
    message isn't data.
    """
    body = msg[12:-1]    # removes header
    out = bytearray()
    for start in range(0, len(body), 8):
        group = body[start:start+8]
        tops = group[0]
        for k, b in enumerate(group[1:]):
            if tops & (0x40 >> k):
                b = b | 0x80
            out.append(b)
    return bytes(out)

def preset_list_request(msg):
    """Returns (kind, index) if msg is a preset-list request, or None.

    kind is 0x06 (short list) or 0x0E (long list). index is msg[22], the
    preset's place in the list, which is also the value select_preset() takes
    (tried for 0 to 20). Meant for handshake lines: anything that isn't a
    29-byte request, however short, gives None.
    """
    if len(msg) == 29 and msg[11] == 0x0B and (msg[13] == 0x06 or msg[13] == 0x0E):
        return (msg[13], msg[22])
    return None

def entry_name(msg):
    """Returns the preset name in a preset-list entry, or None if msg isn't one.

    Entries are 45 to 77 bytes with msg[7] == 1 and msg[13] == 1; names of 12
    characters or fewer come in 45 bytes. Once unpacked, the name's length + 1
    is in one of two places, and u[4] tells the layouts apart:
      short layout  length at u[12], name from u[16], u[4] == u[12] + 8
      long layout   length at u[28], name from u[32], u[4] == u[28] + 24
    A name with bytes that aren't printable ASCII gives None instead of raising.
    """
    name = None
    if 45 <= len(msg) <= 77 and msg[13] == 1 and msg[7] == 1:
        u = unpack(msg)
        if u[4] == u[12] + 8:
            raw = u[16:16 + u[12]-1]
            if all(32 <= b < 127 for b in raw):
                name = raw.decode("ascii")
        elif len(u) > 28 and u[4] == u[28] + 24:
            raw = u[32:32 + u[28] - 1]
            if all(32 <= b < 127 for b in raw):
                name = raw.decode("ascii")
    return name

def preset_names(lines, replies_per_line):
    """Builds {index: name} for every preset named in the handshake.

    lines are the handshake lines that were sent, and replies_per_line what
    Connection.open() returned for them: one list of replies per line, in the
    same order. A request's answer is the first entry in its line's replies.
    Names from the short list (0x06) go in first, then the long list (0x0E)
    fills the indexes still missing (on the real amp: 0, 4 and 34). Other lines,
    and requests with no entry in their replies, are skipped.
    """
    short = {}
    long = {}
    for line, replies in zip(lines, replies_per_line):
        request = preset_list_request(line)
        if request is None:
            continue
        kind, index = request
        for reply in replies:
            name = entry_name(reply)
            if name is not None:
                if kind == 0x06:
                    short[index] = name
                else:
                    long[index] = name
                break
    names = dict(short)
    for index, name in long.items():
        names.setdefault(index, name)   
    return names

            

