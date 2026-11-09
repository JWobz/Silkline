"""Select presets from the Pi and read back each one's name from its dump.

Usage (from the project root, amp on the Pi, nothing else using it):
    python3 -m tools.preset_select                 # values 0 to 15
    python3 -m tools.preset_select 8 4             # only these values
    python3 -m tools.preset_select --dry           # print the messages, send nothing

For each value it calls Amp.select_preset, which sends the preset-select
message (protocol.md section 8) and then the dump request, and waits for the
dump. Selecting a preset only loads it; nothing is saved. It stops if a dump
doesn't arrive, rather than piling up requests (see protocol.md section 9).

Results are printed and saved to captures/preset_select.txt (a new file each
run; an existing file is never overwritten).
"""
import sys
import time
from pathlib import Path

import silkline.protocol as protocol
from silkline.amp import Amp, load_handshake
from silkline.connection import Connection
from silkline.errors import AmpTimeout

PAUSE = 3.0                   # seconds between presets (a setting of this tool only)


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
    others = []                       # messages that weren't part of the dump
    amp = Amp(Connection(load_handshake()))
    amp.add_listener(others.append)
    try:
        amp.connect()
        with open(path, "x") as log:
            for v in values:
                others.clear()
                try:
                    dump = amp.select_preset(v)
                except AmpTimeout:
                    line = f"value {v:2}: no complete dump came back"
                    print(line)
                    log.write(line + "\n")
                    log.writelines(f"    {m.hex()}\n" for m in others)
                    print("Stopping here. If the amp stops responding, power-cycle it and replug USB.")
                    break
                time.sleep(0.3)       # let the messages after the dump arrive

                sizes = [len(c) for c in dump.chunks]
                seen = list(others)
                events = ", ".join(describe(m) for m in seen) or "none"
                line = f"value {v:2}: {dump.name()!r:28} chunks {sizes}  other messages: {events}"
                print(line)
                log.write(line + "\n")
                log.writelines(f"    {m.hex()}\n" for m in dump.chunks + seen)
                log.flush()
                time.sleep(PAUSE)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        amp.close()
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
