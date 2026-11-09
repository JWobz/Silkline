"""
logger.py

A helper logger, responsible for printing to the console
"""


import time


class _Color:
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

    def _log(self, text: str, color: str = _Color.RESET):
        """ Logs a message with a timestamp. """
        timestamp = f"{_Color.GRAY}{time.strftime('%H:%M:%S')}{_Color.RESET}"
        prefix_str = f"{_Color.BOLD}{self.prefix}{_Color.RESET}" if self.prefix else ""
        print(f"{timestamp} {prefix_str}{color}{text}{_Color.RESET}")

    def info(self, text: str):
        """ Logs an informational message. """
        self._log(text, _Color.CYAN)

    def success(self, text: str):
        """ Logs a success message. """
        self._log(text, _Color.GREEN)

    def warning(self, text: str):
        """ Logs a warning message. """
        self._log(text, _Color.YELLOW)

    def error(self, text: str):
        """ Logs an error message. """
        self._log(text, _Color.RED)

    def debug(self, text: str):
        """ Logs a debug message. """
        self._log(text, _Color.GRAY)

    def preset(self, text: str):
        """ Logs a preset message. """
        self._log(text, _Color.MAGENTA)
    
    def action(self, text: str):
        """ Logs an action message. """
        self._log(text, _Color.BLUE)