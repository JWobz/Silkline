"""Phase 5: check the whole stack (AmpService -> Amp -> Connection) on the real amp.

Usage (from the project root, on the Pi, amp on, nothing else using it):
    python3 -m tools.check_amp

Turn the amp's Tone and Reverb knobs fully down first (their jitter floods the
log, protocol.md section 7). It uses one connection for every check and walks
you through them; press Enter to start each one, or type s and Enter to skip it.

  1. connect      the preset name read from the handshake's dump
  2. set          Drive (both ids) to 0.2 then 0.8: does each set get answered and
                  recorded, and can you hear it?
  3. select       presets 4 and 8, timed
  4. presets      select values above 20: is the list index the select value?
  5. knob         click the preset knob once: position and the refreshed name
  6. unplug       pull the USB cable: is it noticed, and how fast?

Everything (each step, every event, every raw message) is saved to
captures/check_amp.txt (a new file each run). Only presets are loaded; nothing
is saved on the amp.
"""
import threading
import time
from pathlib import Path

from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.errors import AmpError
from spiderweb.protocol.messages import MessageKind, classify
from spiderweb.service import AmpService, ConnectionState, EventType

DRIVE_KEYS = {(0x2A, 0x25, 0), (0x2A, 0x26, 0)}    # Drive and Drive (alt)
WAIT_KNOB = 30.0       # seconds to wait for a knob click
WAIT_UNPLUG = 30.0     # seconds to wait for the unplug to be noticed
HIGH_VALUES = (21, 60, 114, 115, 124, 127)   # past the 0-20 tried so far; 115-127 only in the short list


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    path = folder / "check_amp.txt"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"check_amp_{n}.txt"
    return path


class Checker:
    def __init__(self, log_file):
        self.log_file = log_file
        self.log_lock = threading.Lock()
        self.events = []
        self.drive_reports = []
        self.arrived = threading.Condition()
        self.results = []
        self.service = AmpService(amp_factory=self.make_amp)
        self.service.on_change(self.on_event)

    # --- logging ------------------------------------------------------------

    def write(self, text, show=True):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        with self.log_lock:
            self.log_file.write(line + "\n")
            self.log_file.flush()
        if show:
            print(line, flush=True)

    def make_amp(self):
        """ The real amp, plus a listener that logs every raw message to the file only. """
        amp = Amp(Connection(load_handshake()))
        amp.add_listener(self.on_raw)
        return amp

    def on_raw(self, msg):
        """ Logs every raw message, and keeps every Drive report (even ones too small to be an event). """
        self.write(f"raw {len(msg):3} {msg.hex()}", show=False)
        result = classify(msg)
        if result[0] == MessageKind.PARAM and result[1] in DRIVE_KEYS:
            with self.arrived:
                self.drive_reports.append((time.time(), result[1], result[2]))
                self.arrived.notify_all()

    def wait_for_drive_report(self, timeout, since):
        """ The first raw Drive report after `since`, as (key, value), or None after `timeout` seconds. """
        def found():
            return next(((key, value) for t, key, value in self.drive_reports if t >= since), None)
        with self.arrived:
            self.arrived.wait_for(lambda: found() is not None, timeout)
            return found()

    def on_event(self, event):
        self.write(f"event {event.event_type.value} {event.data}")
        with self.arrived:
            self.events.append((time.time(), event))
            self.arrived.notify_all()

    def wait_for(self, check, timeout, since):
        """ The first event after `since` that passes check, or None after `timeout` seconds. """
        def found():
            return next((e for t, e in self.events if t >= since and check(e)), None)
        with self.arrived:
            self.arrived.wait_for(lambda: found() is not None, timeout)
            return found()

    def result(self, step, outcome, detail):
        self.results.append((step, outcome, detail))
        self.write(f"RESULT {step}: {outcome} - {detail}")

    def ask(self, prompt):
        answer = input(f"\n{prompt} ").strip().lower()
        self.write(f"you typed {answer!r} for: {prompt}", show=False)
        return answer

    def go(self, title, instructions):
        print(f"\n=== {title} ===\n{instructions}")
        return self.ask("Press Enter to start (s to skip):") != "s"

    # --- the checks ---------------------------------------------------------

    def check_connect(self):
        start = time.time()
        self.service.start()
        took = time.time() - start
        state = self.service.state()
        if state.preset_name:
            self.result("connect", "PASS", f"connected in {took:.1f}s, preset {state.preset_name!r} from the handshake dump")
        else:
            self.result("connect", "CHECK", f"connected in {took:.1f}s, but the handshake had no complete dump")
        # The amp has no display, so only the knob position can be checked by hand (section 11).
        answer = self.ask("Which position (1-16) is the preset knob at?")
        self.result("connect knob", "INFO", f"{state.preset_name!r} loaded with the knob at {answer!r}")
        presets = self.service.presets()
        missing = [i for i in range(128) if i not in presets]
        if missing:
            self.result("preset list", "CHECK", f"{len(presets)} names from the handshake; missing {missing}")
        else:
            self.result("preset list", "PASS", f"all 128 names: 0 {presets[0]!r}, 20 {presets[20]!r}, 124 {presets[124]!r}")

    def check_set(self):
        if not self.go("2. set", "Plays Drive at 0.2, then 0.8. Strum while it runs and listen for the change."):
            return
        for value in (0.2, 0.8):
            # Both Drive ids: each preset uses one, and the other is harmless (protocol.md
            # section 8). set() waits for the amp's answer, so this also checks the pacing.
            for name in ("drive", "drive (alt)"):
                since = time.time()
                try:
                    self.service.set(name, value)
                except AmpError as e:
                    self.result(f"set {name} {value}", "FAIL", f"{type(e).__name__}: {e}")
                    continue
                self.result(f"set {name} {value}", "PASS", f"answered after {time.time() - since:.2f}s")
                got = self.service.get(name)
                self.result(f"get {name} {value}", "PASS" if got == value else "FAIL", f"service.get = {got}")
            # The amp doesn't report a set back (protocol.md section 8), so a report would be news.
            report = self.wait_for_drive_report(1.0, since)
            if report is not None:
                self.result(f"report {value}", "INFO", f"the amp did report {report[1]:.3f} for {report[0]}")
            time.sleep(2.0)
        answer = self.ask("Did you hear the drive change both times? (y/n)")
        self.result("set by ear", "PASS" if answer == "y" else "FAIL", f"you said {answer!r}")

    def check_select(self):
        if not self.go("3. select", "Loads preset 4 (Chime 1: Class-A), then 8 (Jungle $lash). Strum and listen."):
            return
        for value, expected in ((4, "Chime 1: Class-A"), (8, "Jungle $lash")):
            start = time.time()
            try:
                name = self.service.select_preset(value)
            except AmpError as e:
                self.result(f"select {value}", "FAIL", f"{type(e).__name__}: {e}")
                continue
            took = time.time() - start
            self.result(f"select {value}", "PASS" if name == expected else "CHECK",
                        f"{name!r} in {took:.2f}s (expected {expected!r})")
            time.sleep(2.0)
        answer = self.ask("Did the sound change both times? (y/n)")
        self.result("select by ear", "PASS" if answer == "y" else "FAIL", f"you said {answer!r}")

    def check_presets(self):
        presets = self.service.presets()
        values = [v for v in HIGH_VALUES if v in presets]
        if not values:
            self.result("presets", "FAIL", "no preset list from the handshake to check against")
            return
        listing = ", ".join(f"{v} {presets[v]!r}" for v in values)
        if not self.go("4. presets", f"Loads {listing}, one every 3 seconds. Strum and listen."):
            return
        for value in values:
            try:
                name = self.service.select_preset(value)
            except AmpError as e:
                self.result(f"preset {value}", "FAIL", f"{type(e).__name__}: {e}")
                continue
            self.result(f"preset {value}", "PASS" if name == presets[value] else "FAIL",
                        f"loaded {name!r}, the list says {presets[value]!r}")
            time.sleep(3.0)
        answer = self.ask("Did the sound change with each one? (y/n)")
        self.result("presets by ear", "PASS" if answer == "y" else "FAIL", f"you said {answer!r}")

    def check_knob(self):
        if not self.go("5. knob", f"After Enter, click the preset knob ONE position and leave it ({WAIT_KNOB:.0f}s to do it)."):
            return
        since = time.time()
        moved = self.wait_for(lambda e: e.event_type == EventType.KNOB_MOVED, WAIT_KNOB, since)
        if moved is None:
            self.result("knob", "FAIL", f"no KNOB_MOVED within {WAIT_KNOB:.0f}s")
            return
        self.result("knob position", "PASS", f"settled at position {moved.data['position']}")
        named = self.wait_for(lambda e: e.event_type == EventType.PRESET_CHANGED
                              and e.data["number"] is None, 6.0, since)
        if named is None:
            self.result("knob name", "FAIL", "no refreshed name within 6s of the click")
            return
        self.result("knob name", "PASS", f"refreshed to {named.data['name']!r}")
        answer = self.ask("Which position (1-16) is the preset knob at now?")
        self.result("knob by hand", "INFO", f"reported position {moved.data['position']} (0-15), "
                    f"you said {answer!r}, name {named.data['name']!r}")

    def check_unplug(self):
        if not self.go("6. unplug", f"After Enter, pull the amp's USB cable out of the Pi ({WAIT_UNPLUG:.0f}s to do it)."):
            return
        since = time.time()
        lost = self.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                             and e.data["state"] == ConnectionState.DISCONNECTED, WAIT_UNPLUG, since)
        if lost is None:
            self.result("unplug", "FAIL", f"not noticed within {WAIT_UNPLUG:.0f}s "
                        "(read() may be getting empty bytes instead of an error)")
        else:
            self.result("unplug", "PASS", f"noticed: {lost.data.get('error')}")
        try:
            self.service.set("drive", 0.5)
            self.result("command after unplug", "FAIL", "set() didn't raise")
        except AmpError as e:
            self.result("command after unplug", "PASS", f"{type(e).__name__}: {e}")

    def run(self):
        print(__doc__)
        try:
            self.check_connect()
            self.check_set()
            self.check_select()
            self.check_presets()
            self.check_knob()
            self.check_unplug()
        except KeyboardInterrupt:
            self.write("stopped with Ctrl-C")
        except Exception as e:
            self.write(f"stopped by {type(e).__name__}: {e}")
            raise
        finally:
            self.service.stop()
            print("\n=== summary ===")
            for step, outcome, detail in self.results:
                self.write(f"{outcome:5} {step}: {detail}")


def main():
    path = output_path()
    with open(path, "x") as log_file:
        Checker(log_file).run()
    print(f"\nSaved to {path}. Plug the amp back in; power-cycle it before the next run.")


if __name__ == "__main__":
    main()
