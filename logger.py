import time

class Color:
    """ Represents a color in the log output. """
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"

class Logger:
    """ A simple logger that prints messages with timestamps and optional colors. """
    def __init__(self, prefix: str = ""):
        self.prefix = f"{prefix} " if prefix else ""

    def log(self, text: str, color: str = Color.RESET):
        """ Logs a message with a timestamp. """
        timestamp = f"{Color.GRAY}{time.strftime('%H:%M:%S')}{Color.RESET}"
        prefix_str = f"{Color.BOLD}{self.prefix}{Color.RESET}" if self.prefix else ""
        print(f"{timestamp} {prefix_str}{color}{text}{Color.RESET}")

    def info(self, text: str):
        """ Logs an informational message. """
        self.log(text, Color.CYAN)

    def success(self, text: str):
        """ Logs a success message. """
        self.log(text, Color.GREEN)

    def warning(self, text: str):
        """ Logs a warning message. """
        self.log(text, Color.YELLOW)

    def error(self, text: str):
        """ Logs an error message. """
        self.log(text, Color.RED)

    def debug(self, text: str):
        """ Logs a debug message. """
        self.log(text, Color.GRAY)

    def preset(self, text: str):
        """ Logs a preset message. """
        self.log(text, Color.MAGENTA)
    
    def action(self, text: str):
        """ Logs an action message. """
        self.log(text, Color.BLUE)