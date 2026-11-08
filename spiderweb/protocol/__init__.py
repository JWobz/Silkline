"""The amp's wire format (docs/protocol.md): messages, dumps, uploads, values and names.

Pure functions and tables; nothing here opens the device. The star imports let
tools write protocol.BY_NAME, protocol.classify and so on.
"""
from .dump import *
from .knob import *
from .messages import *
from .parameters import *
from .values import *
