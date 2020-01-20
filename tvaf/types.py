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

import base64
import dataclasses
import os.path
import re
from typing import Optional
from typing import Sequence

import dataclasses_json

from tvaf.exceptions import ValidationError

_SHA1_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")


def _base64_to_bytes(string_in_base64):
    """Convert a base64 string to bytes."""
    if string_in_base64 is None:
        return None
    return base64.b64encode(string_in_base64).decode("utf-8")


def _bytes_to_base64(bytes_):
    """Convert bytes to a base64 string."""
    if bytes_ is None:
        return None
    return base64.b64decode(bytes_.encode("utf-8"))


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

    def validate(self):
        """Raise ValidationError for any internal inconsistencies."""
        if not self.path:
            raise ValidationError("path is empty")
        if not os.path.isabs(self.path):
            raise ValidationError(f"path not absolute: {self.path}")
        if self.file_index < 0:
            raise ValidationError(f"file_index: {self.file_index} < 0")
        if self.start < 0:
            raise ValidationError(f"start: {self.start} < 0")
        if self.stop <= 0:
            raise ValidationError(f"stop: {self.stop} <= 0")
        if self.start >= self.stop:
            raise ValidationError(f"start/stop: {self.start} >= {self.stop}")


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class RequestStatus:
    """The current status of a Request.

    For a variety of performance reasons, a Request is fulfilled by writing
    data to disk, and the requesting application should retrieve the data by
    reading ranges from the appropriate files on the local filesystem. Once
    available, the files attribute describes the ranges to read, in the right
    order.

    Note that tvaf may not fully fill out the files attribute. See
    tvaf.dal.get_request_status() for more information.

    Attributes:
        progress: The total number of bytes available for reading.
        progress_percent: This is equal to progress divided by Request.stop -
            Request.start. Once this is 1.0, the request is fully fulfilled.
        files: A list of FileRefs. The path attribute of each refers to a file
            on the local filesystem.
    """

    progress: int = 0
    progress_percent: float = 0
    files: Sequence[FileRef] = dataclasses.field(default_factory=list)


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class Request:
    """A request for a range of data.

    Requests are submitted to tvaf via tvaf.dal.add_request(), and should be
    polled via tvaf.dal.get_request_status() (though both are not required in
    all cases -- see those functions for more details).

    Not all fields are required when submitting a new request.

    For more information about the significance of each field, see
    tvaf.dal.add_request().

    Attributes:
        tracker: The name of a tracker, as understood by tvaf.
        start: The first byte referenced.
        stop: The last byte referenced, plus one.
        origin: The origin of this Request.
        random: If True, the caller doesn't need sequential access to the data.
        readahead: If True, the caller doesn't need the data immediately, but
            will need it in the future.
        priority: The priority of this request.
        time: The time this request was created, in seconds since epoch.
        request_id: The unique id of this request, assigned by tvaf.
        infohash: The infohash of the torrent referenced by this request.
        deactivated_at: None for active requests. If not None, then this is the
            time (in seconds since epoch) that the request was deleted.
    """
    # pylint: disable=too-many-instance-attributes

    tracker: str = ""
    start: int = 0
    stop: int = 0
    origin: str = ""
    random: bool = False
    readahead: bool = False
    priority: int = 0
    time: int = 0
    request_id: Optional[int] = None
    infohash: str = ""
    deactivated_at: Optional[int] = None

    def validate(self):
        """Raise ValidationError for any internal inconsistencies."""
        if self.start < 0:
            raise ValidationError(f"start: {self.start} < 0")
        if self.stop <= 0:
            raise ValidationError(f"stop: {self.stop} <= 0")
        if self.start >= self.stop:
            raise ValidationError(f"start/stop: {self.start} >= {self.stop}")


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class TorrentMeta:
    """Tvaf's metadata about a torrent.

    Torrent metadata is persistent, even after the torrent has been deleted.

    Attributes:
        infohash: The infohash of the torrent.
        generation: The current generation of this torrent. Each time the
            torrent is added (either the first time, or after being deleted)
            tvaf increments the generation. This is used in Audit records,
            since the same torrent may be downloaded multiple times.
        managed: True if this torrent is managed by tvaf, and may be
            automatically deleted. If False, tvaf will not automatically delete
            this torrent.
        atime: The time (in seconds since epoch) this torrent was accessed via
            tvaf.
    """

    infohash: str = ""
    generation: int = 0
    managed: bool = False
    atime: int = 0


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class TorrentStatus:
    """Information about an active torrent.

    This represents tvaf's knowledge about a torrent which is actively
    downloading or seeding. Once a torrent is deleted, it no longer has a
    TorrentStatus.

    Attributes:
        infohash: The infohash of the torrent.
        tracker: The name of a tracker which this torrent is currently using.
        piece_bitmap: The bitmap of pieces which have been flushed to disk.
        piece_length: The length of each piece. Always a power of two, at least
            16k.
        length: The total length of the torrent data in bytes.
        seeders: The number of seeders last reported by the tracker.
        leechers: The number of leechers last reported by the tracker.
        announce_message: The announce message last reported by the tracker.
        files: A list of FileRefs, corresponding to file ranges on the local
            machine where torrent data has been or will be written. Data is not
            guaranteed to actually have been written unless the corresponding
            piece in piece_bitmap is enabled.
    """

    infohash: str = ""
    tracker: str = ""
    piece_bitmap: bytes = dataclasses.field(default=b"",
                                            metadata=dataclasses_json.config(
                                                encoder=_base64_to_bytes,
                                                decoder=_bytes_to_base64))
    piece_length: int = 0
    length: int = 0
    seeders: int = 0
    leechers: int = 0
    announce_message: str = ""
    files: Sequence[FileRef] = dataclasses.field(default_factory=list)

    def validate(self):
        """Raise ValidationError for any internal inconsistencies."""
        if not _SHA1_REGEX.match(self.infohash):
            raise ValidationError(f"bad infohash: {self.infohash}")
        if self.piece_length <= 0:
            raise ValidationError(f"piece_length <= 0: {self.piece_length}")
        if self.piece_length & (self.piece_length - 1) != 0:
            raise ValidationError(
                f"piece_length not a power of 2: {self.piece_length}")
        if self.length <= 0:
            raise ValidationError(f"length <= 0: {self.length}")
        for fileref in self.files:
            fileref.validate()


@dataclasses_json.dataclass_json
@dataclasses.dataclass
class Audit:
    """An audit record attributing some downloaded torrent data to an origin.

    An audit record is an attribution stating that "tvaf downloaded {num_bytes}
    bytes of torrent {infohash}, in its {generation}th generation, on tracker
    {tracker}, on behalf of {origin}".

    An Audit may either be an atomic attribution, or a roll-up record. For
    example, when origin is "username" and the other key fields are None, the
    Audit record is an attribution that "tvaf has downloaded {num_bytes} on
    behalf of username." tvaf.dal.get_audits() directly creates group-by queries
    to create these rollup records.

    Typically origins correspond directly to usernames. However, tvaf may
    download data on its own to fulfill seeding requirements, and it may
    observe that its torrent client downloaded some bytes that didn't
    correspond to any request. The tvaf.const.ORIGIN_* constants are used for
    these system-origin cases.

    To calculate audit records, tvaf monitors which torrent pieces have been
    downloaded. When a piece is newly-downloaded, tvaf looks at all outstanding
    requests for that piece, and picks one to "blame" for the new download. To
    help with this, requests are not deleted immediately, but are instead
    placed in a deactivated state, for later audit tracking. If there are no
    outstanding or deactivated requests, tvaf blames the piece on
    tvaf.const.ORIGIN_UNKNOWN.

    Attributes:
        origin: The origin of the downloaded bytes. Typically a username or one
            of the tvaf.const.ORIGIN_* constants.
        tracker: The name of the tracker on which the bytes were downloaded.
        infohash: The infohash of the torrent whose bytes were downloaded.
        generation: The generation of the torrent whose bytes were downloaded.
        num_bytes: The number of bytes that were downloaded.
        atime: The time of the most recent request submitted by this origin for
            this torrent at this generation. For tvaf.const.ORIGIN_UNKNOWN
            records, this is just the time of the most recent download. Time is
            measured in seconds from epoch.
    """

    origin: Optional[str] = None
    tracker: Optional[str] = None
    infohash: Optional[str] = None
    generation: Optional[int] = None
    num_bytes: int = 0
    atime: int = 0
