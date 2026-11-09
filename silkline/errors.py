"""
errors.py

Contains the error classes for Amp
"""

class AmpError(Exception):
    """Custom exception for amp-related errors."""

class AmpDisconnected(AmpError):
    """Exception raised when the amp is disconnected."""

class AmpTimeout(AmpError):
    """Exception raised when a timeout occurs while communicating with the amp."""

class AmpNotFound(AmpError):
    """Exception raised when an amp cannot be found"""