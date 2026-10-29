from amp import Amp

def main():
    amp = Amp()
    try:
        logs = amp.handshake_log()
        for number, replies in logs:
            lengths = [len(r) for r in replies]
            if 309 in lengths:
                print(f"Message {number}, {lengths}")
    
    except KeyboardInterrupt:
            print("\nStopping")
    finally:
        amp.close()

if __name__ == "__main__":
    main()
