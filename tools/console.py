"""A console for the amp: watch what changes and type commands.

Usage (from the project root):
    python3 -m tools.console

Messages from the amp are handled on the connection's reader thread and
printed as they come; commands are read from the keyboard on the main thread.
"""
from silkline import protocol
from silkline.amp import Amp, load_handshake
from silkline.connection import Connection
from silkline.logger import Logger

CHANGE_THRESHOLD = 0.02


class AmpConsole:
    """ A console for interacting with the amp. """
    def __init__(self):
        self.amp = Amp(Connection(load_handshake()))
        self.amp.add_listener(self.handle_amp_message)
        self.amp.on_lost(self.handle_lost)
        self.logger = Logger(prefix="AmpConsole")
        self.running = True
        self.last = {}
        self.preset_position = None   # settled preset-knob position, None until the first click
        self.preset_candidates = []   # positions seen during the current click
        self.commands = {
            "help": self.cmd_help,
            "all": self.cmd_all,
            "set": self.cmd_set,
            "get": self.cmd_get,
            "select": self.cmd_select,
            "preset": self.cmd_preset,
            "exit": self.cmd_exit,
            "quit": self.cmd_exit,
        }

    def run(self):
        """ Connects to the amp and starts the console. """
        self.logger.info("Connecting to amp...")
        try:
            self.amp.connect()
            self.console_loop()
        finally:
            self.amp.close()

    def console_loop(self):
        """ Main console loop: reads commands until exit, Ctrl-D or Ctrl-C. """
        self.logger.info("Ready. Type 'help' for commands.")
        while self.running:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                print("\nExiting console.")
                break
            if line.strip():
                self.handle_command(line.strip())

    def handle_lost(self, error):
        """ Called once by the connection if the amp stops responding. """
        self.logger.error(f"Lost the amp: {error!r}. Type 'exit', then power-cycle the amp and replug USB.")

    def handle_amp_message(self, message):
        """ Handles one message from the amp (runs on the reader thread). """
        result = protocol.classify(message)
        match result:
            case (protocol.MessageKind.PARAM, key, value):
                if key == (0x2A, 0x02, 0):
                    return
                changed = key not in self.last or abs(value - self.last[key]) > CHANGE_THRESHOLD
                self.last[key] = value
                if changed:
                    self.logger.info(f"{self.name_for(key)} = {value:.3f}")
            case (protocol.MessageKind.PRESET_INFO, name):
                self.logger.info(f"Preset: {name!r}")
            case (protocol.MessageKind.TAP, bpm):
                self.logger.info(f"Tap: {bpm:.1f} bpm")
            case (protocol.MessageKind.SAVE, ):
                self.logger.info("Save Pressed")
            case (protocol.MessageKind.PRESET_CHANGE, position):
                # The value bounces while the knob moves; wait for the status message.
                self.preset_candidates.append(position)
            case (protocol.MessageKind.STATUS, ):
                if self.preset_candidates:
                    self.preset_position = protocol.settle_position(self.preset_candidates, self.preset_position)
                    self.preset_candidates = []
                    self.logger.info(f"Preset knob: position {self.preset_position}")
                    # We're on the reader thread, so ask without waiting (refresh, not request_dump).
                    if not self.amp.refresh_preset(self.show_refreshed_name):
                        self.logger.warning("Busy; preset name not refreshed.")

    def show_refreshed_name(self, dump):
        """ on_done for refresh_preset: runs on the reader thread when the dump is in, or on a timeout. """
        if dump.complete():
            self.logger.info(f"Preset name: {dump.name()!r}")
        else:
            self.logger.warning("No dump came back for the new preset.")

    def handle_command(self, line):
        """ Handles a command entered in the console. """
        parts = line.split()
        handler = self.commands.get(parts[0].lower())

        if handler is None:
            self.logger.error(f"Unknown command: {parts[0]} (type 'help')")
            return
        try:
            handler(parts[1:])
        except Exception as e:
            self.logger.error(f"{type(e).__name__}: {e}")

    def name_for(self, key):
        return protocol.KNOWN_PARAMETERS.get(key) or "Unknown " + "/".join(f"{x:02X}" for x in key)

    def cmd_exit(self, args):
        """ exit : leave the console """
        self.running = False

    def cmd_help(self, args):
        """ help : show this help """
        self.logger.info("Commands:")
        seen = set()
        for handler in self.commands.values():
            if handler not in seen:            # exit and quit share one handler
                seen.add(handler)
                self.logger.info("  " + handler.__doc__.strip())
        self.logger.info("Parameters (* = can be set from here):")
        for p in sorted(protocol.PARAMETERS, key=lambda p: p.name):
            mark = "*" if p.settable else " "
            self.logger.info(f"  {mark} {p.name.lower()}")

    def cmd_all(self, args):
        """ all : show all parameters and their current values """
        if not self.last:
            self.logger.info("No parameters seen yet.")
            return
        for key, value in sorted(self.last.items()):
            if key == (0x2A, 0x02, 0):
                continue
            self.logger.info(f"{self.name_for(key):<20} = {value:.3f}")

    def cmd_set(self, args):
        """ set <param> <value> : set a parameter (a float in its range, or 0 / 1 for an on/off) """
        if len(args) < 2:
            self.logger.error("Usage: set <param> <value>")
            return
        name, value_text = " ".join(args[:-1]), args[-1]
        param = protocol.BY_NAME.get(name.lower())
        if param is None:
            self.logger.error(f"Unknown parameter: {name}")
            return
        try:
            value = float(value_text)
        except ValueError:
            self.logger.error("Value must be a number.")
            return
        try:
            self.amp.set_parameter(param, value)     # waits for the amp's answer (protocol.md section 8)
        except ValueError as e:
            self.logger.error(str(e))
            return
        self.logger.info(f"Set {param.name} = {value:.3f} (the amp answered)")

    def cmd_get(self, args):
        """ get <param> : show the last value seen for a parameter """
        if not args:
            self.logger.error("Usage: get <param>")
            return

        name = " ".join(args)
        param = protocol.BY_NAME.get(name.lower())
        if param is None:
            self.logger.error(f"Unknown parameter: {name}")
            return

        value = self.last.get(param.key)
        if value is None:
            self.logger.error(f"No value seen yet for {param.name}")
            return
        self.logger.info(f"{param.name} = {value:.3f}")

    def cmd_select(self, args):
        """ select <n> : load preset n (0 Bass, 1 Acoustic, ... see protocol.md section 8) """
        if len(args) != 1:
            self.logger.error("Usage: select <n>")
            return
        dump = self.amp.select_preset(int(args[0], 0))
        self.logger.info(f"Loaded {dump.name()!r}")

    def cmd_preset(self, args):
        """ preset : ask the amp for the current preset's name """
        dump = self.amp.request_dump()
        self.logger.info(f"Current preset: {dump.name()!r}")


if __name__ == "__main__":
    console = AmpConsole()
    console.run()
