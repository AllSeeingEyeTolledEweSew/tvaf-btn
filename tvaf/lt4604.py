import logging
from typing import Optional
from typing import Set
import warnings

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import task as task_lib

# In libtorrent bug 4604, piece hashing jobs can get cancelled, and will not be
# re-run until the torrent is force-rechecked. Download counters may indicate
# 100% completion, but the torrent never enters the "finished" state and
# piece_finished_alerts are missing.

# Our strategy is: if a torrent is paused while in a downloading state, we
# check the set of pieces that are downloaded but not yet hashed, then check
# again 3s later. If any are still pending after waiting, we assume their jobs
# were lost, and we force-recheck the torrent.

# This approach lets us avoid subscribing to piece_progress alerts.

HAVE_BUG = ltpy.version_info < (1, 2, 7)
_LOG = logging.getLogger(__name__)
_HASH_TIMEOUT = 3
_ISSUE_URL = "https://github.com/arvidn/libtorrent/issues/4604"
_ISSUE_TITLE = "libtorrent bug 4604 (%s)" % _ISSUE_URL


def get_pending_pieces(handle: lt.torrent_handle) -> Set[int]:
    with ltpy.translate_exceptions():
        # DOES block
        download_queue = handle.get_download_queue()

    # Block state 3 indicates the block has been written to disk. All
    # blocks being in state 3 indicates the piece will have been submitted
    # for hashing.
    pieces = set()
    for piece_info in download_queue:
        if all(block["state"] == 3 for block in piece_info["blocks"]):
            pieces.add(piece_info["piece_index"])
    return pieces


class _CheckTask(task_lib.Task):
    def __init__(self, handle: lt.torrent_handle):
        super().__init__(
            title=f"lt4604 check for {handle.info_hash()}", forever=False
        )
        self._handle = handle

    def _terminate(self):
        pass

    def _run_inner(self):
        pending_before = get_pending_pieces(self._handle)
        if self._terminated.wait(timeout=_HASH_TIMEOUT):
            return
        pending_pieces = pending_before & get_pending_pieces(self._handle)
        if not pending_pieces:
            return

        with ltpy.translate_exceptions():
            _LOG.warning(
                "%s: Working around %s: pieces %s have been downloaded but "
                "still pending hash check for %ss. Assuming their hash jobs "
                "have been lost; force-rechecking the torrent to recover the "
                "lost jobs. You should upgrade to libtorrent>=1.2.7",
                self._handle.name(),
                _ISSUE_TITLE,
                pending_pieces,
                _HASH_TIMEOUT,
            )
            # Does not block
            self._handle.force_recheck()

    def _run(self):
        try:
            self._run_inner()
        except ltpy.InvalidTorrentHandleError:
            pass


class _TorrentTask(task_lib.Task):
    def __init__(
        self,
        *,
        alert_driver: driver_lib.AlertDriver,
        start: lt.alert,
        handle: lt.torrent_handle,
        pedantic=False,
    ):
        super().__init__(
            title=f"lt4604 fixup monitor for {handle.info_hash()}"
        )
        self._pedantic = pedantic
        self._iterator = alert_driver.iter_alerts(
            lt.alert_category.status,
            lt.state_changed_alert,
            lt.torrent_removed_alert,
            lt.torrent_paused_alert,
            handle=handle,
            start=start,
        )

    def _terminate(self):
        self._iterator.close()

    def _handle_alert(self, alert: lt.alert):
        if isinstance(alert, lt.state_changed_alert):
            if alert.state != lt.torrent_status.states.downloading:
                self.terminate()
        elif isinstance(alert, lt.torrent_removed_alert):
            self.terminate()
        elif isinstance(alert, lt.torrent_paused_alert):
            self._add_child(
                _CheckTask(alert.handle), terminate_me_on_error=self._pedantic
            )

    def _run(self):
        with self._iterator:
            for alert in self._iterator:
                self._handle_alert(alert)


class Fixup(task_lib.Task):
    def __init__(
        self, *, alert_driver: driver_lib.AlertDriver, pedantic=False
    ):
        super().__init__(
            title="lt4604 fixup session monitor", thread_name="lt4604.fixup"
        )
        self._pedantic = pedantic
        self._alert_driver = alert_driver
        if HAVE_BUG:
            self._iterator: Optional[
                driver_lib.Iterator
            ] = alert_driver.iter_alerts(
                lt.alert_category.status, lt.state_changed_alert
            )
        else:
            self._iterator = None

    def _terminate(self):
        if self._iterator:
            self._iterator.close()

    def _run(self):
        if not HAVE_BUG:
            self._terminated.wait()
        else:
            warnings.warn(
                "libtorrent with bug #4604 detected. "
                "Please upgrade to libtorrent 1.2.7 or later."
            )
            assert self._iterator
            with self._iterator:
                for alert in self._iterator:
                    assert isinstance(alert, lt.state_changed_alert)
                    if alert.state == lt.torrent_status.states.downloading:
                        self._add_child(
                            _TorrentTask(
                                alert_driver=self._alert_driver,
                                start=alert,
                                handle=alert.handle,
                                pedantic=self._pedantic,
                            ),
                            terminate_me_on_error=self._pedantic,
                        )
