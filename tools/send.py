"""Set one parameter and show what the amp says back.

Usage (from the project root):
    python3 -m tools.send drive 0.5
"""
import sys
import time

import spiderweb.protocol as protocol
from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.logger import Logger

LISTEN = 1.0          # seconds to show replies after the set


def main():
    logger = Logger(prefix="send")

    if len(sys.argv) != 3:
        print("Usage: python3 -m tools.send <parameter> <value>   (0 / 1 for an on/off)")
        sys.exit(1)

    param, value = sys.argv[1], float(sys.argv[2])
    found_parameter = protocol.BY_NAME.get(param.lower())
    if not found_parameter:
        print(f"Unknown parameter: {param}")
        sys.exit(1)

    amp = Amp(Connection(load_handshake()))
    amp.add_listener(lambda message: logger.info(f"Reply: {protocol.classify(message)}"))
    try:
        amp.connect()
        logger.success("Connected to amp successfully.")
        amp.set_parameter(found_parameter, value)
        time.sleep(LISTEN)        # replies arrive through the listener
    finally:
        amp.close()


if __name__ == "__main__":
    main()
