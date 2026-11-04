import select
import sys

from spiderweb import protocol
from spiderweb.amp import Amp
from spiderweb.logger import Logger

CHANGE_THRESHOLD = 0.02


class AmpConsole:
    """ A console for interacting with the amp. """
    def __init__(self):
        self.amp = Amp()
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
        """ Main console loop. """
        self.logger.info("Ready. Type 'help' for commands.")
        fd = self.amp.transport.fd
        print("> ", end="", flush=True)
        while self.running:
            try:       
                ready, _, _ = select.select([sys.stdin, fd], [], [], 0.5)
                if fd in ready:
                    self.handle_amp_messages(self.amp.transport.read_messages())
                if sys.stdin in ready:
                    line = sys.stdin.readline()
                    if line == "":
                        break
                    if line.strip():
                        self.handle_command(line.strip())
                    if self.running:
                        print("> ", end="", flush=True)                   
            except KeyboardInterrupt:
                print("\nExiting console.")
                break
                
    def handle_amp_messages(self, messages):
        """ Handles messages received from the amp. """
        for message in messages:
            result = protocol.classify(message)
            match result:
                case (protocol.MessageKind.PARAM, key, value):
                    if key == (0x2A, 0x02, 0):
                        continue
                    changed = key not in self.last or abs(value - self.last[key]) > CHANGE_THRESHOLD
                    self.last[key] = value
                    if changed:
                        name = self.name_for(key)
                        self.logger.info(f"{name} = {value:.3f}")
                case (protocol.MessageKind.PRESET_INFO, name, _):
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
        """ Exits the console. """
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
        """ Sets a parameter by name to a given value between 0 and 1. """
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
            self.logger.error("Value must be a number between 0 and 1.")
            return
        if not (0 <= value <= 1):
            self.logger.error("Value must be between 0 and 1.")
            return
        replies = self.amp.set_parameter(param, value)
        self.handle_amp_messages(replies)

    def cmd_get(self, args):
        """ Gets the current value of a parameter by name. """
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

if __name__ == "__main__":
    console = AmpConsole()
    console.run()