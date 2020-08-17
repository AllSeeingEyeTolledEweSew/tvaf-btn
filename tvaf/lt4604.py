import concurrent.futures
import logging
import math
import threading
import time
import warnings
from typing import Dict
from typing import Optional

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import ltpy

# In libtorrent bug 4604, piece hashing jobs can get cancelled, and will not be
# re-run until the torrent is force-rechecked. Download counters may indicate
# 100% completion, but the torrent never enters the "finished" state and
# piece_finished_alerts are missing.

# Our strategy is: if a torrent remains in a state where we expect pieces to be
# hashed, but it has been more than 3s since we have seen any new hashes, then
# we run an expensive check to see if any data is still waiting to be hashed.
# If so, we force-recheck the torrent.

# NB: This may arrive at a false positive if the last block in a piece finishes
# writing to disk just before we run our check *and* the torrent is downloading
# slowly. We could instead run our check 3s after we see the last block written
# to disk (i.e. reset our timer on block_finished_alert, not just
# piece_finished_alert), but subscribing to block alerts would be a huge
# increase in python processing, and a spurious force-recheck is Not That Bad,
# and we could still get unlucky with the timing of the last block.

HAVE_BUG = (tuple(int(i) for i in lt.version.split(".")) < (1, 2, 7))
_LOG = logging.getLogger(__name__)
_HASH_TIMEOUT = 3
_HASHING_STATES = (lt.torrent_status.states.downloading,
                   lt.torrent_status.states.checking_files)
_ISSUE_URL = "https://github.com/arvidn/libtorrent/issues/4604"
_ISSUE_TITLE = "libtorrent bug 4604 (%s)" % _ISSUE_URL


class _Torrent(driver_lib.Ticker):

    def __init__(self, *, handle: lt.torrent_handle,
                 executor: concurrent.futures.Executor,
                 tick_driver: driver_lib.TickDriver):
        self._handle = handle
        self._executor = executor
        self._tick_driver = tick_driver

        self._lock = threading.RLock()
        self._recheck_latched = False
        self._recheck_deadline: float = -math.inf
        self._recheck_future: Optional[concurrent.futures.Future] = None

    def latch_recheck(self):
        deadline = time.monotonic() + _HASH_TIMEOUT
        with self._lock:
            if deadline < self._recheck_deadline:
                return
            self.cancel_recheck()
            self._recheck_latched = True
            self._recheck_deadline = deadline
            self._tick_driver.add(self)

    def cancel_recheck(self):
        with self._lock:
            if self._recheck_future is not None:
                self._recheck_future.cancel()
                self._recheck_future = None
            self._tick_driver.discard(self)
            self._recheck_deadline = -math.inf
            self._recheck_latched = False

    def _maybe_recheck(self):
        with ltpy.translate_exceptions():
            _LOG.info(
                "%s: Gone a long time with no new pieces, doing a thorough "
                "check for %s", self._handle.name(), _ISSUE_TITLE)

            status = self._handle.status(flags=0)

            # Torrents in an error state may have failed hashes for some reason
            # unrelated to 4604. Ignore them.
            if status.errc.value() != 0:
                _LOG.info("%s: In error state (%s), ignoring %s",
                          self._handle.name(), status.errc.message(),
                          _ISSUE_TITLE)
                return

            download_queue = self._handle.get_download_queue()

        # Block state 3 indicates the block has been written to disk. All
        # blocks being in state 3 indicates the piece will have been submitted
        # for hashing.
        pending_pieces = 0
        for piece_info in download_queue:
            if all(block["state"] == 3 for block in piece_info["blocks"]):
                pending_pieces += 1

        if pending_pieces == 0:
            _LOG.info("%s: No pieces pending hash. Doesn't look like %s",
                      self._handle.name(), _ISSUE_TITLE)
            return

        with self._lock:
            # Check if we latched a new recheck while we were doing the
            # calculation
            if self._recheck_latched:
                _LOG.info(
                    "%s: %d pieces pending hash, but we had activity since we "
                    "started running the check. Will check again later...",
                    self._handle.name(), pending_pieces)
                return

            with ltpy.translate_exceptions():
                _LOG.warning(
                    "%s: Working around %s: there are %d pieces pending hash, "
                    "and %s seconds since the last successful hash. "
                    "Force-rechecking the torrent to recover lost hash jobs. "
                    "You should upgrade to libtorrent>=1.2.7",
                    self._handle.name(), _ISSUE_TITLE, pending_pieces,
                    _HASH_TIMEOUT)
                # Does not block
                self._handle.force_recheck()

    def get_tick_deadline(self) -> float:
        with self._lock:
            if not self._recheck_latched:
                return math.inf
            return self._recheck_deadline

    def tick(self, now: float):
        with self._lock:
            assert self._recheck_latched
            # Ensure we didn't latch a new deadline
            if now < self._recheck_deadline:
                return
            self.cancel_recheck()

            def log_exceptions(future: concurrent.futures.Future):
                assert future.done()
                try:
                    future.result()
                except concurrent.futures.CancelledError:
                    pass
                except ltpy.InvalidTorrentHandleError:
                    # The torrent was removed while we were checking; no need
                    # to log anything
                    pass
                except Exception:
                    _LOG.exception("while rechecking")

            self._recheck_future = self._executor.submit(self._maybe_recheck)
            self._recheck_future.add_done_callback(log_exceptions)


class Fixup:

    def __init__(self, *, tick_driver: driver_lib.TickDriver):
        self._executor = concurrent.futures.ThreadPoolExecutor()
        self._torrents_by_handle: Dict[lt.torrent_handle, _Torrent] = {}
        self._tick_driver = tick_driver
        self._lock = threading.RLock()

    def get_alert_mask(self) -> int:
        # pylint: disable=no-self-use
        if HAVE_BUG:
            return (lt.alert.category_t.piece_progress_notification |
                    lt.alert.category_t.status_notification)
        return 0

    def _remove(self, handle: lt.torrent_handle):
        with self._lock:
            torrent = self._torrents_by_handle.pop(handle, None)
        if torrent is not None:
            _LOG.debug("%s: No longer at risk of %s", handle.info_hash(),
                       _ISSUE_TITLE)
            torrent.cancel_recheck()

    def _get(self, handle: lt.torrent_handle) -> Optional[_Torrent]:
        with self._lock:
            return self._torrents_by_handle.get(handle)

    def _ensure(self, handle: lt.torrent_handle) -> _Torrent:
        with self._lock:
            torrent = self._get(handle)
            if torrent is None:
                _LOG.debug("%s: Keeping an eye out for %s", handle.info_hash(),
                           _ISSUE_TITLE)
                torrent = _Torrent(handle=handle,
                                   executor=self._executor,
                                   tick_driver=self._tick_driver)
                self._torrents_by_handle[handle] = torrent
            return torrent

    def _handle_state_change(self, handle: lt.torrent_handle,
                             state: lt.torrent_status.states):
        if state in _HASHING_STATES:
            self._ensure(handle).latch_recheck()
        else:
            self._remove(handle)

    def handle_state_changed_alert(self, alert: lt.state_changed_alert):
        with ltpy.translate_exceptions():
            handle = alert.handle
            state = alert.state
        self._handle_state_change(handle, state)

    def handle_torrent_removed_alert(self, alert: lt.torrent_removed_alert):
        with ltpy.translate_exceptions():
            handle = alert.handle
        self._remove(handle)

    def handle_piece_finished_alert(self, alert: lt.piece_finished_alert):
        with ltpy.translate_exceptions():
            handle = alert.handle
        torrent = self._get(handle)
        if torrent:
            torrent.latch_recheck()

    def handle_alert(self, alert: lt.alert):
        if not HAVE_BUG:
            return
        driver_lib.dispatch(self, alert)

    def start(self):
        # pylint: disable=no-self-use
        if HAVE_BUG:
            warnings.warn("libtorrent with bug #4604 detected. "
                          "Please upgrade to libtorrent 1.2.7 or later.")
