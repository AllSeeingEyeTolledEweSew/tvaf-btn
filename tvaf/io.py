# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Data access functions for tvaf."""
from __future__ import annotations

import collections
import dataclasses
import enum
import logging
import math
import random
import re
import threading
import time
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Set
from typing import SupportsFloat
from typing import Tuple
from weakref import WeakValueDictionary

import dataclasses_json
import intervaltree
import libtorrent as lt

from tvaf import util
from tvaf.config import GetConfig
from tvaf.exceptions import Error
from tvaf.exceptions import ErrorValue

_log = logging.getLogger(__name__)


class RequestMode(enum.Enum):

    READ = "read"
    READAHEAD = "readahead"
    FILL = "fill"


_SHA1_REGEX = re.compile(r"[0-9a-fA-F]{40}")


@dataclasses_json.dataclass_json
@dataclasses.dataclass(frozen=True)
class RequestParams:
    infohash: str = ""
    fetch_params: Any = None
    start: int = 0
    stop: int = 0
    acct_params: Any = None
    mode: RequestMode = dataclasses.field(
        default=RequestMode.READ,
        metadata=dataclasses_json.config(encoder=RequestMode))

    def __post_init__(self):
        """Raise ValidationError for any internal inconsistencies."""
        if self.start < 0:
            raise Error(f"start: {self.start} < 0", code=400)
        if self.stop <= 0:
            raise Error(f"stop: {self.stop} <= 0", code=400)
        if self.start >= self.stop:
            raise Error(f"start/stop: {self.start} >= {self.stop}", code=400)
        if not _SHA1_REGEX.match(self.infohash):
            raise Error(f"invalid infohash: {self.infohash}", code=400)
        super().__setattr__("infohash", self.infohash.lower())


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
        user: The user originating this Request.
        random: If True, the caller doesn't need sequential access to the data.
        readahead: If True, the caller doesn't need the data immediately, but
            will need it in the future.
        time: The time this request was created, in seconds since epoch.
        request_id: The unique id of this request, assigned by tvaf.
        infohash: The infohash of the torrent referenced by this request.
        deactivated_at: None for active requests. If not None, then this is the
            time (in seconds since epoch) that the request was deleted.
    """

    def __init__(self,
                 *,
                 params: Optional[RequestParams] = None,
                 torrent: Optional[_Torrent] = None):
        assert params is not None
        assert torrent is not None

        self._params = params
        self._time = time.time()
        self._deactivated_at: Optional[SupportsFloat] = None
        self._error: Optional[ErrorValue] = None

        self._condition = threading.Condition(torrent._lock)
        self._torrent = torrent
        self._outstanding = params.stop - params.start
        self._have_chunk: Set[int] = set()

        self._torrent_info: Optional[lt.torrent_info] = None
        self._start_piece = 0
        self._stop_piece = 0

        self._chunks: Dict[int, bytes] = dict()
        self._read_offset = params.start
        self._read_outstanding = params.stop - params.start

    def pieces(self) -> Iterable[int]:
        with self._condition:
            return range(self._start_piece, self._stop_piece)

    @property
    def params(self) -> RequestParams:
        return self._params

    @property
    def time(self) -> SupportsFloat:
        return self._time

    @property
    def deactivated_at(self) -> Optional[SupportsFloat]:
        return self._deactivated_at

    @property
    def error(self) -> Optional[ErrorValue]:
        return self._error

    @property
    def active(self) -> bool:
        return self._deactivated_at is None

    @property
    def start_piece(self) -> int:
        return self._start_piece

    @property
    def stop_piece(self) -> int:
        return self._stop_piece

    def cancel(self):
        self._set_error(ErrorValue(message="Operation cancelled", code=499))
        self._torrent._sync()

    def _clamp(self, start: int, stop: int) -> Tuple[int, int]:
        return max(start, self.params.start), min(stop, self.params.stop)

    def _deactivate(self):
        with self._condition:
            if self._deactivated_at is None:
                self._deactivated_at = time.time()

    def _on_piece_finished(self, piece_index: int):
        with self._condition:
            assert self._torrent_info is not None
            start = piece_index * self._torrent_info.piece_length()
            stop = start + self._torrent_info.piece_size(piece_index)
            start, stop = self._clamp(start, stop)
            if stop - start <= 0:
                return
            if start in self._have_chunk:
                return
            self._have_chunk.add(start)
            self._outstanding -= stop - start

    def _have_outstanding(self) -> bool:
        with self._condition:
            return self._outstanding > 0

    def _set_torrent_info(self, torrent_info: lt.torrent_info):
        with self._condition:
            if self._torrent_info is not None:
                return
            self._torrent_info = torrent_info
            self._start_piece, self._stop_piece = util.range_to_pieces(
                self._torrent_info.piece_length(), self.params.start,
                self.params.stop)

    def _set_error(self, error: ErrorValue):
        with self._condition:
            if self._error is None:
                self._error = error
            self._condition.notify_all()

    def _add_piece(self, offset: int, piece: bytes):
        assert self.params.mode == RequestMode.READ
        start, stop = self._clamp(offset, offset + len(piece))
        chunk = piece[start - offset:stop - offset]
        if not chunk:
            return
        with self._condition:
            if start in self._chunks:
                if len(chunk) != len(self._chunks[start]):
                    _log.warning("adding different size chunk at %d: %d != %d",
                                 start, len(chunk), len(self._chunks[start]))
                return
            self._chunks[start] = chunk
            self._condition.notify_all()
            self._read_outstanding -= stop - start

    def has_next(self) -> bool:
        assert self.params.mode == RequestMode.READ
        with self._condition:
            return self._read_offset < self.params.stop

    def next(self, timeout: Optional[float] = None):
        assert self.params.mode == RequestMode.READ
        with self._condition:
            assert self.has_next()

            def condition():
                if self._read_offset in self._chunks:
                    return True
                if self._error is not None:
                    return True
                return False

            value = self._condition.wait_for(condition, timeout=timeout)
            if self._error is not None:
                self._error.raise_exception()
            if self._read_offset in self._chunks:
                chunk = self._chunks.pop(self._read_offset)
                self._read_offset += len(chunk)
                return chunk
            return b""


# The lifecycle of _Torrent objects has subtle motivation and I keep confusing
# myself, so I'm writing down my entire thought process here.

# Option 1: A _Torrent instance may get kept after all requests are removed.
# This simplifies the tricky sequence above. The downsides are that we need
# Spaceman to clean these up, and until cleanup happens we won't be able to
# retry this torrent on a different tracker.

# Option 2: A _Torrent instance only exists when we have requests, or a handle
# with nontrivial data.

# Tricky flow, straightforward version:
# - add_request()
#     (calls session.async_add_torrent())
# - process add_torrent_alert, get handle
# - remove_request()
#     (calls session.remove_torrent())
# - add_request()
#     (calls session.async_add_torrent())
# - remove_request()
#     (does what?)
# - add_request()
#     (calls session.async_add_torrent()?)
# - process torrent_removed_alert for first generation
# - process add_torrent_alert for second generation, get handle
# - ???
# - process add_torrent_alert for third generation, get handle?

# The real version of this flow is more complex, since it includes fetching the
# torrent file from the tracker. libtorrent's thread processes events in order,
# but fetches may return out-of-order.

# Option 2a: We have one _Torrent per call lifecycle of fetch /
# async_add_torrent / remove_torrent. When the last request is removed and
# the handle has no data, we try to remove_torrent, even if we already started
# an async_add_torrent that hasn't completed yet. The downside is that multiple
# add/remove calls can lead to multiple _Torrents calling async_add_torrent.
# libtorrent deduplicates handles, so to keep this lifecycle accurate, we would
# need to synchronize such that a previous remove_torrent happens before the
# next async_add_torrent. This is even more complex once we think about
# synchronizing fetch.

# Option 2b: A _Torrent instance exists when there are requests, a handle with
# data, or a pending fetch async_add_torrent. When a fetch or async_add_torrent
# completes, we check if there are requests; if there are we continue, if not
# we remove the torrent.

# Option 2b1: We drop the _Torrent once we call remove_torrent. We disregard
# torrent_removed_alert. An add_request will just create a new _Torrent and
# fire async_add_torrent, which will be correctly synchronized after the
# remove_torrent.

# Option 2b2: We persist the _Torrent on remove_torrent. When
# torrent_removed_alert is processed, we check if there are requests, and if so
# we start the fetch / async_add_torrent process again. Advantage: better
# defense than 2b1 against torrents being added/removed by code other than
# IOService, which we may want to do, in testing or otherwise.


class _Action(enum.Enum):

    FETCH = "fetch"
    ADD = "add"
    REMOVE = "remove"
    PAUSE = "pause"


def _req_key(req: Request):
    return (req.deactivated_at is not None, req.params.mode != RequestMode.READ,
            req.params.mode != RequestMode.READAHEAD,
            req.params.mode != RequestMode.FILL, random.random())


_cache_have_bug_4604 = None
_4604_STATE_TIMEOUT = 30
_4604_TICK_INTERVAL = 5


def _have_bug_4604():
    global _cache_have_bug_4604
    if _cache_have_bug_4604 is None:
        version = tuple(int(i) for i in lt.version.split("."))
        _cache_have_bug_4604 = (version < (1, 2, 7))
    return _cache_have_bug_4604


class _Torrent:

    _DEADLINE_GAP = 10000

    def __init__(self,
                 *,
                 ios: Optional[IOService] = None,
                 infohash: Optional[str] = None,
                 add_torrent_params: Optional[lt.add_torrent_params] = None):
        assert ios is not None

        if infohash is None:
            assert add_torrent_params is not None
            infohash = str(add_torrent_params.info_hash)

        self._ios = ios
        # One lock for both top-level and per-torrent operations. I have not
        # yet implemented a proper locking protocol between IOService and
        # _Torrent. I intend to move to gevent instead of firming up a locking
        # protocol.
        self._lock = ios._lock
        self._infohash = infohash

        self._requests: List[Request] = []
        self._readers: List[Request] = []
        self._requests_tree = intervaltree.IntervalTree()

        self._handle: Optional[lt.torrent_handle] = None
        self._pending: Dict[_Action, bool] = dict()
        self._add_torrent_params: Optional[lt.add_torrent_params] = None

        self._torrent_info: Optional[lt.torrent_info] = None

        self._piece_priorities: Dict[int, int] = dict()
        self._piece_seq: Dict[int, int] = dict()
        self._piece_readers: Dict[int, WeakValueDictionary[
            int, Request]] = collections.defaultdict(WeakValueDictionary)
        self._piece_reading: Set[int] = set()
        self._piece_have: Set[int] = set()
        self._state: lt.torrent_status.states = lt.torrent_status.states.checking_resume_data
        self._flags = 0

        self._removal_requested = False
        self._remove_data_requested = False

        # State to work around libtorrent bug 4604
        self._pieces_downloaded = 0
        self._time_4604_changed = 0.0

        if add_torrent_params is not None:
            self._set_add_torrent_params(add_torrent_params)

    def _check_4604(self):
        if not _have_bug_4604():
            return

        with self._lock:
            if self._handle is None:
                return
            now = time.time()
            delta = self._time_4604_changed - now
            if delta < _4604_STATE_TIMEOUT:
                return
            if self._state != lt.torrent_status.states.downloading:
                return
            outstanding = self._pieces_downloaded - len(self._piece_have)
            if outstanding <= 0:
                return

            self._warning(
                "Working around "
                "http://github.com/arvidn/libtorrent/issues/4604: "
                "there have been %d pieces downloaded but not hashed for %s "
                "seconds. Force-checking the torrent to recover lost hash "
                "jobs. You should upgrade to libtorrent>=1.2.7", outstanding,
                delta)
            self._handle.force_recheck()
            self._time_4604_changed = now

    def handle_status_update(self, status: lt.torrent_status):
        with self._lock:
            assert self._torrent_info is not None

            if _have_bug_4604():
                pieces_downloaded = round(status.progress *
                                          self._torrent_info.num_pieces())
                if pieces_downloaded != self._pieces_downloaded:
                    self._time_4604_changed = time.time()
                self._pieces_downloaded = pieces_downloaded
                self._check_4604()

    def tick(self):
        with self._lock:
            self._check_4604()

    def _is_paused(self) -> bool:
        with self._lock:
            return bool(self._flags & lt.torrent_flags.paused)

    def _set_add_torrent_params(self, atp: lt.add_torrent_params):
        assert atp.ti is not None
        atp.file_priorities = []
        atp.piece_priorities = [0] * atp.ti.num_pieces()
        atp.flags &= ~lt.torrent_flags.paused
        if _have_bug_4604():
            atp.flags |= lt.torrent_flags.update_subscribe
        with self._lock:
            self._add_torrent_params = atp
            self._torrent_info = atp.ti
            for req in self._requests:
                self._init_req(req)
            self._sync()

    def _log(self, method, msg: str, *args, **kwargs):
        msg = "%s: " + msg
        if self._torrent_info is not None:
            title = self._torrent_info.name()
        else:
            title = self._infohash
        method(msg, *([title] + list(args)), **kwargs)

    def _debug(self, msg: str, *args, **kwargs):
        self._log(_log.debug, msg, *args, **kwargs)

    def _exception(self, msg: str, *args, **kwargs):
        self._log(_log.exception, msg, *args, **kwargs)

    def _error(self, msg: str, *args, **kwargs):
        self._log(_log.error, msg, *args, **kwargs)

    def _warning(self, msg: str, *args, **kwargs):
        self._log(_log.warning, msg, *args, **kwargs)

    def _any_pending(self) -> bool:
        return bool(self._pending)

    def _mark_pending(self, action: _Action):
        self._pending[action] = True

    def _remove_pending(self, action: _Action):
        self._pending.pop(action, None)

    def _init_req(self, req: Request):
        with self._lock:
            if self._torrent_info is not None:
                req._set_torrent_info(self._torrent_info)
                self._requests_tree.addi(req.start_piece, req.stop_piece, req)
            for i in req.pieces():
                if i in self._piece_have:
                    req._on_piece_finished(i)
                if req.params.mode == RequestMode.READ:
                    self._piece_readers[i][id(req)] = req

    def add_request(self, params: RequestParams) -> Request:
        req = Request(params=params, torrent=self)
        with self._lock:
            self._removal_requested = False
            self._remove_data_requested = False
            self._requests.append(req)
            self._init_req(req)
            self._sync()
        return req

    def request_removal(self, remove_data: bool = False):
        with self._lock:
            self._removal_requested = True
            self._remove_data_requested = remove_data
            self._fatal(ErrorValue(message="Delete requested", code=500))

    def _update_priorities(self):
        # Libtorrent strictly downloads time-critical pieces first, in order of
        # their deadlines. Other than this the deadlines are not meaningful --
        # a piece with a deadline of tomorrow is still treated as
        # time-critical. Torrents have a mode to download normal-priority
        # pieces sequentially, but libtorrent treats the entire torrent as a
        # single sequence for this purpose.

        # We want reading and readahead requests to be downloaded sequentially,
        # but they shouldn't block each other. At any given moment, the first
        # outstanding piece of each READ request should be given
        # equally-highest priority, followed by the second outstanding piece of
        # each, and so on. READAHEAD requests should be treated similarly,
        # except that they should be prioritized strictly after READ requests.
        with self._lock:
            if self._handle is None:
                return
            if self._is_checking():
                return

            assert self._torrent_info is not None

            want_seq: Dict[int, int] = dict()
            want_reading: Set[int] = set()
            want_priorities: Dict[int, int] = {
                i: 0
                for i in range(self._torrent_info.num_pieces())
                if i not in self._piece_have
            }

            for req in self._requests:
                if req.params.mode != RequestMode.FILL:
                    continue
                for i in req.pieces():
                    if i in self._piece_have:
                        continue
                    want_priorities[i] = 1

            base_readahead_seq = 0
            for req in self._requests:
                if req.params.mode != RequestMode.READ:
                    continue
                seq = 0
                for i in req.pieces():
                    if i in self._piece_have:
                        continue
                    want_seq[i] = min(seq, want_seq.get(i, math.inf))
                    want_reading.add(i)
                    want_priorities[i] = 7
                    base_readahead_seq = max(base_readahead_seq, seq + 1)
                    seq += 1

            for req in self._requests:
                if req.params.mode != RequestMode.READAHEAD:
                    continue
                seq = 0
                for i in req.pieces():
                    if i in self._piece_have:
                        continue
                    want_seq[i] = min(seq + base_readahead_seq,
                                      want_seq.get(i, math.inf))
                    want_priorities[i] = 7
                    seq += 1

            # If any deadlines or reading states changed, change them all. This
            # is because we can only set deadlines in milliseconds from "now",
            # and libtorrent checks the current time with every
            # set_piece_deadline call.

            piece_reading_outstanding: Set[int] = set()
            piece_reading_have: Set[int] = set()
            for i in self._piece_reading:
                if i in self._piece_have:
                    piece_reading_have.add(i)
                else:
                    piece_reading_outstanding.add(i)

            if want_reading != piece_reading_outstanding or want_seq != self._piece_seq:
                update_pieces = set(want_seq) | set(self._piece_seq)
            else:
                update_pieces = set()

            if update_pieces:
                self._piece_seq = want_seq
                self._piece_reading = piece_reading_have
                self._piece_reading.update(want_reading)

                # Pieces with equal sequence numbers may end up with offset
                # deadlines, since libtorrent adds the current time. Assign
                # them in random order to avoid bias.
                update_pieces = random.sample(update_pieces,
                                              k=len(update_pieces))

            # NB: If there are many outstanding read_piece_alerts for the same
            # READ request, we will end up triggering duplicate
            # read_piece_alerts. When processing each alert, we re-prioritize,
            # which re-sets alert_when_available on the subsequent pieces. If
            # these are already downloaded, it is equivalent to calling
            # read_piece.

            for i in update_pieces:
                seq = self._piece_seq.get(i)
                if seq is not None:
                    flags = 0
                    if i in self._piece_reading:
                        flags |= lt.deadline_flags_t.alert_when_available
                    deadline = seq * self._DEADLINE_GAP
                    self._debug("set_piece_deadline(%d, %d, %d)", i, deadline,
                                flags)
                    # Non-blocking
                    self._handle.set_piece_deadline(i, deadline, flags)
                else:
                    self._debug("reset_piece_deadline(%d)", i)
                    # Non-blocking
                    self._handle.reset_piece_deadline(i)

            if want_priorities != self._piece_priorities:
                self._debug("prioritize_pieces(%s)",
                            list(want_priorities.items()))
                # Non-blocking
                self._handle.prioritize_pieces(list(want_priorities.items()))
                self._piece_priorities = want_priorities

    def handle_read_piece_alert(self, alert: lt.read_piece_alert):
        error = ErrorValue.from_alert(alert)
        data = alert.buffer
        i = alert.piece

        with self._lock:
            assert self._torrent_info is not None
            self._piece_reading.discard(i)
            readers = list(self._piece_readers.pop(i, dict()).values())
            if error is None:
                offset = i * self._torrent_info.piece_length()
                for req in readers:
                    req._add_piece(offset, data)
            else:
                for req in readers:
                    req._set_error(error)
                self._sync()

    def handle_piece_finished_alert(self, alert: lt.piece_finished_alert):
        i = alert.piece_index

        with self._lock:
            assert self._torrent_info is not None

            if _have_bug_4604():
                self._time_4604_changed = time.time()

            self._piece_have.add(i)
            self._piece_priorities.pop(i, None)
            self._piece_seq.pop(i, None)

            intervals = self._requests_tree.at(i)
            reqs = [interval.data for interval in intervals]

            for req in reqs:
                req._on_piece_finished(i)

            self._sync()

            if self._is_checking():
                return

            piece_size = self._torrent_info.piece_size(i)

            reqs = sorted(reqs, key=_req_key)
            if reqs:
                params = reqs[0].params.acct_params
            else:
                params = None

            self._debug("acct(%d, %s)", piece_size, params)

    def handle_hash_failed_alert(self, alert: lt.hash_failed_alert):
        i = alert.piece_index

        with self._lock:
            self._piece_have.discard(i)
            self._sync()

    def _keep(self) -> bool:
        with self._lock:
            # Active requests override everything, including explicit removal
            if self._requests:
                return True

            # Explicit removal overrides whether we have any data
            if self._removal_requested:
                return False

            # If we have data, expect to have data, or are currently checking
            # whether we have data, keep the torrent for now.
            if self._piece_have:
                return True
            if self._add_torrent_params is not None and any(
                    self._add_torrent_params.have_pieces):
                return True
            if self._handle is not None and self._is_checking():
                return True

            # If we have no requests and no data, we don't need this torrent.
            return False

    def _is_checking(self) -> bool:
        with self._lock:
            return self._state in (
                lt.torrent_status.states.checking_resume_data,
                lt.torrent_status.states.allocating,
                lt.torrent_status.states.checking_files,
            )

    def _fatal(self, error: ErrorValue):
        with self._lock:
            for req in self._requests:
                req._set_error(error)
            self._sync()

    def _cleanup(self):
        with self._lock:
            requests = self._requests
            self._requests = []
            for req in requests:
                self._debug("cleanup: %s: %s, %s", req, req.error,
                            req._have_outstanding())
                if req.error is None and req._have_outstanding():
                    self._requests.append(req)
                else:
                    req._deactivate()
                    self._requests_tree.discardi(req.start_piece,
                                                 req.stop_piece, req)

    def _read_pieces(self):
        with self._lock:
            if self._handle is None:
                return
            # It's fine to call read_piece even if we're checking.
            for i, readers in self._piece_readers.items():
                # Readers may have been garbage collected
                if not readers:
                    continue
                if i in self._piece_have and i not in self._piece_reading:
                    self._debug("firing read_piece(%d)", i)
                    # Non-blocking
                    self._handle.read_piece(i)
                    self._piece_reading.add(i)

    def _update_flags(self):
        with self._lock:
            if self._handle is None:
                return

            set_bits: List[Tuple[int, bool]] = []

            if self._keep():
                if not (self._flags & lt.torrent_flags.auto_managed):
                    self._debug("setting auto_managed")
                    set_bits.append((lt.torrent_flags.auto_managed, True))
            else:
                if not (self._flags & lt.torrent_flags.paused):
                    self._debug("pausing")
                    self._mark_pending(_Action.PAUSE)
                    set_bits.append((lt.torrent_flags.auto_managed, False))
                    set_bits.append((lt.torrent_flags.paused, True))

            flags = 0
            mask = 0
            for bit, is_set in set_bits:
                mask |= bit
                if is_set:
                    flags |= bit

            if not mask:
                return

            immediate_mask = mask & ~lt.torrent_flags.paused

            self._flags &= ~immediate_mask
            self._flags |= (flags & immediate_mask)

            # Non-blocking
            self._handle.set_flags(flags, mask)

    def handle_torrent_paused_alert(self, alert: lt.torrent_paused_alert):
        with self._lock:
            self._remove_pending(_Action.PAUSE)
            self._flags |= lt.torrent_flags.paused
            self._sync()

    def handle_torrent_resumed_alert(self, alert: lt.torrent_resumed_alert):
        with self._lock:
            self._flags &= lt.torrent_flags.paused
            self._sync()

    def _sync(self):
        with self._lock:
            self._cleanup()
            self._read_pieces()
            self._update_priorities()
            self._update_flags()
            if self._keep():
                if self._handle is None:
                    if self._add_torrent_params is None:
                        self._maybe_async_fetch_torrent_info()
                    else:
                        self._maybe_async_add_torrent()
            else:
                if self._handle is not None:
                    self._maybe_remove_torrent()
                else:
                    self._maybe_remove_from_parent()

    def _should_graceful_pause(self):
        with self._lock:
            if self._flags & lt.torrent_flags.paused:
                return False
            if self._keep():
                return False
            if self._removal_requested:
                return False
            return True

    def _should_resume(self):
        with self._lock:
            if not (self._flags & lt.torrent_flags.paused):
                return False
            if self._flags & lt.torrent_flags.auto_managed:
                return False
            if self._is_checking():
                return False
            return True

    def _maybe_graceful_pause(self):
        with self._lock:
            if self._any_pending():
                return

            assert self._handle is not None

            self._debug("gracefully pausing torrent")
            self._mark_pending(_Action.GRACEFUL_PAUSE)

            flags = lt.torrent_flags.paused
            mask = lt.torrent_flags.paused | lt.torrent_flags.auto_managed
            # Non-blocking
            self._handle.set_flags(flags, mask)

            self._flags &= ~lt.torrent_flags.auto_managed

    def _maybe_resume(self):
        with self._lock:
            if self._any_pending():
                return

            assert self._handle is not None

            self._debug("resuming torrent")

    def _get_preferred_params(self) -> Optional[RequestParams]:
        with self._lock:
            reqs = sorted(self._requests, key=_req_key)
            if reqs:
                return reqs[0].params
            return None

    def _maybe_async_fetch_torrent_info(self):

        def fetch(params: Any):
            torrent_info: Optional[lt.torrent_info] = None
            error: Optional[ErrorValue] = None
            try:
                torrent_info = self._ios.fetch(self._infohash, params)
            except:
                error = ErrorValue.from_exc_info()
            try:
                self._handle_fetched_torrent_info(torrent_info=torrent_info,
                                                  error=error)
            except:
                self._exception("during handle_fetched_torrent_info")

        with self._lock:
            assert self._add_torrent_params is None

            if self._any_pending():
                return

            self._debug("fetching torrent info")
            self._mark_pending(_Action.FETCH)

            reqs = sorted(self._requests, key=_req_key)
            assert reqs
            params = reqs[0].params.fetch_params

            fetch_thread = threading.Thread(name=f"fetch-{self._infohash}",
                                            target=fetch,
                                            args=(params,))
            fetch_thread.start()

    def _handle_fetched_torrent_info(
        self,
        torrent_info: Optional[lt.torrent_info] = None,
        error: Optional[ErrorValue] = None):
        save_path = self._ios.get_config().save_path

        with self._lock:
            self._remove_pending(_Action.FETCH)

            if error is not None:
                self._error("while fetching torrent info: %s", error)
                self._fatal(error)
                return

            assert torrent_info is not None

            self._debug("got torrent info")

            atp = lt.add_torrent_params()
            # NB: async_add_torrent may do disk io to normalize the path
            atp.save_path = save_path
            atp.ti = torrent_info

            self._set_add_torrent_params(atp)

    def _maybe_async_add_torrent(self):
        with self._lock:
            assert self._add_torrent_params is not None
            assert self._handle is None

            if self._any_pending():
                return

            self._debug("adding torrent")
            self._mark_pending(_Action.ADD)

            # DOES block (may do disk io to normalize path)
            self._ios._session.async_add_torrent(self._add_torrent_params)

    def handle_add_torrent_alert(self, alert: lt.add_torrent_alert):
        error = ErrorValue.from_alert(alert)

        with self._lock:
            self._remove_pending(_Action.ADD)
            atp = self._add_torrent_params
            # Release reference
            self._add_torrent_params = None

            if error is not None:
                self._error("while adding: %s", error)
                self._fatal(error)
                return

            self._piece_reading = set()
            self._piece_priorities = dict()
            self._piece_seq = dict()
            # The torrent will be checking_resume_data now, though we don't get
            # a state_changed_alert for this.
            self._state = lt.torrent_status.states.checking_resume_data

            assert atp is not None
            self._flags = atp.flags

            if self._handle is not None:
                self._warning("got add_torrent_alert but already have handle")

            self._handle = alert.handle
            self._sync()

    def _maybe_remove_torrent(self):
        with self._lock:
            if self._any_pending():
                return

            self._debug("removing torrent")
            self._mark_pending(_Action.REMOVE)

            # libtorrent's python bindings don't export these flags?
            if self._remove_data_requested:
                flags = 1
            else:
                flags = 0
            handle = self._handle
            self._handle = None
            self._add_torrent_params = None
            # DOES block (checks handle is valid)
            self._ios._session.remove_torrent(handle, flags)

    def handle_torrent_removed_alert(self, alert: lt.torrent_removed_alert):
        with self._lock:
            self._remove_pending(_Action.REMOVE)

            with self._ios._lock:
                self._ios._torrents_by_handle.pop(alert.handle, None)
            # This errors out any existing requests, and syncs to the next
            # step.
            self._fatal(ErrorValue(message="Unexpectedly removed", code=500))

    def _maybe_remove_from_parent(self):
        with self._ios._lock:
            if self._any_pending():
                return

            self._debug("removing from parent")
            del self._ios._torrents[self._infohash]

    def handle_torrent_error_alert(self, alert: lt.torrent_error_alert):
        with self._lock:
            error = ErrorValue.from_alert(alert)
            if error is not None:
                self._fatal(error)

    def handle_state_changed_alert(self, alert: lt.state_changed_alert):
        with self._lock:
            if _have_bug_4604():
                self._time_4604_changed = time.time()
            self._debug("%s -> %s", alert.prev_state, alert.state)
            self._state = alert.state
            self._sync()


def _log_alert(alert: lt.alert,
               message: str = "",
               args: Iterable[Any] = (),
               method=None):
    prefix = "%s"
    prefix_args = [alert.__class__.__name__]
    torrent_name = getattr(alert, "torrent_name", None)
    error = getattr(alert, "error", None)
    if torrent_name and torrent_name not in alert.message():
        prefix += ": %s"
        prefix_args += [torrent_name]
    if alert.message():
        prefix += ": %s"
        prefix_args += [alert.message()]
    if error and error.value():
        prefix += " [%s (%s %d)]"
        prefix_args += [error.message(), error.category().name(), error.value()]
        if method is None:
            method = _log.error
    if method is None:
        method = _log.debug

    if message:
        message = prefix + ": " + message
    else:
        message = prefix

    args = prefix_args + list(args)

    method(message, *args)


Fetch = Callable[[str, Any], bytes]


class IOService:

    def __init__(self,
                 *,
                 session: lt.session = None,
                 get_config: Optional[GetConfig] = None,
                 fetch: Optional[Fetch] = None):
        assert session is not None
        assert get_config is not None
        assert fetch is not None

        self._session = session
        self.get_config = get_config
        self.fetch = fetch

        # One lock for both top-level and per-torrent operations. I have not
        # yet implemented a proper locking protocol between IOService and
        # _Torrent.
        self._lock = threading.RLock()
        self._torrents: Dict[str, _Torrent] = dict()
        self._torrents_by_handle: Dict[lt.torrent_handle, _Torrent] = dict()
        if _have_bug_4604():
            self._post_torrent_updates_deadline = -math.inf
            self._tick_deadline = -math.inf
        else:
            self._post_torrent_updates_deadline = math.inf
            self._tick_deadline = math.inf

    @staticmethod
    def get_alert_mask() -> int:
        return (lt.alert_category.status | lt.alert_category.piece_progress)

    def get_post_torrent_updates_deadline(self) -> float:
        with self._lock:
            return self._post_torrent_updates_deadline

    def on_fired_post_torrent_updates(self):
        if not _have_bug_4604():
            return

        with self._lock:
            self._post_torrent_updates_deadline = time.time(
            ) + _4604_TICK_INTERVAL

    @staticmethod
    def get_post_torrent_updates_flags():
        return 0

    def get_tick_deadline(self) -> float:
        with self._lock:
            return self._tick_deadline

    def tick(self):
        if not _have_bug_4604():
            return

        with self._lock:
            self._tick_deadline = time.time() + _4604_TICK_INTERVAL
            for torrent in self._torrents.values():
                torrent.tick()

    def add_request(
            self,
            *,
            params: Optional[RequestParams] = None,
            infohash: Optional[str] = None,
            fetch_params: Any = None,
            start: Optional[int] = None,
            stop: Optional[int] = None,
            acct_params: Any = None,
            mode: Optional[RequestMode] = None,
    ) -> Request:
        with self._lock:
            if params is None:
                assert infohash is not None
                assert start is not None
                assert stop is not None
                assert mode is not None
                params = RequestParams(infohash=infohash,
                                       start=start,
                                       stop=stop,
                                       mode=mode,
                                       fetch_params=fetch_params,
                                       acct_params=acct_params)
            torrent = self._torrents.get(params.infohash)
            if not torrent:
                torrent = _Torrent(ios=self, infohash=params.infohash)
                self._torrents[params.infohash] = torrent
            return torrent.add_request(params)

    def add_torrent(self, atp: lt.add_torrent_params):
        with self._lock:
            infohash = str(atp.info_hash)
            if infohash in self._torrents:
                raise KeyError(infohash)
            self._torrents[infohash] = _Torrent(ios=self,
                                                add_torrent_params=atp)

    def remove_torrent(self, infohash: str, remove_data: bool = False):
        with self._lock:
            torrent = self._torrents[infohash]
            torrent.request_removal(remove_data=remove_data)

    def _filter_alert(self, alert: lt.alert):
        # libtorrent fires read_piece_alert with an "Operation cancelled" error
        # whenever we change alert_when_available state. Not useful to us.
        if isinstance(alert, lt.read_piece_alert):
            error = alert.error
            if (error.category(), error.value()) == (lt.generic_category(),
                                                     125):
                return False
        return True

    def _get_torrent_for_handle(self, handle: lt.torrent_handle):
        with self._lock:
            torrent = self._torrents_by_handle.get(handle)
            if not torrent:
                infohash = str(handle.info_hash())
                torrent = self._torrents.get(infohash)
            return torrent

    def _handle_state_update_alert(self, alert: lt.state_update_alert):
        with self._lock:
            for status in alert.status:
                torrent = self._get_torrent_for_handle(status.handle)
                if not torrent:
                    _log.warning("state update for torrent we don't have? %s",
                                 str(status.handle.info_hash()))
                    continue
                torrent.handle_status_update(status)

    def handle_alert(self, alert: lt.alert):
        if not self._filter_alert(alert):
            return
        type_name = alert.__class__.__name__
        if isinstance(alert, lt.torrent_alert):
            handle = alert.handle
            with self._lock:
                torrent = self._get_torrent_for_handle(handle)
                if not torrent:
                    # Some alerts are expected after we've totally removed the
                    # torrent.
                    if not isinstance(
                            alert,
                        (lt.torrent_deleted_alert, lt.torrent_log_alert)):
                        _log_alert(alert,
                                   method=_log.warning,
                                   message="alert for torrent we don't have?")
                    return
                self._torrents_by_handle[handle] = torrent
            handler = getattr(torrent, "handle_" + type_name, None)
        else:
            handler = getattr(self, "_handle_" + type_name, None)
        _log_alert(alert)
        if handler:
            handler(alert)
