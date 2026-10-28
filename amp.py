import os, select, time

DEFAULTDEVICE = "/dev/snd/midiC3D0"
BYTE_HEADER = bytes.fromhex("F0 00 01 0C 22 05 4D 00")
BEGIN_LENGTH = 29
SET_VALUE_LENGTH = 37

class Amp:
    def __init__(self, path=DEFAULTDEVICE):
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        self.buf = bytearray()
        self.device = path
        self.seq = 0x0C

    def handshake(self, path="handshake.txt"):
        messages = []
        with open(path) as f:
            for line in f:
                strippedLine = line.strip()
                if not strippedLine:
                    continue
                self.send(bytes.fromhex(strippedLine))
                messages.extend(self.read_messages())
        return messages
    
    def send(self, data: bytes):
        bytesWritten= os.write(self.fd, data)
        if bytesWritten < len(data):
            raise IOError(f"Failed to write all bytes to {self.device}: {bytesWritten} of {len(data)}")
    
    def read_messages(self, quiet=0.05, limit=1.0):
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
        os.close(self.fd)
        self.fd = None
    
    def set_raw(self, param_id, raw5):
        self.send(self.begin_message())
        self.read_messages()

        value = BYTE_HEADER + bytes([self.seq+1]) + bytes.fromhex("00 00 0F 00 2A 00 00 00") + bytes([param_id]) + bytes.fromhex("00 00 01 00 04 00 00 00") + raw5 + bytes(5) + bytes([0xF7])
        if len(value) != SET_VALUE_LENGTH:
            raise ValueError(f"SET_VALUE_LENGTH mismatch: {len(value)} != {SET_VALUE_LENGTH}")
        
        self.send(value)
        self.read_messages()
        self.seq = (self.seq + 2) % 128

    def begin_message(self):
        seq = bytes([self.seq])
        fixed = bytes.fromhex("00 00 07 00 0A 00 00 00 10")
        zeros = bytes(10)
        end = bytes([0xF7])

        begin = BYTE_HEADER + seq + fixed + zeros + end
        if len(begin) != BEGIN_LENGTH:
            raise ValueError(f"BEGIN_LENGTH mismatch: {len(begin)} != {BEGIN_LENGTH}")

        return begin

if __name__ == "__main__":
    amp = Amp()
    print(amp.handshake())
    amp.set_raw(0x25, bytes.fromhex("022B40203D"))
    for msg in amp.read_messages():
        print(msg.hex(" "))