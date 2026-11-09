"""Watch the amp and log what changes. Ctrl-C to stop.

Usage (from the project root):
    python3 -m tools.watch                  # just watch
    python3 -m tools.watch handshake.txt    # also save the handshake replies to captures/
"""
import sys
import time
from pathlib import Path

from silkline.amp import Amp, load_handshake
from silkline.connection import Connection
from silkline.logger import Logger
from silkline.protocol import KNOWN_PARAMETERS, MessageKind, classify

CHANGE_THRESHOLD = 0.02
QUIET_SHAPES = {(29, 11, 1)}  # the amp sends these by itself; show each shape once


class AmpWatcher:
    """ Watches for messages from the amp and logs updates. """
    def __init__(self, capture_filename: str | None = None):
        self.capture_filename = capture_filename
        self.logger = Logger(prefix="AmpWatcher")
        self.last = {}
        self.last_preset = None
        self.seen_shapes = set()
        self.amp = Amp(Connection(load_handshake()))
        self.amp.add_listener(self.handle_message)
        self.amp.on_lost(lambda error: self.logger.error(f"Lost the amp: {error!r}. Ctrl-C to stop."))

    def run(self):
        """ Default entry point for the watcher. Connects to the amp and starts watching for messages. """
        try:
            self.save_handshake(self.amp.connect())
            self.logger.info("Listening for updates...")
            while True:
                time.sleep(1)      # the connection's reader thread calls handle_message
        except KeyboardInterrupt:
            self.logger.warning("Stopping...")
        finally:
            self.amp.close()

    def handle_message(self, message):
        """ Logs one message from the amp (runs on the reader thread). """
        match classify(message):
            case (MessageKind.PRESET_INFO, name):
                self.logger.preset(f"Preset: {name!r} (len {len(message)}) hex: {message.hex()}")
            case (MessageKind.PRESET_CHANGE, preset):
                if self.last_preset is None or preset != self.last_preset:
                    self.last_preset = preset
                    self.logger.debug(f"Preset change: {preset} hex: {message.hex()}")
            case (MessageKind.PARAM, (0x2A, 0x02, 0), _):
                self.logger.info(f"2A/02 raw bytes: {message[35:40].hex()}")
            case (MessageKind.PARAM, key, value):
                if key not in self.last or abs(value - self.last[key]) >= CHANGE_THRESHOLD:
                    self.last[key] = value
                    self.logger.preset(f"{self.name_for(key)}={value:.3f}")
            case (MessageKind.TAP, bpm):
                self.logger.preset(f"Tap message: {bpm:.3f} bpm")
            case (MessageKind.SAVE,):
                self.logger.preset("Save message received")
            case (MessageKind.STATUS,):
                self.logger.debug(f"Status message received hex: {message.hex()}")
            case (MessageKind.UNKNOWN, shape):
                if shape in QUIET_SHAPES:
                    if shape in self.seen_shapes:
                        return
                    self.seen_shapes.add(shape)
                self.logger.error(f"Unknown message shape: {shape} hex: {message.hex()}")

    def name_for(self, key):
        """ Finds a human-readable name for a parameter key, or returns a hex representation if not found. """
        name = KNOWN_PARAMETERS.get(key)
        if name is None:
            name = "Unfound " + "/".join(f"{x:02X}" for x in key)
        return name

    def save_handshake(self, groups):
        """Saves the handshake replies to a file, if a capture filename was provided.

        groups is what amp.connect() returns: one list of replies per handshake line.
        Each group gets a "# handshake line N" marker so replies can be matched to lines.
        """
        if self.capture_filename is None:
            return

        filepath = Path("captures") / self.capture_filename

        if filepath.exists():
            while True:
                response = input(f"Capture file {self.capture_filename} already exists. Overwrite? (y/n): ").strip().lower()
                if response in ("y", "yes"):
                    break
                elif response in ("n", "no", ''):
                    self.logger.warning("Not overwriting capture file; handshake messages will not be saved.")
                    return
                else:
                    print("Please enter 'y' or 'n'.")
        try:
            with open(filepath, "w") as f:
                for line_number, group in enumerate(groups, 1):
                    f.write(f"# handshake line {line_number} ({len(group)} {'reply' if len(group) == 1 else 'replies'})\n")
                    for message in group:
                        f.write(message.hex() + "\n")
        except Exception as e:
            self.logger.error(f"Failed to save handshake messages to {filepath}: {e}")


if __name__ == "__main__":
    capture_file = sys.argv[1] if len(sys.argv) > 1 else None
    watcher = AmpWatcher(capture_file)
    watcher.run()
