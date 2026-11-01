import sys

from pathlib import Path
from amp import Amp
from logger import Color, Logger
from protocol import KNOWN_PARAMETERS, MessageKind, classify

CHANGE_THRESHOLD = 0.02
QUIET_SHAPES = {(29, 11, 1)}  # the amp sends these by itself; show each shape once

class AmpWatcher:
    """ Watches for messages from the amp and logs updates. """
    def __init__(self, capture_filename: str | None = None):
        self.capture_filename = capture_filename
        self.logger = Logger(prefix="AmpWatcher")
        self.last = {}
        self.last_heartbeat = None
        self.seen_shapes = set()
        self.amp = None

    def run(self):
        """ Default entry point for the watcher. Connects to the amp and starts watching for messages. """
        self.amp = Amp()
        self.save_handshake(self.amp.connect())
        self.watch()

    def watch(self):
        """ Listens for messages from the amp and logs updates. """
        if self.amp is None or not self.amp.connected:
            raise RuntimeError("Not connected to amp")
        
        self.logger.info("Listening for updates...")
        try:
            while True:
                updates = {}
                for message in self.amp.transport.read_messages():
                    result = classify(message)

                    match result:
                        case (MessageKind.PARAM, key, value):
                            if key not in self.last or abs(value - self.last[key]) >= CHANGE_THRESHOLD:
                                self.last[key] = value
                                updates[key] = value
                        case (MessageKind.PRESET_INFO, name, fingerprint):
                            self.logger.preset(f"Preset: {name!r} (fp=0x{fingerprint:02X}, len {len(message)}) hex: {message.hex()}")
                        case (MessageKind.UNKNOWN, shape):
                            if shape in QUIET_SHAPES:
                                if shape in self.seen_shapes:
                                    continue
                                self.seen_shapes.add(shape)
                            self.logger.error(f"Unknown message shape: {shape} hex: {message.hex()}")
                        case (MessageKind.TAP, bpm):
                            self.logger.preset(f"Tap message: {bpm:.3f} bpm")
                        case (MessageKind.SAVE,):
                            self.logger.preset("Save message received")
                        case (MessageKind.HEARTBEAT, heartbeat):
                            if (self.last_heartbeat is None or heartbeat != self.last_heartbeat):
                                self.last_heartbeat = heartbeat
                                self.logger.debug(f"Heartbeat: {heartbeat}")

                if updates:
                    self.logger.preset(", ".join(f"{self.name_for(k)}={v:.3f}" for k, v in sorted(updates.items())))
        except KeyboardInterrupt:
            self.logger.warning("Stopping...")
        finally:
            self.amp.close()

    def name_for(self, key):
        """ Finds a human-readable name for a parameter key, or returns a hex representation if not found. """
        name = KNOWN_PARAMETERS.get(key)
        if name is None:
            name = "Unfound " + "/".join(f"{x:02X}" for x in key)
        return name

    def save_handshake(self, messages):
        """Saves the handshake messages to a file, if a capture filename was provided."""
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
                for message in messages:
                    f.write(message.hex() + "\n")
        except Exception as e:
            self.logger.error(f"Failed to save handshake messages to {filepath}: {e}")

if __name__ == "__main__":
    capture_file = sys.argv[1] if len(sys.argv) > 1 else None
    watcher = AmpWatcher(capture_file)
    watcher.run()