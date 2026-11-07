"""Turn a Wireshark USBPcap capture (.pcapng) of the amp into a text timeline of messages.

Usage (from the project root):
    python3 -m tools.pcap_to_text captures/windows/names.pcapng

Writes captures/windows/names.txt: one SysEx message per line,
    <clock time> <seconds from start> <out|in> <hex>
The clock time (local time, like tools/capture_gatherer.html's log) lines a capture up
with notes taken during it.
"out" is PC -> amp, "in" is amp -> PC. The last word is the hex, so
tests/helpers.capture_messages() and the other tools can read it.

USBPcap puts a header before each USB transfer (its first two bytes give its length;
byte 21 is the endpoint, top bit set for IN). The amp is a USB-MIDI device: its data is
4-byte event packets whose low nibble says how many MIDI bytes follow (0x4 = SysEx
start or continue, 3 bytes; 0x5 / 0x6 / 0x7 = SysEx end with 1 / 2 / 3 bytes). Those
bytes are joined into whole F0...F7 messages, separately for each direction.
"""
import struct
import sys
from datetime import datetime
from pathlib import Path

SYSEX_BYTES = {0x4: 3, 0x5: 1, 0x6: 2, 0x7: 3}


def packets(path):
    """ (timestamp in seconds, USB transfer bytes) for every packet in a pcapng file. """
    data = Path(path).read_bytes()
    o, resolution = 0, 1e-6
    while o + 12 <= len(data):
        block_type, block_len = struct.unpack_from("<II", data, o)
        if block_len < 12:
            break
        body = data[o + 8:o + block_len - 4]
        if block_type == 1 and len(body) >= 8:           # interface description: look for if_tsresol
            p = 8
            while p + 4 <= len(body):
                code, length = struct.unpack_from("<HH", body, p)
                if code == 0:
                    break
                if code == 9 and length >= 1:
                    r = body[p + 4]
                    resolution = 2 ** -(r & 0x7F) if r & 0x80 else 10 ** -r
                p += 4 + ((length + 3) & ~3)
        elif block_type == 6 and len(body) >= 20:        # enhanced packet
            _, ts_high, ts_low, captured, _ = struct.unpack_from("<IIIII", body, 0)
            yield ((ts_high << 32) | ts_low) * resolution, body[20:20 + captured]
        o += block_len


def messages(path, absolute=False):
    """ (seconds, "out"/"in", message) for every SysEx message in the capture.

    Seconds are from the first message, or Unix time if absolute is True.
    """
    building = {"in": bytearray(), "out": bytearray()}
    start = None
    for ts, pkt in packets(path):
        if len(pkt) < 27:
            continue
        header_len = struct.unpack_from("<H", pkt, 0)[0]
        endpoint = pkt[21]
        payload = pkt[header_len:]
        if not payload or len(payload) % 4:
            continue
        direction = "in" if endpoint & 0x80 else "out"
        start = ts if start is None else start
        for p in range(0, len(payload), 4):
            cin = payload[p] & 0x0F
            n = SYSEX_BYTES.get(cin)
            if n is None:
                continue
            chunk = payload[p + 1:p + 1 + n]
            buf = building[direction]
            if chunk[:1] == b"\xf0":
                buf.clear()
            buf.extend(chunk)
            if 0xF7 in chunk:
                end = buf.index(0xF7)
                yield (ts if absolute else ts - start), direction, bytes(buf[:end + 1])
                buf.clear()


def main():
    for name in sys.argv[1:]:
        path = Path(name)
        out = path.with_suffix(".txt")
        found = list(messages(path, absolute=True))
        first = found[0][0] if found else 0
        lines = [f"{datetime.fromtimestamp(t).strftime('%H:%M:%S.%f')[:-3]} {t - first:9.3f} {d:3} {m.hex()}"
                 for t, d, m in found]
        out.write_text("\n".join(lines) + "\n")
        print(f"{path}: {len(lines)} messages -> {out}")


if __name__ == "__main__":
    main()
