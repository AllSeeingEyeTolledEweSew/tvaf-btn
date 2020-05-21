# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Datatype classes for tvaf core functionality.

We use Python 3.7+'s dataclasses for all our data types.

While we don't use any full ORM system, each of the following datatypes is also
designed to closely align with its representation in tvaf's sqlite3 tables.
Wherever possible, attribute names match table column names, and types match
what you see when inserting into or selecting from the table.

We currently also use the third-party dataclasses_json library to facilitate
json encoding of datatypes, but that may change, and shouldn't be considered a
stable part of the interface.
"""

import dataclasses
import enum
from typing import Optional

import dataclasses_json

from tvaf.exceptions import Error

USER_UNKNOWN = "*unknown*"


class Tracker(enum.Enum):

    BTN = "btn"
    PTP = "ptp"


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class FileRef:
    """A range of data within a file, which is itself part of a collection.

    Attributes:
        path: The path to this file. Depending on the context, this may be
            a "suggested path" from a torrent file, or path to a real file on
            the local filesystem.
        file_index: The index of this file within the larger collection.
        start: The first byte referenced within this file.
        stop: The last byte referenced within this file, plus one.
    """

    path: str = ""
    file_index: int = 0
    start: int = 0
    stop: int = 0


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class TorrentMeta:
    """Tvaf's metadata about a torrent.

    Torrent metadata is persistent, even after the torrent has been deleted.

    Attributes:
        infohash: The infohash of the torrent.
        generation: The current generation of this torrent. Each time the
            torrent is added (either the first time, or after being deleted)
            tvaf increments the generation. This is used in Acct records,
            since the same torrent may be downloaded multiple times.
        atime: The time (in seconds since epoch) this torrent was accessed via
            tvaf.
    """

    infohash: str = ""
    generation: int = 0
    atime: int = 0


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class Acct:
    """A record attributing some downloaded torrent data to a user.

    An Acct record is an attribution stating that "tvaf downloaded {num_bytes}
    bytes of torrent {infohash}, in its {generation}th generation, on tracker
    {tracker}, on behalf of {user}".

    An Acct may either be an atomic attribution, or a roll-up record. For
    example, when username is "sam" and the other key fields are None, the
    Acct record is an attribution that "tvaf has downloaded {num_bytes} on
    behalf of sam." TODO directly creates group-by queries
    to create these rollup records.

    The username may be one of the tvaf.const.USER_* constants for some edge
    cases which don't correspond to a real user.

    To calculate Acct records, tvaf monitors which torrent pieces have been
    downloaded. When a piece is newly-downloaded, tvaf looks at all outstanding
    requests for that piece, and picks one to "blame" for the new download. To
    help with this, requests are not deleted immediately, but are instead
    placed in a deactivated state, for later Acct tracking. If there are no
    outstanding or deactivated requests, tvaf blames the piece on
    tvaf.const.USER_UNKNOWN.

    Attributes:
        user: The user of the downloaded bytes. May be one of the
            tvaf.const.USER_* constants.
        tracker: The name of the tracker on which the bytes were downloaded.
        infohash: The infohash of the torrent whose bytes were downloaded.
        generation: The generation of the torrent whose bytes were downloaded.
        num_bytes: The number of bytes that were downloaded.
        atime: The time of the most recent request submitted by this user for
            this torrent at this generation. For tvaf.const.USER_UNKNOWN
            records, this is just the time of the most recent download. Time is
            measured in seconds from epoch.
    """

    user: Optional[str] = None
    tracker: Optional[Tracker] = None
    infohash: Optional[str] = None
    generation: Optional[int] = None
    num_bytes: int = 0
    atime: int = 0