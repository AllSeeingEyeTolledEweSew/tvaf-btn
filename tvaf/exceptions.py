# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Exception types for tvaf core functionality."""


class Error(Exception):
    """A base class for any errors belonging to tvaf code."""


class BadRequest(Error):
    """Exception raised when any input doesn't conform to expectations."""


class TrackerNotFound(BadRequest):
    """Exception raised when input references an unknown tracker."""


class TorrentEntryNotFound(BadRequest):
    """Exception raised when input references an unknown torrent entry."""
