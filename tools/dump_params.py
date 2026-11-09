"""Where is each parameter stored in the preset dump? (protocol.md section 3)

Usage (from the project root, on the Pi, amp on, nothing else using it):
    python3 -m tools.dump_params

Turn the amp's master volume down and keep your hands off its knobs while it runs
(knob moves change the dump too). No guitar needed. It takes about 2 minutes.

For each preset in PRESETS it:
  1. selects the preset and takes two dumps, to see which bytes change on their own
  2. for each parameter in PARAMS: sets it to 0.5, takes a dump, sets it to 0.75
     (0 then 1 for an on/off; halfway then three quarters for other ranges),
     takes another dump
  3. looks for the record in the dump that went from 0.5 to 0.75

Records are named block/id, e.g. "2A:0/1f" (the amp block's Drive), from the dump's
layout in protocol.md section 3. The amp stores a set value a little high (0.5 as
0.502), so values are matched within 0.005.

Everything goes to captures/dump_params.txt (a new file each run): every dump as hex,
the bytes each set changed, and a summary. Only the edit buffer changes; nothing is
saved on the amp. Turn the preset knob afterwards to reload a clean preset.

Other parameters: name them after the command, by name or as block:id:sub in hex
(for ones not in parameters.py), for example
    python3 -m tools.dump_params "mod on" "delay on" "mod knob" 2a:27:0

New mode, for every settable parameter that DUMP_RECORDS doesn't map yet, on the
first two presets only (about 5 minutes):
    python3 -m tools.dump_params new
It sets each stage's on/off too, so stages switch on and off while it runs.

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

from silkline.amp import Amp, load_handshake
from silkline.connection import Connection
from silkline.errors import AmpError
from silkline.protocol.dump import DUMP_CHUNK_LENGTH
from silkline.protocol.packing import unpack
from silkline.protocol.parameters import BY_NAME, DUMP_RECORDS, PARAMETERS, Parameter

PRESETS = (4, 8, 0, 14)          # Chime 1: Class-A, Jungle $lash, Bass, Ambient 1: Black Hole
DEFAULT_PARAMS = ("gain", "drive", "volume", "reverb", "reverb mix", "stomp on", "stomp knob")


def parameter(spec):
    """ A Parameter from a name in parameters.py, or from "block:id:sub" in hex (e.g. 2a:27:0). """
    if spec.lower() in BY_NAME:
        return BY_NAME[spec.lower()]
    parts = spec.split(":")
    if len(parts) == 3:
        block, param_id, sub = (int(p, 16) for p in parts)
        return Parameter(spec.upper(), block, sub, param_id, sub, settable=True)    # namespace = sub
    raise SystemExit(f"unknown parameter {spec!r}: use a name from parameters.py or block:id:sub (the namespace is taken as sub)")


def not_mapped_yet():
    """ Every settable parameter whose dump record isn't in DUMP_RECORDS yet ("new" mode). """
    mapped = set(DUMP_RECORDS.values())
    return [p for p in PARAMETERS if p.settable and p.key not in mapped]


def test_values(param):
    """ The two values to set, and how close the dump must be: 0 then 1 for a switch,
    halfway then three quarters of the way through a float's range (0.5 and 0.75 for
    0 to 1), and 0.5 then 1.0 in bits mode. """
    if BITS:
        return 0.5, 1.0, TOLERANCE
    if param.kind == "switch":
        return 0, 1, 0.5
    span = param.high - param.low
    return param.low + 0.5 * span, param.low + 0.75 * span, TOLERANCE * max(1.0, span)


ARGS = [a for a in sys.argv[1:] if a not in ("bits", "new")]
if "new" in sys.argv[1:]:
    PARAMS = not_mapped_yet()
    PRESETS = PRESETS[:2]        # Chime and Jungle $lash: enough to confirm, half the time
else:
    PARAMS = [parameter(a) for a in (ARGS or DEFAULT_PARAMS)]
BITS = "bits" in sys.argv[1:]

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
    """ The old 259-bytes-per-chunk view (5 x 259 bytes), whose offsets the archived
    tools and protocol.md's offset table use. New code wants dump_stream(). """
    return b"".join(unpack(chunk) for chunk in dump.chunks if len(chunk) == DUMP_CHUNK_LENGTH)


def dump_stream(dump):
    """ The dump's data as protocol.md section 3 lays it out: each full chunk unpacked,
    its first 256 bytes kept (the last 3 are padding), joined. """
    return b"".join(unpack(chunk)[:256] for chunk in dump.chunks if len(chunk) == DUMP_CHUNK_LENGTH)


def records(dump):
    """ Every parameter record in a dump, as {"BB:s/rr": (type, value)}, e.g. "2A:0/1f".

    Blocks are 3 info records (03 block, 05 kind, 06 count) and then `count` 10-byte
    parameter records (protocol.md section 3). Reads dump.data(), the whole dump: the
    short last chunk holds the EQ's last records, which dump_stream() leaves out.
    """
    d, out, o = dump.data(), {}, 0
    while o + 30 <= len(d):
        info = [d[o + 10 * i:o + 10 * i + 10] for i in range(3)]
        if not all(r[0] == n and r[3] == 0x80 for r, n in zip(info, (3, 5, 6))):
            o += 1
            continue
        block = int.from_bytes(info[0][6:10], "little")
        count = int.from_bytes(info[2][6:10], "little")
        o += 30
        for _ in range(count):
            r = d[o:o + 10]
            if len(r) < 10 or r[4] not in (1, 2, 3):
                break
            raw = r[6:10]
            value = struct.unpack("<f", raw)[0] if r[4] == 3 else int.from_bytes(raw, "little")
            out[f"{block & 0xFF:02X}:{block >> 8:x}/{r[0]:02x}"] = (r[4], value)
            o += 10
    return out


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

    def check_param(self, preset, param, noise):
        name = param.name.lower()        # the label used in the log
        low, high, tolerance = test_values(param)
        self.amp.set_parameter(param, low)
        time.sleep(SETTLE)
        low_dump = self.take_dump(f"{preset} {name} {low}")
        self.amp.set_parameter(param, high)
        time.sleep(SETTLE)
        high_dump = self.take_dump(f"{preset} {name} {high}")
        if BITS:
            diffs = raw_diffs(low_dump, high_dump)
            self.write(f"  {param.name:14} raw diff: {'; '.join(diffs) if diffs else 'none'}")
        before, after = records(low_dump), records(high_dump)
        wanted_type = (1, 2) if param.kind == "switch" else (3,)
        found = [key for key, (typ, value) in after.items()
                 if typ in wanted_type and key in before and abs(before[key][1] - low) < tolerance
                 and abs(value - high) < tolerance]
        moved = [key for key in after if before.get(key) != after[key]]
        if found:
            self.write(f"  {param.name:14} FOUND as record {', '.join(found)}")
        else:
            changes = [f"{key} (type {after[key][0]}: {before.get(key, (None, None))[1]} -> {after[key][1]})"
                       for key in moved]
            self.write(f"  {param.name:14} not found; records that changed: {', '.join(changes) or 'none'}")
        self.summary.append((preset, param.name, found, ", ".join(moved) or "none"))

    def check_preset(self, value):
        try:
            dump = self.amp.select_preset(value)
        except AmpError as e:
            self.write(f"preset {value}: select failed ({type(e).__name__}: {e}); skipping")
            return
        self.log_dump(f"{value} selected", dump)
        self.write(f"\npreset {value}: {dump.name()!r}")
        first, again = records(dump), records(self.take_dump(f"{value} again"))
        noise = [key for key in again if first.get(key) != again[key]]
        self.write(f"  {len(first)} records; changed by themselves between two dumps: {', '.join(noise) or 'none'}")
        for param in PARAMS:
            try:
                self.check_param(value, param, noise)
            except AmpError as e:
                self.write(f"  {param.name}: {type(e).__name__}: {e}")

    def run(self):
        print(__doc__)
        input("Volume down, hands off the knobs, then press Enter. ")
        self.write("connecting (about 15 s)...")
        self.amp.connect()
        for value in PRESETS:
            self.check_preset(value)
        self.write("\n=== summary: the record holding each parameter's value, per preset ===")
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
