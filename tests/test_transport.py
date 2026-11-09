import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from silkline.transport import AmpTransport


class TestTransportRead(unittest.TestCase):
    """ AmpTransport on a named pipe (FIFO) standing in for the amp's MIDI device. """
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "midi"
        os.mkfifo(path)
        self.transport = AmpTransport(str(path))
        self.addCleanup(self.transport.close)
        self.amp = os.open(path, os.O_WRONLY | os.O_NONBLOCK)    # the "amp" end
        self.addCleanup(os.close, self.amp)

    def amp_sends(self, hex_bytes):
        os.write(self.amp, bytes.fromhex(hex_bytes))

    def test_nothing_waiting_returns_empty_after_timeout(self):
        start = time.time()
        self.assertEqual(self.transport.read(0.1), [])
        self.assertGreaterEqual(time.time() - start, 0.09)

    def test_whole_messages_are_returned(self):
        self.amp_sends("f00102f7 f00304f7")
        self.assertEqual(self.transport.read(0.5), [bytes.fromhex("f00102f7"), bytes.fromhex("f00304f7")])

    def test_a_half_message_waits_for_the_rest(self):
        self.amp_sends("f00102f7 f003")
        self.assertEqual(self.transport.read(0.5), [bytes.fromhex("f00102f7")])
        self.amp_sends("04f7")
        self.assertEqual(self.transport.read(0.5), [bytes.fromhex("f00304f7")])

    def test_a_spurious_wakeup_is_not_an_error(self):
        # select says "ready" but the read finds nothing: that's not an unplug.
        self.amp_sends("f0")
        with mock.patch("silkline.transport.os.read", side_effect=BlockingIOError):
            self.assertEqual(self.transport.read(0.1), [])

    def test_close_twice_is_harmless(self):
        self.transport.close()
        self.transport.close()


if __name__ == "__main__":
    unittest.main()
