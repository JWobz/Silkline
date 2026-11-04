"""Print every message from the amp, raw, with its shape. Ctrl-C to stop.

Usage (from the project root):
    python3 -u -m tools.raw_watch | tee captures/<name>.txt
"""
import time

from spiderweb.amp import Amp


def main():
    amp = Amp()
    try:
        amp.handshake()
        print("Listening. Ctrl-C to stop.")
        while True:
            for m in amp.transport.read_messages():
                shape = (len(m), m[11] if len(m) > 11 else None, m[13] if len(m) > 13 else None)
                print(time.strftime("%H:%M:%S"), shape, m.hex()[:90])
    except KeyboardInterrupt:
        pass
    finally:
        amp.close()


if __name__ == "__main__":
    main()
