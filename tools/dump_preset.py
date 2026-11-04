"""Save the current preset dump from the amp as hex, one message per line.

Usage (from the project root, amp already showing the preset you want):
    python3 -m tools.dump_preset captures/chime_A.txt

The handshake asks the amp for its current preset, so the dump arrives
among the handshake replies. A good dump is five 309-byte messages
(followed by a short final one). Don't touch the amp's controls while
this runs.
"""
import sys
from pathlib import Path

from spiderweb.amp import Amp

DUMP_CHUNK_LENGTH = 309
DUMP_CHUNK_COUNT = 5


def main():
    if len(sys.argv) < 2 or not sys.argv[1]:
        raise SystemExit("Usage: python3 -m tools.dump_preset <output file>")

    path = Path(sys.argv[1])
    if path.exists():
        raise SystemExit(f"{path} already exists; pick a new name so nothing is overwritten.")
    path.parent.mkdir(parents=True, exist_ok=True)

    amp = Amp()
    try:
        messages = amp.connect()

        chunks = 0
        with open(path, "x") as f:
            for number, message in enumerate(messages):
                f.write(f"{message.hex()}\n")
                if len(message) == DUMP_CHUNK_LENGTH:
                    chunks += 1
                    print(f"  message {number}: {len(message)} bytes (dump chunk {chunks})")
    finally:
        amp.close()

    print(f"Saved {len(messages)} messages to {path}")
    if chunks == DUMP_CHUNK_COUNT:
        print(f"Dump looks complete: {chunks} chunks of {DUMP_CHUNK_LENGTH} bytes.")
    else:
        print(f"WARNING: expected {DUMP_CHUNK_COUNT} chunks of {DUMP_CHUNK_LENGTH} bytes, got {chunks}. "
              "Power-cycle the amp and capture again before sending this file.")
        sys.exit(1)


if __name__ == "__main__":
    main()