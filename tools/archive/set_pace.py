"""(Archived 2026-11-07: answered, see protocol.md section 8. Since Amp.set_raw waits for the amp's answer, the answer no longer reaches listeners, so this tool's answer counts read 0.)

Why did sets stop working in amp_survey? (protocol.md section 8, "Two sets in a row")

Usage (from the project root, on the Pi, amp on, nothing else using it):
    python3 -m tools.set_pace

No guitar needed and no questions: it reads each set back from the dump. Keep your
hands off the knobs. It takes 3 to 4 minutes, most of it handshakes.

Everything happens on Chime 1: Class-A (preset 4), whose Drive is id 0x25, stored at
offset 1028 of the unpacked dump (section 3). A "probe" is one Drive set, then a wait
for the amp's 29-byte answer, then a dump: did the value arrive?

  1. control      two sets, each after the previous one's answer: both should work
  2. back-to-back two sets with no wait, then probes: after a short wait, after 5 s,
                  after a preset select, after a dump. Which (if any) brings sets back?
  3. unused id    one set of Drive (alt), 0x26, which Chime doesn't use, on its own,
                  then a probe: does an unused id alone break sets?

Each case starts with a new handshake (sets come back after one). Results go to
captures/set_pace.txt (a new file each run), raw messages included.
"""
import struct
import threading
import time
from pathlib import Path

from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.protocol.parameters import BY_NAME
from spiderweb.protocol.messages import is_set_answer
from tools.dump_params import dump_data

DRIVE, DRIVE_ALT = BY_NAME["drive"], BY_NAME["drive (alt)"]
PRESET, DRIVE_AT = 4, 1028
WAIT_ANSWER = 1.0
TOLERANCE = 0.005


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    path, n = folder / "set_pace.txt", 1
    while path.exists():
        n += 1
        path = folder / f"set_pace_{n}.txt"
    return path


class SetPace:
    def __init__(self, log_file):
        self.log_file = log_file
        self.lock = threading.Lock()
        self.arrived = threading.Condition()
        self.answers = []
        self.amp = None
        self.results = []

    def write(self, text, show=True):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        with self.lock:
            self.log_file.write(line + "\n")
            self.log_file.flush()
        if show:
            print(line, flush=True)

    def on_raw(self, msg):
        self.write(f"raw {len(msg):3} {msg.hex()}", show=False)
        if is_set_answer(msg):
            with self.arrived:
                self.answers.append(time.time())
                self.arrived.notify_all()

    def answers_since(self, since, timeout=0.0):
        """ How many set answers arrived after `since`, waiting up to `timeout` for the first. """
        with self.arrived:
            self.arrived.wait_for(lambda: any(t >= since for t in self.answers), timeout)
            return sum(t >= since for t in self.answers)

    def result(self, case, detail):
        self.results.append((case, detail))
        self.write(f"RESULT {case}: {detail}")

    # --- amp actions --------------------------------------------------------

    def fresh_connection(self):
        if self.amp is not None:
            self.amp.close()
            time.sleep(1.0)
        self.write("handshake (about 15 s)...")
        self.amp = Amp(Connection(load_handshake()))
        self.amp.add_listener(self.on_raw)
        self.amp.connect()
        name = self.amp.select_preset(PRESET).name()
        self.write(f"loaded {name!r}; Drive reads {self.drive():.3f}")

    def drive(self):
        return struct.unpack_from("<f", dump_data(self.amp.request_dump()), DRIVE_AT)[0]

    def probe(self, case, value):
        """ One set, wait for its answer, then read it back. Returns True if it arrived. """
        since = time.time()
        self.amp.set_parameter(DRIVE, value)
        answered = self.answers_since(since, WAIT_ANSWER)
        time.sleep(0.3)
        got = self.drive()
        ok = abs(got - value) < TOLERANCE
        self.result(case, f"set {value}: {answered} answer(s), dump reads {got:.3f} -> "
                    f"{'WORKED' if ok else 'did not arrive'}")
        return ok

    # --- the cases ----------------------------------------------------------

    def case_control(self):
        self.fresh_connection()
        self.probe("1 control, first", 0.2)
        self.probe("1 control, second", 0.8)

    def case_back_to_back(self):
        self.fresh_connection()
        since = time.time()
        self.amp.set_parameter(DRIVE, 0.3)
        self.amp.set_parameter(DRIVE, 0.7)
        time.sleep(1.5)
        got = self.drive()
        self.result("2 back-to-back", f"sent 0.3 then 0.7 with no wait: {self.answers_since(since)} "
                    f"answer(s), dump reads {got:.3f}")
        if self.probe("2 probe after 1 s", 0.5):
            return
        time.sleep(5.0)
        if self.probe("2 probe after 5 s more", 0.6):
            return
        self.amp.select_preset(PRESET)
        if self.probe("2 probe after a preset select", 0.4):
            return
        self.drive()
        self.probe("2 probe after a dump", 0.55)

    def case_unused_id(self):
        self.fresh_connection()
        since = time.time()
        self.amp.set_parameter(DRIVE_ALT, 0.5)
        answered = self.answers_since(since, WAIT_ANSWER)
        time.sleep(0.5)
        self.result("3 unused id", f"Drive (alt) 0.5 alone: {answered} answer(s), Drive reads {self.drive():.3f}")
        self.probe("3 probe after it", 0.25)

    def run(self):
        print(__doc__)
        input("Hands off the knobs, then press Enter. ")
        try:
            for case in (self.case_control, self.case_back_to_back, self.case_unused_id):
                try:
                    case()
                except Exception as e:
                    self.write(f"{case.__name__} stopped by {type(e).__name__}: {e}")
        except KeyboardInterrupt:
            self.write("stopped with Ctrl-C")
        finally:
            if self.amp is not None:
                self.amp.close()
            print("\n=== summary ===")
            for case, detail in self.results:
                self.write(f"{case}: {detail}")


def main():
    path = output_path()
    with open(path, "x") as log_file:
        SetPace(log_file).run()
    print(f"\nSaved to {path}. Turn the preset knob to reload a clean preset.")


if __name__ == "__main__":
    main()
