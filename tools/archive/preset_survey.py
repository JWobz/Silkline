"""Collects, for each preset you select on the amp, its full dump and which amp-block ids the Drive knob uses.

Run from ~/SpiderWeb-Amp:   python3 -m tools.preset_survey
Then, for each preset: turn the preset knob, wait for the name to appear, and when asked, turn the
Drive knob back and forth for a few seconds. Ctrl-C to stop.
"""
import re
import time
from collections import Counter
from pathlib import Path

from spiderweb.amp import Amp
from spiderweb.protocol import MessageKind, classify

DUMP_REQUEST = bytes.fromhex("f000010c22054d010200000b000b0000000400003c007f7f7f7f0000f7")
OUT_DIR = Path("captures/presets")
AMP_BLOCK = 0x2A
NOT_A_FLOAT_ID = 0x02
MIN_MOVEMENT = 0.2        # an id counts as "moved" if its value changed by at least this much
DEBUG = True              # print every preset name the amp announces


class Survey:
    """ Reads from the amp and always remembers the latest preset name it announced,
    no matter which step of the survey was doing the reading. """

    def __init__(self, amp):
        self.amp = amp
        self.preset = None

    def read_for(self, seconds):
        """ Collects every message the amp sends for the given number of seconds. """
        messages = []
        end = time.time() + seconds
        while time.time() < end:
            for message in self.amp.transport.read_messages():
                messages.append(message)
                result = classify(message)
                if result[0] == MessageKind.PRESET_INFO:
                    if DEBUG and result[1] != self.preset:
                        print(f"  [saw preset {result[1]!r}]")
                    self.preset = result[1]
        return messages

    def wait_for_new_preset(self, last_name):
        """ Blocks until the amp has announced a preset name different from last_name. """
        counts = Counter()
        last_report = time.time()
        while self.preset is None or self.preset == last_name:
            for message in self.read_for(0.5):
                counts[classify(message)[0].value] += 1
            if time.time() - last_report >= 5:
                print(f"  [waiting; last 5 s: {dict(counts)}]")
                counts.clear()
                last_report = time.time()
        return self.preset

    def get_dump(self, tries=3):
        """ Asks for the current preset's dump. Returns the 309-byte chunks, or None if it never arrived. """
        for _ in range(tries):
            self.amp.transport.send(DUMP_REQUEST)
            chunks = [m for m in self.read_for(3.0) if len(m) == 309]
            if len(chunks) >= 5:
                return chunks[:5]
        return None

    def drive_ids(self, seconds):
        """ Watches amp-block parameters while you turn the Drive knob. Returns {id: (low, high)} for moved ids. """
        seen = {}
        for message in self.read_for(seconds):
            result = classify(message)
            if result[0] != MessageKind.PARAM:
                continue
            (block, param_id, sub), value = result[1], result[2]
            if block != AMP_BLOCK or param_id == NOT_A_FLOAT_ID or not (0.0 <= value <= 1.0):
                continue
            low, high = seen.get(param_id, (value, value))
            seen[param_id] = (min(low, value), max(high, value))
        return {i: r for i, r in seen.items() if r[1] - r[0] >= MIN_MOVEMENT}


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    amp = Amp()
    survey = Survey(amp)
    last_name = None
    try:
        amp.handshake()
        print("Connected. Turn the preset knob to a preset you haven't done yet.")
        while True:
            name = survey.wait_for_new_preset(last_name)
            last_name = name
            print(f"\nPreset: {name!r}. Getting the dump...")
            chunks = survey.get_dump()
            if chunks is None:
                print("  No dump received. Select another preset to try again.")
                continue
            (OUT_DIR / f"{safe_name(name)}.dump.txt").write_text("\n".join(c.hex() for c in chunks) + "\n")
            print("  Dump saved. Now turn the Drive knob back and forth for 8 seconds...")
            moved = survey.drive_ids(8)
            line = f"{name}: " + (", ".join(f"0x{i:02X} ({lo:.2f}..{hi:.2f})" for i, (lo, hi) in sorted(moved.items())) or "no amp-block id moved")
            print("  " + line)
            with open(OUT_DIR / "summary.txt", "a") as f:
                f.write(line + "\n")
            print("Turn the preset knob to the next preset (Ctrl-C to stop).")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        amp.close()


if __name__ == "__main__":
    main()