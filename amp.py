import os, select, time, mido

SPIDER_KEYWORD = "spider"
BYTE_HEADER = bytes.fromhex("F0 00 01 0C 22 05 4D 00")
BEGIN_LENGTH = 29
SET_VALUE_LENGTH = 37

class Amp:
    """ Represents a connection to the amp. """
    def __init__(self):
        print("Searching for amp...")
        amp_port = self.find_amp_port()
        self.fd = os.open(amp_port, os.O_RDWR | os.O_NONBLOCK)
        self.buf = bytearray()
        self.device = amp_port
        self.seq = 0x0C

    def find_amp_port(self):
        """ Get all availible input/output port names """
        ports = mido.get_input_names()

        for port in ports:
            if SPIDER_KEYWORD.lower() in port.lower():
                print(f"Found amp port: {port}")
                return port
        raise RuntimeError("Could not find amp port. Please check that the amp is connected and powered on.")

    def handshake(self, path="handshake.txt"):
        """ Performs a handshake with the amp and returns the messages received during the handshake. If a path is provided, it will also save the handshake messages to that file. """
        logs = self.handshake_log(path)
        messages = []
        for _, replies in logs:
            messages.extend(replies)
        return messages
    
    def handshake_log(self, path="handshake.txt"):
        """ Performs a handshake with the amp and returns a list of tuples containing the line number and the messages received for each line sent. If a path is provided, it will also save the handshake messages to that file. """
        messages = []
        with open(path) as f:
            for number, line in enumerate(f):
                strippedLine = line.strip()
                if not strippedLine:
                    continue
                self.send(bytes.fromhex(strippedLine))
                messages.append((number, self.read_messages()))
        return messages
    
    def close(self):
        """ Closes the connection to the amp. """
        os.close(self.fd)
        self.fd = None

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
    
    def send(self, data: bytes):
        """ Sends a message to the amp. """
        bytesWritten= os.write(self.fd, data)
        if bytesWritten < len(data):
            raise IOError(f"Failed to write all bytes to {self.device}: {bytesWritten} of {len(data)}")
    
    def set_raw(self, param_id, raw5):
        """ Sets a parameter on the amp using a raw five-byte value. """
        self.send(self.begin_message())
        self.read_messages()

        value = BYTE_HEADER + bytes([self.seq+1]) + bytes.fromhex("00 00 0F 00 2A 00 00 00") + bytes([param_id]) + bytes.fromhex("00 00 01 00 04 00 00 00") + raw5 + bytes(5) + bytes([0xF7])
        if len(value) != SET_VALUE_LENGTH:
            raise ValueError(f"SET_VALUE_LENGTH mismatch: {len(value)} != {SET_VALUE_LENGTH}")
        
        self.send(value)
        self.read_messages()
        self.seq = (self.seq + 2) % 128

    def begin_message(self):
        """ Constructs the beginning message for a parameter set operation. """
        seq = bytes([self.seq])
        fixed = bytes.fromhex("00 00 07 00 0A 00 00 00 10")
        zeros = bytes(10)
        end = bytes([0xF7])

        begin = BYTE_HEADER + seq + fixed + zeros + end
        if len(begin) != BEGIN_LENGTH:
            raise ValueError(f"BEGIN_LENGTH mismatch: {len(begin)} != {BEGIN_LENGTH}")

        return begin