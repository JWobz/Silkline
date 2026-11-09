"""Map preset-knob positions to preset names.

Usage (from the project root, amp on the Pi, Tone and Reverb turned down):
    python3 -m tools.knob_names

Click the preset knob one position at a time and wait for a line to print
(about 2 to 3 seconds) before the next click. For each settled click it asks
the amp for the current preset's dump and prints the position, the raw value
and the preset name. Ctrl-C to stop.

Results are printed and saved to captures/knob_names.txt (a new file each run).
"""
import time
from pathlib import Path

import silkline.protocol as protocol
from silkline.amp import Amp
from silkline.protocol import DUMP_REQUEST, settle_position
from tools.preset_select import read_dump


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    path = folder / "knob_names.txt"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"knob_names_{n}.txt"
    return path


def main():
    path = output_path()
    amp = Amp()
    position, candidates = None, []
    try:
        amp.connect()
        amp.transport.read_messages(quiet=0.2, limit=1.0)    # drain anything left over
        print("Ready. Click the preset knob once, wait for a line, repeat. Ctrl-C to stop.")
        with open(path, "x") as log:
            while True:
                for msg in amp.transport.read_messages(quiet=0.05, limit=0.3):
                    result = protocol.classify(msg)
                    if result[0] == protocol.MessageKind.PRESET_CHANGE:
                        candidates.append(result[1])
                    elif result[0] == protocol.MessageKind.STATUS and candidates:
                        seen = candidates
                        position, candidates = settle_position(candidates, position), []

                        amp.transport.send(DUMP_REQUEST)
                        dump, _ = read_dump(amp)
                        name = dump.name()
                        if not dump.complete():
                            name = f"{name!r} (dump incomplete)" if name else "(no dump)"

                        raw = (position + 8) % 16
                        line = (f"{time.strftime('%H:%M:%S')} position {position:2} "
                                f"(raw {raw:2}): {name}   seen {seen}")
                        print(line)
                        log.write(line + "\n")
                        log.flush()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        amp.close()
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
