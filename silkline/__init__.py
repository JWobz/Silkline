"""
__init__.py

Silkline: control a Line 6 Spider V MkII amp over USB (docs/api.md).

The names a program needs, so it can write "from silkline import AmpService":
the service, its state and events, and the errors it raises. Everything else
(Amp, Connection, the transport and silkline.protocol) is internal.
"""

__version__ = "1.0.0"

from silkline.errors import AmpDisconnected, AmpError, AmpNotFound, AmpTimeout
from silkline.service import APP_DATA_FOLDER, AmpService
from silkline.state import AmpState, ConnectionState, Event, EventType
