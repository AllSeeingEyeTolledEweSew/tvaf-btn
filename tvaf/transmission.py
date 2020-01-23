# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Transmission integration for tvaf.

The transmissionrpc python package is typically used for interfacing to
Transmission, but it has a few performance problems, has accumulated a lot of
complexity, and is difficult to test.

Our reimplementation here is a very simple wrapper around the transmission API.
It doesn't support attribute setters like transmissionrpc does, and only
supports the most recent API version.
"""
from __future__ import annotations

import base64
import dataclasses
import enum
import re
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional
from typing import Sequence
from typing import SupportsFloat
from typing import SupportsInt
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

import intervaltree
import requests as requests_lib

from tvaf import util
from tvaf.types import Request

DEFAULT_REQUESTS_PER_BLOCK = 1
READING_REQUESTS_PER_BLOCK = 2

MIN_PRIORITY = -128
MAX_PRIORITY = 127

BLOCK_SIZE = 16 * 1024

SESSION_ID_HEADER = "X-Transmission-Session-Id"


def _mk_filtered(cls, kwargs):
    """Returns a cls instance, passing only the kwargs supported by cls.

    The intent is so that we can pass json with unknown fields to dataclass
    constructor functions.
    """
    # I couldn't figure out how to make correct type hints for this function.
    # We need to filter the type of cls to only classes whose constructor
    # accepts some arbitrary kwargs.
    filtered_kwargs: Dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        name = field.name
        if name in kwargs:
            filtered_kwargs[name] = kwargs[name]
    return cls(**filtered_kwargs)


def _clean_kwargs(func):
    """Decorator to translate kwargs from RPC form to Python form.

    Transmission's JSON API uses a style of identifiers with dashes like
    "piece-priorities". This wraps a function so it may be called with such
    arguments, but it may define its kwargs like "piece_priorities".

    Just translates "-" to "_" in the kwargs.

    Arguments:
        func: A function to wrap.

    Returns:
        A wrapped version of the function.
    """

    def wrapped(*args, **kwargs):
        sanitized_kwargs: Dict[str, Any] = {}
        for key, value in kwargs.items():
            key = re.sub("-", "_", key)
            sanitized_kwargs[key] = value
        return func(*args, **sanitized_kwargs)

    return wrapped


class TrackerState(enum.IntEnum):
    """An enum for the TrackerStats.*State fields."""

    INACTIVE = 0
    WAITING = 1
    QUEUED = 2
    ACTIVE = 3


@dataclasses.dataclass
class TrackerStats:
    """A dataclass for the "trackerStats" object of Transmission torrents.

    We've only defined the attributes we currently care about.

    Attributes:
        announce: The tracker announce url.
        announceState: The TrackerState constant for this announce process for
            this tracker.
        hasAnnounced: Whether the announce process has completed.
        hasScraped: Whether the scrape process has completed.
        lastAnnounceResult: The string message from the most recent announce.
            Usually "Success".
        lastAnnounceSucceeded: Whether the most recent announce process
            was successful.
        lastAnnounceTimedOut: Whether the most recent announce process timed
            out.
        lastScrapeResult: The string message from the most recent scrape.
        lastScrapeSucceeded: Whether the most recent scrape process was
            successful.
        lastScrapeTimedOut: Whether the most recent scrape process timed out.
        leecherCount: The count of leechers last reported by the tracker.
        scrapeState: The TrackerState constant for the scrape process for this
            tracker.
        seederCount: The count of seeders last reported by the tracker.
    """
    # pylint: disable=too-many-instance-attributes

    @classmethod
    @_clean_kwargs
    def from_json(cls: Type[TrackerStats], **kwargs: Any) -> TrackerStats:
        """Returns a TrackerStats from its JSON form."""
        return _mk_filtered(cls, kwargs)

    announce: str = ""
    # pylint: disable=invalid-name
    announceState: int = 0
    # pylint: disable=invalid-name
    hasAnnounced: bool = False
    # pylint: disable=invalid-name
    hasScraped: bool = False
    # pylint: disable=invalid-name
    lastAnnounceResult: str = ""
    # pylint: disable=invalid-name
    lastAnnounceSucceeded: bool = False
    # pylint: disable=invalid-name
    lastAnnounceTimedOut: bool = False
    # pylint: disable=invalid-name
    lastScrapeResult: str = ""
    # pylint: disable=invalid-name
    lastScrapeSucceeded: bool = False
    # pylint: disable=invalid-name
    lastScrapeTimedOut: bool = False
    # pylint: disable=invalid-name
    leecherCount: int = 0
    # pylint: disable=invalid-name
    scrapeState: int = 0
    # pylint: disable=invalid-name
    seederCount: int = 0


@dataclasses.dataclass
class File:
    """A file within a torrent, as understood by Transmission.

    Attributes:
        length: The length of the file in bytes.
        name: The relative pathname to the file.
    """

    @classmethod
    @_clean_kwargs
    def from_json(cls: Type[File], **kwargs: Any) -> File:
        """Returns a File from its JSON form."""
        return _mk_filtered(cls, kwargs)

    length: int = 0
    name: str = ""


class Status(enum.IntEnum):
    """An enum for the status of a torrent."""

    STOPPED = 0
    CHECK_WAIT = 1
    CHECK = 2
    DOWNLOAD_WAIT = 3
    DOWNLOAD = 4
    SEED_WAIT = 5
    SEED = 6


@dataclasses.dataclass
class Torrent:
    """A Torrent in Transmission.

    We've only defined the attributes we currently care about. Note that all
    type hints are Optional, to reflect the fact that fields are selectively
    returned from the API.

    Attributes:
        totalSize: The total length of the torrent data in bytes.
        hashString: The infohash of the torrent as a hex string.
        pieceSize: The size of a piece. Always a power of two, at least equal
            to BLOCK_SIZE.
        files: The files in the torrent.
        pieces: A bitmap of whether each piece has been downloaded and
            verified. The piece is either in the write cache or has been
            written to disk.
        downloadDir: The directory where the torrent's files are saved.
        status: One of the TorrentStatus enum values.
        trackerStats: A list of TrackerStats structures for each configured
            tracker.
        block_in_cache: A bitfield representing whether a given block is in the
            write cache, or written to disk.
        max_requests_per_block: The number of allowed outstanding requests for
            a given block. The granularity of the mapping is one entry per
            piece.
        piece_get: A bitfield representing whether to try to download a given
            piece.
        piece_priorities: The download priority of each piece. Note that
            priorities must fit within a signed 8-bit int.
        pieceCount: The total number of pieces.
    """
    # pylint: disable=too-many-instance-attributes

    @classmethod
    @_clean_kwargs
    def from_json(
            cls: Type[Torrent],
            pieces: Optional[str] = None,
            # pylint: disable=invalid-name
            trackerStats: Optional[Iterable[Dict[str, Any]]] = None,
            files: Optional[Iterable[Dict[str, Any]]] = None,
            block_in_cache: Optional[str] = None,
            piece_get: Optional[str] = None,
            **kwargs: Any) -> Torrent:
        """Returns a Torrent from its JSON form."""
        if pieces is not None:
            kwargs["pieces"] = base64.b64decode(pieces)
        if trackerStats is not None:
            kwargs["trackerStats"] = [
                TrackerStats.from_json(**t) for t in trackerStats
            ]
        if files is not None:
            kwargs["files"] = [File.from_json(**f) for f in files]
        if block_in_cache is not None:
            kwargs["block_in_cache"] = base64.b64decode(block_in_cache)
        if piece_get is not None:
            kwargs["piece_get"] = base64.b64decode(piece_get)
        return _mk_filtered(cls, kwargs)

    # pylint: disable=invalid-name
    totalSize: Optional[int] = None
    # pylint: disable=invalid-name
    hashString: Optional[str] = None
    # pylint: disable=invalid-name
    pieceSize: Optional[int] = None
    files: Optional[Sequence[File]] = None
    pieces: Optional[bytes] = None
    # pylint: disable=invalid-name
    downloadDir: Optional[str] = None
    status: Optional[int] = None
    # pylint: disable=invalid-name
    trackerStats: Optional[Sequence[TrackerStats]] = None
    block_in_cache: Optional[bytes] = None
    max_requests_per_block: Optional[Sequence[int]] = None
    piece_get: Optional[bytes] = None
    piece_priorities: Optional[Sequence[int]] = None
    # pylint: disable=invalid-name
    pieceCount: Optional[int] = None


@dataclasses.dataclass
class TorrentGetResult:
    """The result of a torrent-get API call.

    Attributes:
        torrents: A list of Torrents returned by the call.
    """

    @classmethod
    @_clean_kwargs
    def from_json(cls: Type[TorrentGetResult],
                  torrents: Optional[Iterable[Dict[str, Any]]] = None,
                  **kwargs: Any) -> TorrentGetResult:
        """Returns a TorrentGetResult from its JSON form."""
        if torrents is not None:
            kwargs["torrents"] = [Torrent.from_json(**j) for j in torrents]
        return _mk_filtered(cls, kwargs)

    torrents: Optional[Sequence[Torrent]] = None


@dataclasses.dataclass
class TorrentAddResult:
    """The result of a torrent-add API call.

    The resulting Torrent fields are minimal; the API only returns the
    "hashString", "name" and "id" fields.

    Attributes:
        torrent_added: A minimal Torrent, reflecting the result that a new
            torrent was added.
        torrent_duplicate: A minimal Torrent, reflecting the result that the
            given torrent was identical to an existing torrent.
    """

    @classmethod
    @_clean_kwargs
    def from_json(cls: Type[TorrentAddResult],
                  torrent_added: Optional[Dict[str, Any]] = None,
                  torrent_duplicate: Optional[Dict[str, Any]] = None,
                  **kwargs: Any) -> TorrentAddResult:
        """Returns a TorrentAddResult from its JSON form."""
        if torrent_added is not None:
            kwargs["torrent_added"] = Torrent.from_json(**torrent_added)
        if torrent_duplicate is not None:
            kwargs["torrent_duplicate"] = Torrent.from_json(**torrent_duplicate)
        return _mk_filtered(cls, kwargs)

    torrent_added: Optional[Torrent] = None
    torrent_duplicate: Optional[Torrent] = None


class Error(Exception):
    """Base class for all exceptions generated by the transmission API."""


class APIError(Error):
    """An error returned by the API."""


class HTTPError(Error):
    """An error occurred at the HTTP level."""


TorrentIds = Union[str, int, Iterable[Union[str, int]]]


class Client:
    """A client interface to the Transmission API.

    This client is designed to directly reflect the call structure of the
    Transmission API. Methods on this client match API methods, and they return
    dumb objects that directly reflect the returned JSON.

    Most API calls take a torrent_ids kwarg, which is a simple selector. It may
    either be an integer Transmission Torrent Id, an infohash hex string, a
    list of either of these, or the special value "recently-active", which
    selects all torrents that have had recent upload or download activity.

    The client currently doesn't support anything other than the most recent
    API. Using it with an older Transmission instance will probably result in
    undefined behavior.

    The client does support Transmission's CSRF protection.

    Under the hood, this client does all its operations on a requests.Session
    object, which can be customized or mocked for testing.

    Attributes:
        url: The Transmission API endpoint. Defaults to
            http://localhost:9091/transmission/rpc.
        auth: Any value suitable for passing as the auth= parameter to
            requests. May be a tuple of (user, pass), one of requests' auth
            handlers, or any other appropriate callable.
        timeout: A default timeout in seconds. May also be overridden in each
            API call.
        session: The requests.Session that will be used for all HTTP
            operations.
    """

    def __init__(self,
                 url: Optional[str] = None,
                 address: Optional[str] = None,
                 port: Optional[SupportsInt] = None,
                 auth: Any = None,
                 timeout: Optional[SupportsFloat] = None,
                 session: Optional[requests_lib.Session] = None):
        if address is None:
            address = "localhost"
        if port is None:
            port = 9091
        if url is None:
            url = f"http://{address}:{port}/transmission/rpc"
        if session is None:
            session = requests_lib.Session()
        self.url = url
        self.auth = auth
        self.timeout = timeout
        self.session = session
        self.headers: Dict[str, Optional[str]] = {}

    def request(self,
                method: str,
                arguments: Any,
                timeout: Optional[SupportsFloat] = None) -> Any:
        """Generic API call.

        Args:
            method: The name of the Transmission API to call.
            arguments: The JSON arguments structure.
            timeout: A timeout in seconds.

        Returns:
            The JSON structure returned by the API call, if any.

        Raises:
            APIError: If an API-level error was returned.
            HTTPError: If there was an HTTP-level error.
        """

        if timeout is None:
            timeout = self.timeout

        def do_request() -> requests_lib.Response:
            try:
                response = self.session.post(self.url,
                                             headers=self.headers,
                                             auth=self.auth,
                                             timeout=timeout,
                                             json=dict(method=method,
                                                       arguments=arguments))
            except requests_lib.RequestException as exc:
                raise HTTPError(exc)

            self.headers[SESSION_ID_HEADER] = response.headers.get(
                SESSION_ID_HEADER)

            return response

        response = do_request()

        if response.status_code == requests_lib.codes["conflict"]:
            response = do_request()

        if response.status_code >= 400:
            raise HTTPError(f"{response.status_code} error: {response.reason} "
                            f"for {self.url}")

        response_json = response.json()
        result = response_json.get("result")
        if result != "success":
            raise APIError(result)
        return response_json.get("arguments")

    def torrent_get(
            self,
            *,
            torrent_ids: Optional[TorrentIds] = None,
            fields: Optional[Sequence[str]] = None,
            timeout: Optional[SupportsFloat] = None) -> TorrentGetResult:
        """Get metadata about active torrents.

        Args:
            torrent_ids: A torrent selector.
            fields: A list of attributes to return for each torrent. Must be in
                API form ("piece-priorities", not "piece_priorities").
            timeout: A timeout in seconds.

        Returns:
            A TorrentGetResult reflecting the selected torrents.

        Raises:
            APIError: If an API-level error was returned.
            HTTPError: If there was an HTTP-level error.
        """
        if fields is None:
            fields = []
        arguments: Dict[str, Any] = dict(fields=fields)
        if torrent_ids is not None:
            arguments["ids"] = torrent_ids
        result = self.request("torrent-get", arguments, timeout=timeout)
        return TorrentGetResult.from_json(**result)

    def torrent_start(self,
                      *,
                      torrent_ids: Optional[TorrentIds] = None,
                      timeout: Optional[SupportsFloat] = None) -> None:
        """Make torrents active, if they were stopped.

        The method gives no indication of whether the torrents were previously
        stopped, or were already active.

        Args:
            torrent_ids: A torrent selector.
            timeout: A timeout in seconds.

        Raises:
            APIError: If an API-level error was returned.
            HTTPError: If there was an HTTP-level error.
        """
        arguments: Dict[str, Any] = dict()
        if torrent_ids is not None:
            arguments["ids"] = torrent_ids
        self.request("torrent-start", arguments, timeout=timeout)

    def torrent_add(
            self,
            *,
            metainfo: Optional[bytes] = None,
            timeout: Optional[SupportsFloat] = None) -> TorrentAddResult:
        """Add a torrent to Transmission.

        Transmission's API supports more arguments, but we currently only
        support the metainfo argument.

        Args:
            metainfo: The full contents of the metainfo .torrent file.
            timeout: A timeout in seconds.

        Returns:
            A TorrentAddResult reflecting the identifiers of the resulting
                torrent, and whether it already existed.

        Raises:
            APIError: If an API-level error was returned.
            HTTPError: If there was an HTTP-level error.
        """
        arguments: Dict[str, Any] = {}
        if metainfo is not None:
            arguments["metainfo"] = base64.b64encode(metainfo)
        result = self.request("torrent-add", arguments, timeout=timeout)
        return TorrentAddResult.from_json(**result)

    def torrent_flush(self,
                      *,
                      torrent_ids: Optional[TorrentIds] = None,
                      timeout: Optional[SupportsFloat] = None) -> None:
        """Flush the write cache of some torrents to disk.

        Args:
            torrent_ids: A torrent selector.
            timeout: A timeout in seconds.

        Raises:
            APIError: If an API-level error was returned.
            HTTPError: If there was an HTTP-level error.
        """
        arguments: Dict[str, Any] = dict()
        if torrent_ids is not None:
            arguments["ids"] = torrent_ids
        self.request("torrent-flush", arguments, timeout=timeout)

    def torrent_set(self,
                    *,
                    torrent_ids: Optional[TorrentIds] = None,
                    timeout: Optional[SupportsFloat] = None,
                    **kwargs: Any) -> None:
        """Modify attributes of some torrents.

        The given kwargs will be translated from Python form to RPC form
        ("piece_priorities" translated to "piece-priorities").

        Args:
            torrent_ids: A torrent selector.
            timeout: A timeout in seconds.
            **kwargs: Attributes to be modified.

        Raises:
            APIError: If an API-level error was returned.
            HTTPError: If there was an HTTP-level error.
        """
        arguments: Dict[str, Any] = {}
        for key, value in kwargs.items():
            key = re.sub("_", "-", key)
            arguments[key] = value
        if torrent_ids is not None:
            arguments["ids"] = torrent_ids
        self.request("torrent-set", arguments, timeout=timeout)


def iter_outstanding(torrent: Torrent, start: int, stop: int):
    assert torrent.pieceSize is not None
    assert torrent.pieces is not None
    start_piece, stop_piece = util.range_to_pieces(torrent.pieceSize, start,
                                                   stop)
    for piece in range(start_piece, stop_piece):
        if not util.bitmap_is_set(torrent.pieces, piece):
            yield piece


def iter_outstanding_req(torrent: Torrent, request: Request):
    return iter_outstanding(torrent, request.start, request.stop)


_TT = TypeVar("_TT")


def max_dict(iter_items: Iterator[Tuple[_TT, int]]) -> Dict[_TT, int]:
    result: Dict[_TT, int] = {}
    for key, value in iter_items:
        if key not in result or result[key] < value:
            result[key] = value
    return result


_SV = TypeVar("_SV")


def dict_to_sparse_list(
        value_dict: Dict[int, _SV]) -> Dict[str, Sequence[Union[int, _SV]]]:
    indexes = sorted(value_dict.keys())
    return dict(indexes=indexes, values=[value_dict[i] for i in indexes])


class TorrentDriver:

    REQUIRED_FIELDS = ("hashString", "block-in-cache", "pieces", "pieceSize",
                       "piece-priorities", "pieceCount", "piece-get",
                       "max-requests-per-block")

    def __init__(self, client: Client, torrent: Torrent,
                 requests: Sequence[Request]) -> None:
        assert all(r.infohash == torrent.hashString for r in requests)
        self.torrent = torrent
        self.requests = requests
        self.client = client

        self.read_requests: Iterable[Request] = []
        self.readahead_requests: Iterable[Request] = []
        self.random_requests: Iterable[Request] = []

        for req in requests:
            if req.random:
                self.random_requests.append(req)
            elif req.readahead:
                self.readahead_requests.append(req)
            else:
                self.read_requests.append(req)

        self.read_requests_tree_flat = intervaltree.IntervalTree()
        for req in self.read_requests:
            self.read_requests_tree_flat.addi(req.start, req.stop, req)
        self.read_requests_tree_flat.merge_overlaps()

    def any_reading_blocks_in_cache(self) -> bool:
        assert self.torrent.block_in_cache is not None
        assert self.torrent.pieces is not None
        assert self.torrent.pieceSize is not None
        for interval in self.read_requests_tree_flat.items():
            block_start, block_stop = util.range_to_pieces(
                BLOCK_SIZE, interval.begin, interval.end)
            for block in range(block_start, block_stop):
                if not util.bitmap_is_set(self.torrent.block_in_cache, block):
                    continue
                piece = block * BLOCK_SIZE // self.torrent.pieceSize
                if not util.bitmap_is_set(self.torrent.pieces, piece):
                    continue
                return True
        return False

    def maybe_flush(self) -> None:
        assert self.torrent.hashString is not None
        if self.any_reading_blocks_in_cache():
            self.client.torrent_flush(torrent_ids=self.torrent.hashString)

    def maybe_start(self) -> None:
        assert self.torrent.hashString is not None
        if self.requests and self.torrent.status == Status.STOPPED:
            self.client.torrent_start(torrent_ids=self.torrent.hashString)

    def iter_desired_priorities(self) -> Iterator[Tuple[int, int]]:
        # First, assign all read requests
        lowest_read_priority = MAX_PRIORITY
        for req in self.read_requests:
            next_priority = MAX_PRIORITY
            for piece in iter_outstanding_req(self.torrent, req):
                priority = next_priority
                next_priority -= 1
                next_priority = max(next_priority, MIN_PRIORITY)
                yield piece, priority
                lowest_read_priority = min(lowest_read_priority, priority)

        # Next, assign readahead requests. These cause sequential priority
        # orderings, but strictly lower priority than any reads.
        first_readahead_priority = lowest_read_priority - 1
        first_readahead_priority = max(first_readahead_priority, MIN_PRIORITY)
        for req in self.readahead_requests:
            next_priority = first_readahead_priority
            for piece in iter_outstanding_req(self.torrent, req):
                priority = next_priority
                next_priority -= 1
                next_priority = max(next_priority, MIN_PRIORITY)
                yield piece, priority

        # Lastly, assign any random requests.
        for req in self.random_requests:
            for piece in iter_outstanding_req(self.torrent, req):
                yield piece, MIN_PRIORITY

    def update_priorities(self) -> None:
        assert self.torrent.hashString is not None
        assert self.torrent.piece_priorities is not None
        assert self.torrent.pieceCount is not None
        assert self.torrent.piece_get is not None
        cur_priorities = self.torrent.piece_priorities
        set_priorities: Dict[int, int] = {}
        piece_desired: Dict[int, bool] = {}

        # Initialize wanted pieces
        for piece in iter_outstanding(self.torrent, 0, self.torrent.pieceCount):
            piece_desired[piece] = False

        # Calculate desired priorities from iterated version
        desired_priorities = max_dict(self.iter_desired_priorities())
        for piece in desired_priorities:
            piece_desired[piece] = True

        # Figure out which priorities we need to update
        set_priorities = dict(
            set(desired_priorities.items()) - set(enumerate(cur_priorities)))

        # Figure out which wanted-pieces we need to update
        set_piece_wanted: List[int] = []
        set_piece_unwanted: List[int] = []
        for piece, wanted in piece_desired.items():
            if util.bitmap_is_set(self.torrent.piece_get, piece) != wanted:
                if wanted:
                    set_piece_wanted.append(piece)
                else:
                    set_piece_unwanted.append(piece)

        # Apply the updates
        if set_priorities:
            self.client.torrent_set(
                torrent_ids=self.torrent.hashString,
                piece_priorities=dict_to_sparse_list(set_priorities))
        if set_piece_wanted:
            self.client.torrent_set(torrent_ids=self.torrent.hashString,
                                    pieces_wanted=set_piece_wanted)
        if set_piece_unwanted:
            self.client.torrent_set(torrent_ids=self.torrent.hashString,
                                    pieces_unwanted=set_piece_unwanted)

    def iter_desired_mrpb(self) -> Iterator[Tuple[int, int]]:
        assert self.torrent.pieceCount is not None
        for piece in iter_outstanding(self.torrent, 0, self.torrent.pieceCount):
            yield piece, DEFAULT_REQUESTS_PER_BLOCK

        for req in self.read_requests:
            for piece in iter_outstanding_req(self.torrent, req):
                yield piece, READING_REQUESTS_PER_BLOCK

    def update_max_requests_per_block(self) -> None:
        assert self.torrent.max_requests_per_block is not None
        assert self.torrent.hashString is not None
        desired_mrpb_by_piece = max_dict(self.iter_desired_mrpb())
        mrpb_by_piece = self.torrent.max_requests_per_block
        set_mrpb_by_piece = dict(
            set(desired_mrpb_by_piece.items()) - set(enumerate(mrpb_by_piece)))

        if set_mrpb_by_piece:
            self.client.torrent_set(
                torrent_ids=self.torrent.hashString,
                max_requests_per_block=dict_to_sparse_list(set_mrpb_by_piece))

    def drive(self) -> None:
        self.maybe_start()
        self.maybe_flush()

        self.update_priorities()
        self.update_max_requests_per_block()
