"""The last real-amp checks before calling the API finished (2026-11-07; step 3 dropped 2026-11-09).

Usage (from the project root, on the Pi, amp on, nothing else using the amp; no
guitar needed, and nothing is judged by ear: every check reads the amp's dump):
    python3 -m tools.finish_check

Press Enter to start each step, or type s and Enter to skip it. About 5 minutes.

  1. connect    AmpService.keep_connected(): connects, with values from the dump
  2. sliders    set_latest() in a burst on Chime and on Jungle $lash: the newest value
                reaches the amp (read back from the dump), and "drive" picks the
                preset's Drive id
  3. replug     pull the USB cable, plug it back in: keep_connected() should reconnect
                by itself, with the preset names, and sets should work again
  4. power      the same, switching the amp off and on (the preset list comes late)

Everything goes to captures/finish_check.txt (a new file each run), raw messages
included. Only the edit buffer changes; nothing is saved on the amp. Turn the preset
knob afterwards to reload a clean preset.
"""
import threading
import time
from pathlib import Path

from silkline.amp import Amp, load_handshake
from silkline.connection import Connection
from silkline.errors import AmpError
from silkline.service import AmpService, ConnectionState, EventType
from tools.dump_params import records

CHIME, JUNGLE = 4, 8
BURST = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
DRIVE_KEYS = {(0x2A, 0x25, 0), (0x2A, 0x26, 0)}    # Gain and Drive
WAIT_CONNECTED = 90.0           # seconds for keep_connected() to come back (power-on can take a few tries)


def output_path():
    folder = Path("captures")
    folder.mkdir(exist_ok=True)
    path, n = folder / "finish_check.txt", 1
    while path.exists():
        n += 1
        path = folder / f"finish_check_{n}.txt"
    return path


class FinishCheck:
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

    def changes_since(self, since, key):
        with self.arrived:
            return [e.data["value"] for t, e in self.events
                    if t >= since and e.event_type == EventType.PARAMETER_CHANGED and e.data["key"] == key]

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

    def connected(self):
        return self.service.state().connection == ConnectionState.CONNECTED

    def wait_connected(self, since, timeout=WAIT_CONNECTED):
        return self.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                             and e.data["state"] == ConnectionState.CONNECTED, timeout, since)

    # --- the steps ----------------------------------------------------------

    def check_connect(self):
        since = time.time()
        self.service.keep_connected()
        if not self.wait_connected(since):
            self.result("connect", "FAIL", f"not connected within {WAIT_CONNECTED:.0f}s")
            return False
        state = self.service.state()
        took = time.time() - since
        names = self.service.presets()
        self.result("connect", "PASS", f"{took:.1f}s, preset {state.preset_name!r}, {len(names)} preset names "
                    f"(115 {'left out' if 115 not in names else 'STILL THERE'})")
        values = {k: round(v, 3) for k, v in state.params.items()}
        self.result("connect values", "PASS" if values else "CHECK", f"from the dump: {values}")
        return True

    def burst(self, label, name):
        """ set_latest() from several threads, 20 ms apart, the newest last. """
        since = time.time()
        threads = []
        for value in BURST:
            t = threading.Thread(target=self.service.set_latest, args=(name, value))
            t.start()
            threads.append(t)
            time.sleep(0.02)
        for t in threads:
            t.join(timeout=5)
        # Only the two Drive keys: a preset select's dump capture can carry other knob reports.
        key = next((e.data["key"] for t, e in self.events if t >= since
                    and e.event_type == EventType.PARAMETER_CHANGED and e.data["key"] in DRIVE_KEYS), None)
        sent = self.changes_since(since, key) if key else []
        got = self.service.get(name)
        ok = sent and got == BURST[-1] and len(sent) <= len(BURST)
        self.result(f"sliders {label}", "PASS" if ok else "CHECK",
                    f"{len(BURST)} moves -> {len(sent)} sets {sent} to {key}; get({name!r}) = {got}")
        return key

    def check_sliders(self):
        if not self.go("2. sliders", "On Chime, then Jungle $lash: Drive swept 0.1 to 0.9 in a quick burst; "
                       "the dump shows whether the last value reached the amp. No need to play."):
            return
        for preset in (CHIME, JUNGLE):
            name = self.service.select_preset(preset)
            # Which one the preset has: a model with Drive has DriveState (record 33) in the
            # dump, a Gain model GainState (1f). Presets can change (Chime 1 was saved over).
            has = records(self.service._amp.request_dump())
            expect = 0x26 if "2A:0/33" in has else 0x25
            key = self.burst(f"{preset} {name}", "drive")
            if key:
                self.result(f"drive pick {preset}", "PASS" if key[1] == expect else "FAIL",
                            f"\"drive\" went to {key[1]:#04x} (expected {expect:#04x})")
            # Read it back from the amp: the dump holds the value the amp really has.
            stored = {k: v for k, (typ, v) in records(self.service._amp.request_dump()).items()
                      if k in ("2A:0/1f", "2A:0/33")}
            arrived = any(abs(v - BURST[-1]) < 0.01 for v in stored.values())
            self.result(f"sliders {preset} in the amp", "PASS" if arrived else "FAIL",
                        f"the dump's Drive record: {stored} (expected {BURST[-1]})")

    def check_loss(self, number, title, lose, restore):
        if not self.go(f"{number}. {title}", f"With keep_connected() running you {lose}, then {restore}. "
                       "It should reconnect by itself."):
            return
        if not self.connected():
            self.wait_connected(time.time(), 30)
        self.ask(f"Now {lose}, then press Enter.")
        since = time.time()
        lost = self.wait_for(lambda e: e.event_type == EventType.CONNECTION_CHANGED
                             and e.data["state"] == ConnectionState.DISCONNECTED, 30, since)
        self.result(f"{title} lost", "PASS" if lost else "FAIL",
                    f"noticed after {time.time() - since:.1f}s: {lost.data.get('error')}" if lost else "not noticed in 30 s")
        self.ask(f"Now {restore}, then press Enter.")
        since = time.time()
        back = self.wait_connected(since)
        if not back:
            self.result(f"{title} back", "FAIL", f"not reconnected within {WAIT_CONNECTED:.0f}s")
            return
        tries = sum(1 for t, e in self.events if t >= since and e.event_type == EventType.CONNECTION_CHANGED
                    and e.data["state"] == ConnectionState.CONNECTING)
        names = len(self.service.presets())
        self.result(f"{title} back", "PASS" if names == 127 else "CHECK",
                    f"reconnected {time.time() - since:.1f}s after Enter, {tries} attempt(s), {names} preset names, "
                    f"preset {self.service.state().preset_name!r}")
        try:
            self.service.set("drive", 0.5)
            self.result(f"{title} set after", "PASS", "a set works on the new connection")
        except AmpError as e:
            self.result(f"{title} set after", "FAIL", f"{type(e).__name__}: {e}")

    def run(self):
        print(__doc__)
        try:
            self.write("connecting (about 15 s)...")
            if self.check_connect():
                self.check_sliders()
            self.check_loss(3, "replug", "pull the amp's USB cable out", "plug it back in")
            self.check_loss(4, "power", "switch the amp off (leave the USB in)", "switch it back on")
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
        FinishCheck(log_file).run()
    print(f"\nSaved to {path}. Turn the preset knob to reload a clean preset.")


if __name__ == "__main__":
    main()
