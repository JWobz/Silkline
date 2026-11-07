"""
upload.py

Uploads: sending data to the amp (a save, or a type change in v1.1). 
protocol.md section 8, "Uploads".
"""

HEADER = bytes.fromhex("f000010c22054d")
CHANNEL = 0x01                              # uploads go on channel 1, like dumps
PIECE = 210                                 # data bytes per message
EDIT_BUFFER = 0xFFFFFFFF                    # "slot" for the live preset (type changes, v1.1)

def pack(data):
    """The amp's 7-bit packing (the reverse of presets.unpack).

    Pads data with zeros to a whole group of 7. Each group becomes a byte of
    top bits (data byte k's top bit is 0x40 >> k) and the 7 bytes without them.
    """
    data = data + bytes(-len(data) % 7)
    out = bytearray()
    for g in range(0, len(data), 7):
        group = data[g:g + 7]
        top = 0
        for k, b in enumerate(group):
            if b & 0x80:
                top |= 0x40 >> k
        out.append(top)
        out.extend(b & 0x7F for b in group)
    return bytes(out)

def upload_message(counter, index, data):
    """One channel-1 message: counter, index, length - 1 in two halves, packed data, F7."""
    n = len(data) - 1
    return HEADER + bytes([CHANNEL, counter, index, n >> 4, n & 0x0F]) + pack(data) + b"\xf7"

def build_upload(counter, slot, data):
    """All the messages of an upload: a header, then the data in 210-byte pieces.

    The header's data is four little-endian 32-bit numbers: 12, len + 8, slot, len.
    The pieces all use counter + 1, numbered 0, 1, 2... slot is a preset number,
    or EDIT_BUFFER.
    """
    header = b"".join(n.to_bytes(4, "little") for n in (12, len(data) + 8, slot, len(data)))
    messages = [upload_message(counter, 0, header)]
    for i in range(0, len(data), PIECE):
        messages.append(upload_message((counter+1) % 128, i // PIECE, data[i:i+PIECE]))
    return messages