import os, time, select
from logger import Logger


class AmpTransport:
    """ Transport layer for communicating with the amp. Handles sending and receiving messages over the raw MIDI device. """
    def __init__(self, devicepath : str):
        self.devicepath = devicepath
        self.fd = os.open(self.devicepath, os.O_RDWR | os.O_NONBLOCK)
        self.buf = bytearray()
        self.logger = Logger(prefix="AmpTransport")

    def send(self, data: bytes):
        """ Sends a message to the amp. """
        bytes_written = os.write(self.fd, data)
        if bytes_written != len(data):
            self.logger.error(f"Failed to send complete message. Sent {bytes_written} of {len(data)} bytes.")

    def read_messages(self, quiet=0.05, limit=1.0):
        """ Reads messages from the amp until a quiet period of `quiet` seconds is observed or a total of `limit` seconds has passed. Returns a list of complete messages received. """
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
                msgs.append(bytes(self.buf[:i + 1]))
                del self.buf[:i + 1]
        return msgs

    def close(self):
        """ Closes the transport connection to the amp. """
        os.close(self.fd)
        self.fd = None