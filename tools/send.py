import sys
import protocol

from amp import Amp
from logger import Logger

def main():
    logger = Logger(prefix="send")

    if len(sys.argv) != 3:
        print("Usage: python3 -m tools.send <parameter> <value 0-1>")
        sys.exit(1)

    param, value = sys.argv[1], float(sys.argv[2])
    found_parameter = protocol.BY_NAME.get(param.lower())
    if not found_parameter:
        print(f"Unknown parameter: {param}")
        sys.exit(1)

    amp = Amp()
    try:
        amp.handshake()
        logger.success("Connected to amp successfully.")
        replies = amp.set_parameter(found_parameter, value)
        for message in replies:
            logger.info(f"Reply: {protocol.classify(message)}")
    finally:
        amp.close()

if __name__ == "__main__":
    main()