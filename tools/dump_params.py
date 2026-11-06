"""Where is each parameter stored in the preset dump? (protocol.md section 3)

Usage (from the project root, on the Pi, amp on, nothing else using it):
    python3 -m tools.dump_params

Turn the amp's master volume down and keep your hands off its knobs while it runs
(knob moves change the dump too). No guitar needed. It takes about 2 minutes.

For each preset in PRESETS it:
  1. selects the preset and takes two dumps, to see which bytes change on their own
  2. for each parameter in PARAMS: sets it to 0.5, takes a dump, sets it to 0.75,
     takes another dump
  3. looks for the place in the dump that went from 0.5 to 0.75

Offsets are into the unpacked data of the five 309-byte chunks (protocol.md section 3:
top bits most significant first). The amp stores a set value a little high (0.5 as
0.502), so values are matched within 0.005.

Everything goes to captures/dump_params.txt (a new file each run): every dump as hex,
the bytes each set changed, and a summary. Only the edit buffer changes; nothing is
saved on the amp. Turn the preset knob afterwards to reload a clean preset.

Bits mode, to work out the 7-bit packing (protocol.md section 3):
    python3 -m tools.dump_params bits
sets 0.5 then 1.0 instead. 1.0 is 3f800000, so only one top bit should change between
the two dumps, and the raw diff shows which bit of which byte carries it. It goes to
captures/dump_bits.txt.
"""
import struct
import sys
import time
from pathlib import Path

from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.errors import AmpError
from spiderweb.protocol.dump import DUMP_CHUNK_LENGTH
from spiderweb.protocol.parameters import BY_NAME


def unpack(msg):
    """ The dump's 7-bit packing (protocol.md section 3): in each group of 8 from msg[12],
    the first byte holds the top bits, most significant first (data byte k takes 0x40 >> k). """
    body, out = msg[12:-1], bytearray()
    for g in range(0, len(body), 8):
        group = body[g:g + 8]
        for k, b in enumerate(group[1:]):
            out.append(b | (0x80 if group[0] & (0x40 >> k) else 0))
    return bytes(out)

PRESETS = (4, 8, 0, 14)          # Chime 1: Class-A, Jungle $lash, Bass, Ambient 1: Black Hole
PARAMS = ("drive", "drive (alt)", "volume", "reverb", "reverb (mix)", "fx1", "fx knob (fx1)")
BITS = "bits" in sys.argv[1:]
LOW, HIGH = (0.5, 1.0) if BITS else (0.5, 0.75)
TOLERANCE = 0.005
SETTLE = 0.5                     # seconds between a set and the dump that should show it


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    stem = "dump_bits" if BITS else "dump_params"
    path, n = folder / f"{stem}.txt", 1
    while path.exists():
        n += 1
        path = folder / f"{stem}_{n}.txt"
    return path


def raw_diffs(low_dump, high_dump):
    """ Every raw byte that differs between two dumps: "chunk 3 msg[245] top 00->02".

    "top" marks a group's first byte (msg[12 + 8n]), "data" the others.
    """
    out = []
    for a, b in zip(low_dump.chunks, high_dump.chunks):
        for j in range(min(len(a), len(b))):
            if a[j] != b[j]:
                kind = "top" if j >= 12 and (j - 12) % 8 == 0 else "data"
                out.append(f"chunk {a[9]} msg[{j}] {kind} {a[j]:02x}->{b[j]:02x}")
    return out


def dump_data(dump):
    """ The unpacked data of a dump's full-size chunks, joined (5 x 259 bytes for a whole dump). """
    return b"".join(unpack(chunk) for chunk in dump.chunks if len(chunk) == DUMP_CHUNK_LENGTH)


def changed(a, b):
    """ Offsets where two dumps' data differ. """
    return {i for i in range(min(len(a), len(b))) if a[i] != b[i]}


def ranges(offsets):
    """ [3, 4, 5, 9] -> "3-5, 9" """
    out, run = [], []
    for o in sorted(offsets):
        if run and o != run[-1] + 1:
            out.append(run)
            run = []
        run.append(o)
    if run:
        out.append(run)
    return ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else str(r[0]) for r in out) or "none"


def matches(low, high):
    """ Offsets holding LOW in the first dump and HIGH in the second, as floats.

    The amp stores a set value a little high (0.5 as 0.502, protocol.md section 3),
    so they're compared with a tolerance.
    """
    def near(data, o, value):
        return abs(struct.unpack_from("<f", data, o)[0] - value) < TOLERANCE
    return [o for o in range(min(len(low), len(high)) - 3)
            if near(low, o, LOW) and near(high, o, HIGH)]


class DumpParams:
    def __init__(self, log_file):
        self.log_file = log_file
        self.amp = Amp(Connection(load_handshake()))
        self.amp.on_lost(lambda error: self.write(f"LOST the amp: {error!r}"))
        self.summary = []

    def write(self, text, show=True):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        self.log_file.write(line + "\n")
        self.log_file.flush()
        if show:
            print(line, flush=True)

    def log_dump(self, label, dump):
        self.write(f"dump {label}: {dump.name()!r}, {len(dump.chunks)} chunks", show=False)
        for chunk in dump.chunks:
            self.write(f"  chunk {chunk[9]} {len(chunk)} {chunk.hex()}", show=False)

    def take_dump(self, label):
        dump = self.amp.request_dump()
        self.log_dump(label, dump)
        return dump

    def check_param(self, preset, name, noise):
        param = BY_NAME[name]
        self.amp.set_parameter(param, LOW)
        time.sleep(SETTLE)
        low_dump = self.take_dump(f"{preset} {name} {LOW}")
        self.amp.set_parameter(param, HIGH)
        time.sleep(SETTLE)
        high_dump = self.take_dump(f"{preset} {name} {HIGH}")
        if BITS:
            diffs = raw_diffs(low_dump, high_dump)
            self.write(f"  {param.name:14} raw diff: {'; '.join(diffs) if diffs else 'none'}")
        low, high = dump_data(low_dump), dump_data(high_dump)
        found = matches(low, high)
        moved = changed(low, high) - noise
        if found:
            records = ", ".join(f"{o} (6 bytes before: {low[o - 6:o].hex()})" for o in found)
            self.write(f"  {param.name:14} FOUND at {records}")
        else:
            self.write(f"  {param.name:14} not found; bytes that changed: {ranges(moved)}")
        self.summary.append((preset, param.name, found, ranges(moved)))

    def check_preset(self, value):
        try:
            dump = self.amp.select_preset(value)
        except AmpError as e:
            self.write(f"preset {value}: select failed ({type(e).__name__}: {e}); skipping")
            return
        self.log_dump(f"{value} selected", dump)
        self.write(f"\npreset {value}: {dump.name()!r}")
        first = dump_data(dump)
        noise = changed(first, dump_data(self.take_dump(f"{value} again")))
        self.write(f"  changed by themselves between two dumps: {ranges(noise)}")
        for name in PARAMS:
            try:
                self.check_param(value, name, noise)
            except AmpError as e:
                self.write(f"  {name}: {type(e).__name__}: {e}")

    def run(self):
        print(__doc__)
        input("Volume down, hands off the knobs, then press Enter. ")
        self.write("connecting (about 15 s)...")
        self.amp.connect()
        for value in PRESETS:
            self.check_preset(value)
        self.write("\n=== summary: offset of each parameter's value, per preset ===")
        for preset, name, found, moved in self.summary:
            self.write(f"preset {preset:3} {name:14} {found if found else 'not found (changed: ' + moved + ')'}")


def main():
    path = output_path()
    with open(path, "x") as log_file:
        checker = DumpParams(log_file)
        try:
            checker.run()
        except KeyboardInterrupt:
            checker.write("stopped with Ctrl-C")
        finally:
            checker.amp.close()
    print(f"\nSaved to {path}. Turn the preset knob to reload a clean preset.")


if __name__ == "__main__":
    main()
