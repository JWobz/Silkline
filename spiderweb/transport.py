"""
transport.py

The raw MIDI device: finding the amp, and reading and writing whole SysEx messages.

The lowest layer; Connection is the only user.
"""
import os
import select
import time

from spiderweb.errors import AmpNotFound
from spiderweb.logger import Logger

_SPIDER_KEYWORD = "spider"


class AmpTransport:
    """Transport layer for communicating with the amp. Handles sending and receiving messages over the raw MIDI device."""

    def __init__(self, devicepath: str):
        self.devicepath = devicepath
        self.fd = os.open(self.devicepath, os.O_RDWR | os.O_NONBLOCK)
        self.buf = bytearray()
        self.logger = Logger(prefix="AmpTransport")

    def send(self, data: bytes, timeout=1.0):
        """Writes the whole message, waiting for the device when its buffer is full."""
        remaining = memoryview(data)
        deadline = time.time() + timeout
        while remaining:
            try:
                written = os.write(self.fd, remaining)
                remaining = remaining[written:]
            except BlockingIOError:
                pass  # buffer full; wait below
            if remaining:
                if time.time() > deadline:
                    raise IOError(
                        f"Timed out sending to {self.devicepath}: {len(remaining)} of {len(data)} bytes unsent"
                    )
                select.select(
                    [], [self.fd], [], 0.05
                )  # wait until the device can take more

    def read(self, timeout):
        """Reads messages until timeout"""
        msgs = []
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                return []
            if chunk:
                self.buf += chunk
        while 0xF7 in self.buf:
            i = self.buf.index(0xF7)
            msgs.append(bytes(self.buf[: i + 1]))
            del self.buf[: i + 1]
        return msgs 

    def read_messages(self, quiet=0.05, limit=1.0):
        """Reads messages from the amp until a quiet period of `quiet` seconds is observed or a total of `limit` seconds has passed. Returns a list of complete messages received."""
        msgs, end, last = [], time.time() + limit, time.time()
        while time.time() < end and time.time() - last < quiet:
            r, _, _ = select.select([self.fd], [], [], 0.01)
            if r:
                try:
                    chunk = os.read(self.fd, 4096)
                except BlockingIOError:
                    continue
                if chunk:
                    self.buf += chunk
                    last = time.time()
            while 0xF7 in self.buf:
                i = self.buf.index(0xF7)
                msgs.append(bytes(self.buf[: i + 1]))
                del self.buf[: i + 1]
        return msgs

    def close(self):
        """Closes the transport connection to the amp."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

def find_device():
    """Finds the amp's raw MIDI device by looking for it in the ALSA card list."""
    card = None
    with open("/proc/asound/cards") as f:
        for line in f:
            first = line.split()[0] if line.split() else ""
            if first.isdigit():
                card = first  # a card's first line: remember its number
            if _SPIDER_KEYWORD in line.lower() and card is not None:
                return f"/dev/snd/midiC{card}D0"
    raise AmpNotFound(
        "Could not find amp port. Please check that the amp is connected and powered on."
    )
