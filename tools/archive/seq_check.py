"""(Archived 2026-11-07: answered, see protocol.md section 8. Since Amp.set_raw waits for the amp's answer, the answer no longer reaches listeners, so this tool's answer counts read 0.)

Does a set work only when its sequence number follows the amp's own counter?

Usage (from the project root, on the Pi, amp on, guitar plugged in):
    python3 -m tools.seq_check

Why: in check_amp on 2026-11-06 both Drive sets failed (no report, nothing heard).
The amp's own channel-0 messages after that handshake were numbered 0x08 to 0x0B,
not from 0x0C as in a fresh session (protocol.md section 2), so the Pi's fixed
start at 0x0C may have been ahead of the amp.

It connects once, shows the last channel-0 counter in the handshake replies, then
sets Drive three times and waits for the amp's report of each:
  1. seq 0x0C, the fixed start Amp uses now
  2. seq = the amp's last counter + 1
  3. the next seq after that (does it stay in step?)
Strum while each one runs; it asks what you heard. Everything, raw messages and
the seq of every set, goes to captures/seq_check.txt (a new file each run).
Only Drive changes; nothing is saved on the amp.
"""
import threading
import time
from pathlib import Path

from silkline.amp import Amp, load_handshake
from silkline.connection import Connection
from silkline.protocol.messages import FIRST_SEQUENCE, HEADER, MessageKind, classify
from silkline.protocol.parameters import BY_NAME

DRIVE = BY_NAME["drive"]
DRIVE_KEYS = {(0x2A, 0x25, 0), (0x2A, 0x26, 0)}    # Drive and Drive (alt), as in check_amp
WAIT_REPORT = 2.0


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    path, n = folder / "seq_check.txt", 1
    while path.exists():
        n += 1
        path = folder / f"seq_check_{n}.txt"
    return path


def channel0_counters(messages):
    """ msg[8] of every channel-0 Line 6 message, in order. """
    return [m[8] for m in messages if len(m) > 8 and m[:7] == HEADER and m[7] == 0]


class SeqCheck:
    def __init__(self, log_file):
        self.log_file = log_file
        self.lock = threading.Lock()
        self.arrived = threading.Condition()
        self.drive_reports = []
        self.amp = Amp(Connection(load_handshake()))
        self.amp.add_listener(self.on_raw)
        self.amp.on_lost(lambda error: self.write(f"LOST the amp: {error!r}"))

    def write(self, text, show=True):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        with self.lock:
            self.log_file.write(line + "\n")
            self.log_file.flush()
        if show:
            print(line, flush=True)

    def on_raw(self, msg):
        result = classify(msg)
        counter = f"ch{msg[7]} #{msg[8]:#04x}" if len(msg) > 8 else ""
        self.write(f"raw {len(msg):3} {counter} {result[0].value:13} {msg.hex()}", show=False)
        if result[0] == MessageKind.PARAM and result[1] in DRIVE_KEYS:
            with self.arrived:
                self.drive_reports.append((time.time(), result[2]))
                self.arrived.notify_all()
        elif result[0] != MessageKind.PARAM:
            self.write(f"  amp sent {len(msg)} bytes, {counter}, {result[0].value}")

    def wait_for_report(self, since):
        def found():
            return next((value for t, value in self.drive_reports if t >= since), None)
        with self.arrived:
            self.arrived.wait_for(lambda: found() is not None, WAIT_REPORT)
            return found()

    def trial(self, label, seq, value):
        input(f"\n{label}: Drive to {value} with seq {seq:#04x}. Start strumming, then press Enter. ")
        self.amp._seq = seq          # an experiment: Amp has no public way to choose the seq
        since = time.time()
        self.amp.set_parameter(DRIVE, value)
        self.write(f"sent Drive {value}: begin seq {seq:#04x}, set seq {(seq + 1) % 128:#04x}")
        report = self.wait_for_report(since)
        if report is None:
            self.write(f"RESULT {label}: no Drive report within {WAIT_REPORT}s")
        else:
            self.write(f"RESULT {label}: amp reported {report:.3f} after {time.time() - since:.2f}s")
        time.sleep(1.0)
        heard = input("Did the drive change? (y/n) ").strip().lower()
        self.write(f"RESULT {label} by ear: {heard!r}")
        return report is not None

    def run(self):
        print(__doc__)
        self.write("connecting (about 15 s)...")
        groups = self.amp.connect()
        replies = [m for group in groups for m in group]
        counters = channel0_counters(replies)
        if not counters:
            self.write("no channel-0 messages in the handshake replies; stopping")
            return
        last = counters[-1]
        self.write(f"handshake: {len(replies)} replies; last channel-0 counters "
                   f"{[hex(c) for c in counters[-6:]]}; a fresh session ends at 0x0b")
        follow = (last + 1) % 128
        self.trial("1 fixed", FIRST_SEQUENCE, 0.2)
        self.trial("2 follow", follow, 0.8)
        self.trial("3 next", self.amp._seq, 0.4)


def main():
    path = output_path()
    with open(path, "x") as log_file:
        checker = SeqCheck(log_file)
        try:
            checker.run()
        except KeyboardInterrupt:
            checker.write("stopped with Ctrl-C")
        finally:
            checker.amp.close()
    print(f"\nSaved to {path}.")


if __name__ == "__main__":
    main()
