"""(Archived 2026-11-07: done; results in protocol.md sections 8, 9 and 11.)

The real-amp questions still open on 2026-11-07, in one guided run.

Usage (from the project root, on the Pi, amp on, guitar plugged in):
    python3 -m tools.amp_survey

Press Enter to start each step, or type s and Enter to skip it.

  1. drive      send Drive as both ids (0x25 and 0x26) at once, on Chime (preset 4)
                and Jungle $lash (8): does it work on both, by ear and in the dump?
  2. presets    select 115 to 123 (the names only the short list has): can they load?
  3. knob       turn the preset knob to each marking 1 to 16: the reported position
                and the preset name for each (protocol.md section 11)
  4. replug     pull the USB cable while connected, then plug it back in: how long
                until it's noticed, until the device is back, and until a new
                handshake works (for phase 6, reconnect)
  5. power      switch the amp off while connected, then on again: the same timings

Everything (each step, every event, every raw message) goes to
captures/amp_survey.txt (a new file each run). Only the edit buffer changes; nothing
is saved on the amp.
"""
import struct
import threading
import time
from pathlib import Path

from spiderweb.amp import Amp, load_handshake
from spiderweb.connection import Connection
from spiderweb.errors import AmpError
from spiderweb.protocol.parameters import BY_NAME
from spiderweb.service import AmpService, ConnectionState, EventType
from spiderweb.transport import find_device
from tools.dump_params import dump_data

DRIVES = (BY_NAME["drive"], BY_NAME["drive (alt)"])
DRIVE_PRESETS = ((4, 1028), (8, 1037))     # preset, where its Drive is in the dump (protocol.md section 3)
WAIT_LOST = 30.0
WAIT_DEVICE = 60.0
START_TRIES = 5


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    path, n = folder / "amp_survey.txt", 1
    while path.exists():
        n += 1
        path = folder / f"amp_survey_{n}.txt"
    return path


class Survey:
    def __init__(self, log_file):
        self.log_file = log_file
        self.log_lock = threading.Lock()
        self.events = []
        self.arrived = threading.Condition()
        self.results = []
        self.service = AmpService(amp_factory=self.make_amp)
        self.service.on_change(self.on_event)

    # --- logging and waiting ------------------------------------------------

    def write(self, text, show=True):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        with self.log_lock:
            self.log_file.write(line + "\n")
            self.log_file.flush()
        if show:
            print(line, flush=True)

    def make_amp(self):
        amp = Amp(Connection(load_handshake()))
        amp.add_listener(lambda msg: self.write(f"raw {len(msg):3} {msg.hex()}", show=False))
        return amp

    def on_event(self, event):
        self.write(f"event {event.event_type.value} {event.data}", show=False)
        with self.arrived:
            self.events.append((time.time(), event))
            self.arrived.notify_all()

    def wait_for(self, check, timeout, since):
        def found():
            return next((e for t, e in self.events if t >= since and check(e)), None)
        with self.arrived:
            self.arrived.wait_for(lambda: found() is not None, timeout)
            return found()

    def last_since(self, event_type, since):
        with self.arrived:
            return next((e for t, e in reversed(self.events) if t >= since and e.event_type == event_type), None)

    def result(self, step, detail):
        self.results.append((step, detail))
        self.write(f"RESULT {step}: {detail}")

    def ask(self, prompt):
        answer = input(f"\n{prompt} ").strip().lower()
        self.write(f"you typed {answer!r} for: {prompt}", show=False)
        return answer

    def go(self, title, instructions):
        print(f"\n=== {title} ===\n{instructions}")
        return self.ask("Press Enter to start (s to skip):") != "s"

    def connected(self):
        return self.service.state().connection == ConnectionState.CONNECTED

    def start(self, label):
        """ start(), retried a few times. Returns seconds taken, or None. """
        began = time.time()
        for attempt in range(1, START_TRIES + 1):
            try:
                self.service.start()
                took = time.time() - began
                state = self.service.state()
                self.result(label, f"connected after {took:.1f}s (attempt {attempt}); preset "
                            f"{state.preset_name!r}; {len(self.service.presets())} preset names")
                return took
            except Exception as e:
                self.write(f"start attempt {attempt} failed: {type(e).__name__}: {e}")
                time.sleep(2.0)
        self.result(label, f"FAILED to connect after {START_TRIES} attempts")
        return None

    # --- the steps ----------------------------------------------------------

    def check_drive(self):
        if not self.go("1. drive", "Loads Chime (4) and Jungle $lash (8). On each, Drive goes to 0.1 then "
                       "0.9, sent as both ids. Strum the whole time."):
            return
        amp = self.service._amp            # a tool: the raw sets and dumps aren't service commands
        for preset, at in DRIVE_PRESETS:
            name = self.service.select_preset(preset)
            for value in (0.1, 0.9):
                for param in DRIVES:
                    amp.set_parameter(param, value)
                time.sleep(1.5)
                data = dump_data(amp.request_dump())
                got = struct.unpack_from("<f", data, at)[0]
                self.result(f"drive {preset} {value}", f"{name!r}: the dump's Drive reads {got:.3f}")
                time.sleep(1.5)
            answer = self.ask(f"On {name!r}, did the drive go clean, then dirty? (y/n)")
            self.result(f"drive {preset} by ear", f"you said {answer!r}")

    def check_presets(self):
        if not self.go("2. presets", "Selects 115 to 123, then 4 again. No need to play."):
            return
        names = self.service.presets()
        for value in list(range(115, 124)) + [4]:
            began = time.time()
            try:
                name = self.service.select_preset(value)
                self.result(f"select {value}", f"loaded {name!r} in {time.time() - began:.2f}s "
                            f"(list: {names.get(value)!r})")
            except AmpError as e:
                self.result(f"select {value}", f"{type(e).__name__}: {e} (list: {names.get(value)!r})")

    def check_knob(self):
        if not self.go("3. knob", "For each marking: turn the preset knob there, wait until the name "
                       "shows here, then press Enter."):
            return
        for marking in range(1, 17):
            since = time.time()
            self.ask(f"Turn the knob to marking {marking}. Enter when the name shows (or now if it's already there):")
            moved = self.last_since(EventType.KNOB_MOVED, since)
            named = self.last_since(EventType.PRESET_CHANGED, since)
            position = moved.data["position"] if moved else None
            name = named.data["name"] if named else self.service.state().preset_name
            print(f"   position {position}, {name!r}")
            self.result(f"knob {marking}", f"reported position {position}, preset {name!r}")

    def wait_for_device(self, label, since):
        while time.time() - since < WAIT_DEVICE:
            try:
                path = find_device()
                self.result(label, f"{path} back {time.time() - since:.1f}s after you pressed Enter")
                return True
            except AmpError:
                time.sleep(0.2)
        self.result(label, f"no device within {WAIT_DEVICE:.0f}s")
        return False

    def check_loss(self, number, title, lose, restore):
        if not self.go(f"{number}. {title}", f"While connected you {lose}, and then {restore}. "
                       "It times when each is noticed and how long a new connection takes."):
            return
        if not self.connected():
            self.start(f"{title} connect first")
        try:
            before = find_device()
        except AmpError:
            before = None
        self.ask(f"Now {lose}, then press Enter straight away.")
        since = time.time()
        lost = self.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                             and e.data["state"] == ConnectionState.DISCONNECTED, WAIT_LOST, since)
        if lost:
            self.result(f"{title} lost", f"noticed {time.time() - since:.1f}s after Enter: {lost.data.get('error')}")
        else:
            self.result(f"{title} lost", f"NOT noticed within {WAIT_LOST:.0f}s")
        self.service.stop()
        self.ask(f"Now {restore}, then press Enter straight away.")
        since = time.time()
        if self.wait_for_device(f"{title} device", since):
            after = find_device()
            self.result(f"{title} path", f"before {before}, after {after}")
            self.start(f"{title} reconnect")

    def run(self):
        print(__doc__)
        try:
            self.start("connect")
            if self.connected():
                self.check_drive()
                self.check_presets()
                self.check_knob()
            self.check_loss(4, "replug", "pull the amp's USB cable out", "plug it back in")
            self.check_loss(5, "power", "switch the amp off (leave the USB in)", "switch it back on")
        except KeyboardInterrupt:
            self.write("stopped with Ctrl-C")
        except Exception as e:
            self.write(f"stopped by {type(e).__name__}: {e}")
            raise
        finally:
            self.service.stop()
            print("\n=== summary ===")
            for step, detail in self.results:
                self.write(f"{step}: {detail}")


def main():
    path = output_path()
    with open(path, "x") as log_file:
        Survey(log_file).run()
    print(f"\nSaved to {path}.")


if __name__ == "__main__":
    main()
