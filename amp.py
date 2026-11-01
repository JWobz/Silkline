import os, select, time

import protocol

from transport import AmpTransport
from utils import find_amp_port
from logger import Logger


class Amp:
    """ Represents a connection to the amp. """
    def __init__(self):
        print("Searching for amp...")
        self.device = find_amp_port()
        self.transport = AmpTransport(self.device)
        self.seq = 0x0C
        self.connected = False
        self.logger = Logger(prefix="Amp")

    def connect(self):
        """ Connects to the amp and performs a handshake. """
        self.logger.warning("Connecting to amp...")
        try:
            messages = self.handshake()
            self.logger.success("Connected to amp successfully.")
            self.connected = True
        except Exception:
            self.close()
            raise
        return messages    

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
                self.transport.send(bytes.fromhex(strippedLine))
                messages.append((number, self.transport.read_messages()))
        return messages
    
    def close(self):
        """ Closes the connection to the amp. """
        self.transport.close()
        self.connected = False
    
    def set_raw(self, block, sub, param_id, raw5, unknown=1):
        """ Sets a parameter using a raw five-byte value. Returns the amp's replies. """
        replies = []
        self.transport.send(protocol.build_begin_message(self.seq))
        replies += self.transport.read_messages()

        self.transport.send(protocol.build_set_message(
            self.seq + 1, block, sub, param_id, raw5, unknown
        ))
        replies += self.transport.read_messages()
        self.seq = (self.seq + 2) % 128
        return replies

    def set_parameter(self, param, value):
        """ Sets a parameter by name to a given value between 0 and 1. """
        if not param.settable:
            raise ValueError(f"Parameter {param.name} is not settable.")
        if not (0 <= value <= 1):
            raise ValueError(f"Value must be between 0 and 1, got {value}")
        return self.set_raw(param.block, param.sub, param.id, protocol.encode_set_value(value))