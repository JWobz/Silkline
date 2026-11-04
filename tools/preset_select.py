"""Select presets from the Pi and read back each one's name from its dump.

Usage (from the project root, amp on the Pi, nothing else using it):
    python3 -m tools.preset_select                 # values 0 to 15
    python3 -m tools.preset_select 8 4             # only these values
    python3 -m tools.preset_select --dry           # print the messages, send nothing

For each value it sends the preset-select message seen in the app's captures
(protocol.md section 8), then the dump request (handshake line 8), and reads
the preset name from the first dump chunk. Selecting a preset only loads it;
nothing is saved. It stops if a dump doesn't arrive, rather than piling up
requests (see protocol.md section 9).

Results are printed and saved to captures/preset_select.txt (a new file each
run; an existing file is never overwritten).
"""
import sys
import time
from pathlib import Path

import spiderweb.protocol as protocol
from spiderweb.amp import DUMP_TIMEOUT, Amp

PAUSE = 3.0                   # seconds between presets (a setting of this tool only)


def is_first_dump_chunk(msg):
    """ Chunk 0: 309 bytes on channel 1, index 0, with 0F 0F at msg[10:12]. """
    return (len(msg) == protocol.DUMP_CHUNK_LENGTH and msg[:7] == protocol.HEADER
            and msg[7] == 0x01 and msg[9] == 0 and msg[10:12] == b"\x0f\x0f")


def is_dump_chunk(msg, counter):
    """ Any later chunk shares chunk 0's counter (msg[8]) and has index 1 to 5 at msg[9].

    The last chunk's size varies (45 bytes with 01 08 in older captures, 53 bytes with
    01 0F on 2026-11-03), so it is matched by counter and index, not by shape.
    """
    return (len(msg) > 12 and msg[:7] == protocol.HEADER and msg[7] == 0x01
            and msg[8] == counter and 1 <= msg[9] <= protocol.LAST_CHUNK_INDEX)


def read_dump(amp, timeout=DUMP_TIMEOUT):
    """ Reads until the last dump chunk arrives or `timeout` passes. Returns (chunks, others). """
    chunks, others = [], []
    deadline = time.time() + timeout
    while time.time() < deadline:
        for msg in amp.transport.read_messages(quiet=0.05, limit=0.3):
            if not chunks and is_first_dump_chunk(msg):
                chunks.append(msg)
            elif chunks and is_dump_chunk(msg, chunks[0][8]):
                chunks.append(msg)
                if protocol.dump_complete(chunks):
                    return chunks, others
            else:
                others.append(msg)
    return chunks, others


def describe(msg):
    result = protocol.classify(msg)
    kind = result[0].value
    return f"{kind} {result[1:]}" if len(result) > 1 else kind


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    path = folder / "preset_select.txt"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"preset_select_{n}.txt"
    return path


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    values = [int(a, 0) for a in args if a != "--dry"] or list(range(16))

    if dry:
        for v in values:
            print(f"{v:2}: {protocol.select_message(v).hex(' ')}")
        print(f"dump request: {protocol.DUMP_REQUEST.hex(' ')}")
        return

    path = output_path()
    amp = Amp()
    try:
        amp.connect()
        amp.transport.read_messages(quiet=0.2, limit=1.0)    # drain anything left over
        with open(path, "x") as log:
            for v in values:
                amp.transport.send(protocol.select_message(v))
                time.sleep(0.2)
                amp.transport.send(protocol.DUMP_REQUEST)
                chunks, others = read_dump(amp)

                sizes = [len(c) for c in chunks]
                name = protocol.name_from_dump(chunks[0]) if chunks else None
                events = ", ".join(describe(m) for m in others) or "none"
                line = f"value {v:2}: {name!r:28} chunks {sizes}  other messages: {events}"
                print(line)
                log.write(line + "\n")
                log.writelines(f"    {m.hex()}\n" for m in chunks + others)
                log.flush()

                if not protocol.dump_complete(chunks):
                    print("No complete dump came back, so stopping here. "
                          "If the amp stops responding, power-cycle it and replug USB.")
                    break
                time.sleep(PAUSE)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        amp.close()
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
