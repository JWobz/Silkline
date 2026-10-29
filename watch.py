import sys
from amp import Amp
from protocol import KNOWN_PARAMETERS, classify

def connect():
    print("Connecting to amp")
    amp = Amp()
    messages = amp.handshake()
    with open(f"captures/{sys.argv[1]}", "w") as f:
        for message in messages:
            f.write(message.hex() + "\n")
    print("Connected")

    try:
        while True:
            messages = amp.read_messages()
            updates = {}
            for message in messages:
                translated_message = classify(message)
                kind = translated_message[0]
                if kind == "param":
                    key, value = translated_message[1:]
                    updates[key] = value
                elif kind == "unknown":
                    shape = translated_message[1]
                    print(f"Unknown message shape: {shape} hex: {message.hex()}")

            if (len(updates) > 0):
                line = ", ".join(f"{KNOWN_PARAMETERS.get(k, f"Unfound {"/".join(f"{x:02X}" for x in k)}")}={v}" for k, v in sorted(updates.items()))
                print(line)
    except KeyboardInterrupt:
        print("\nStopping")
    finally:
        amp.close()

if __name__ == "__main__":
    connect()