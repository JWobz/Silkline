"""Print every message from the amp, raw, with its shape. Ctrl-C to stop.

Usage (from the project root):
    python3 -u -m tools.raw_watch | tee captures/<name>.txt
"""
import time

from silkline.amp import Amp, load_handshake
from silkline.connection import Connection


def show(m):
    shape = (len(m), m[11] if len(m) > 11 else None, m[13] if len(m) > 13 else None)
    print(time.strftime("%H:%M:%S"), shape, m.hex()[:90], flush=True)


def main():
    amp = Amp(Connection(load_handshake()))
    amp.add_listener(show)
    amp.on_lost(lambda error: print(f"Lost the amp: {error!r}. Ctrl-C to stop.", flush=True))
    try:
        amp.connect()
        print("Listening. Ctrl-C to stop.", flush=True)
        while True:
            time.sleep(1)          # the connection's reader thread does the work
    except KeyboardInterrupt:
        pass
    finally:
        amp.close()


if __name__ == "__main__":
    main()
