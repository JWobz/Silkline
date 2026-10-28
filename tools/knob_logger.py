#!/usr/bin/env python3
"""Record what the amp reports while you turn its physical knobs.
Needs spider_test.py in the same folder. Usage: python3 knob_logger.py [--dev /dev/snd/midiC3D0]
For each knob: type its name, press Enter, turn it SLOWLY from minimum to maximum
(about 10 seconds), then press Enter again. Results go to knob_log.jsonl
"""
import json, os, select, sys, time
import spider_test as st

dev = st.DEV
amp = st.Amp(dev)
amp.drain(0.1, 0.3)
print("Connecting (replaying handshake)...")
for h in st.HANDSHAKE:
    amp.send(bytes.fromhex(h)); amp.drain()
amp.drain(0.5, 2.0)
print("Connected.\n")

out = open("knob_log.jsonl", "a")
while True:
    name = input("Knob name (blank to finish): ").strip()
    if not name:
        break
    input("  Press Enter, then turn '%s' slowly from MIN to MAX. Press Enter again when done. " % name)
    amp.drain(0.05, 0.2)
    t0, n = time.time(), 0
    print("  recording...")
    while True:
        r, _, _ = select.select([amp.fd, sys.stdin], [], [], 0.05)
        if sys.stdin in r:
            sys.stdin.readline()
            break
        if amp.fd in r:
            try:
                chunk = os.read(amp.fd, 4096)
            except BlockingIOError:
                continue
            amp.buf += chunk
            while 0xF7 in amp.buf:
                i = amp.buf.index(0xF7)
                msg = bytes(amp.buf[:i + 1]); del amp.buf[:i + 1]
                out.write(json.dumps({"knob": name, "t": round(time.time() - t0, 4), "hex": msg.hex()}) + "\n")
                n += 1
    out.flush()
    print("  saved %d messages for '%s'\n" % (n, name))
print("Done. Copy knob_log.jsonl back to your PC.")
