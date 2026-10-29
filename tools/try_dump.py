from amp import Amp

DUMP_REQUEST = bytes.fromhex(
    "f000010c22054d010200000b000b0000000400003c007f7f7f7f0000f7"
)


def main():
    amp = Amp()
    try:
        amp.handshake()
        for attempt in range(1, 4):
            amp.send(DUMP_REQUEST)
            replies = amp.read_messages()
            print(f"Request {attempt}: {[len(r) for r in replies]}")
    except KeyboardInterrupt:
        print("\nStopping")
    finally:
        amp.close()


if __name__ == "__main__":
    main()