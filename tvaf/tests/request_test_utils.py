import pathlib
import sys
import tempfile
import time
import unittest

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import driver as driver_lib
from tvaf import request as request_lib
from tvaf import types

from . import tdummy
from . import test_utils


def wait_done_checking_or_error(handle: lt.torrent_handle):
    while True:
        status = handle.status()
        if status.state not in (lt.torrent_status.states.checking_resume_data,
                                lt.torrent_status.states.checking_files):
            break
        if status.errc.value() != 0:
            break


class RequestServiceTestCase(unittest.TestCase):
    """Tests for tvaf.dal.create_schema()."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_dir = pathlib.Path(self.tempdir.name)
        self.config = config_lib.Config(
            torrent_default_save_path=str(self.config_dir))
        self.init_session()

    def init_session(self):
        self.session = test_utils.create_isolated_session()
        self.service = request_lib.RequestService(session=self.session,
                                                  config=self.config,
                                                  config_dir=self.config_dir)

    def tearDown(self):
        self.tempdir.cleanup()

    def pump_alerts(self, condition, msg="condition", timeout=5):
        condition_deadline = time.monotonic() + timeout
        while not condition():
            deadline = min(condition_deadline, self.service.get_tick_deadline())
            timeout = max(deadline - time.monotonic(), 0.0)
            timeout_ms = int(min(timeout * 1000, sys.maxsize))

            self.session.wait_for_alert(int(timeout_ms))

            for alert in self.session.pop_alerts():
                driver_lib.log_alert(alert)
                self.service.handle_alert(alert)
            now = time.monotonic()
            self.assertLess(now, condition_deadline, msg=f"{msg} timed out")
            if now >= self.service.get_tick_deadline():
                self.service.tick(now)

    def feed_pieces(self, piece_indexes=None):
        if not piece_indexes:
            piece_indexes = list(range(len(tdummy.PIECES)))
        handle = self.wait_for_torrent()
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        wait_done_checking_or_error(handle)
        for i in piece_indexes:
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, tdummy.PIECES[i].decode(), 0)

    def read_all(self, req, msg="read all data", timeout=5):
        chunks = []

        def read_and_check():
            while req.has_next():
                chunk = req.get_next(timeout=0)
                if not chunk:
                    break
                chunks.append(bytes(chunk))
            return not req.has_next()

        self.pump_alerts(read_and_check, msg=msg, timeout=timeout)
        return b"".join(chunks)

    def pump_and_find_first_alert(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            alert = self.session.wait_for_alert(
                int((deadline - time.monotonic()) * 1000))
            if not alert:
                assert False, "condition timed out"
            saved = None
            for alert in self.session.pop_alerts():
                self.service.handle_alert(alert)
                if condition(alert) and saved is None:
                    saved = alert
            if saved is not None:
                return saved

    def add_req(self,
                mode=request_lib.Mode.READ,
                infohash=tdummy.INFOHASH,
                start=0,
                stop=len(tdummy.DATA),
                user="tvaf",
                get_torrent=lambda: lt.bencode(tdummy.DICT)):
        tslice = types.TorrentSlice(info_hash=infohash, start=start, stop=stop)
        params = request_lib.Params(tslice=tslice,
                                    mode=mode,
                                    user=user,
                                    get_torrent=get_torrent)
        return self.service.add_request(params)

    def wait_for_torrent(self):

        def find():
            return self.session.find_torrent(tdummy.SHA1_HASH)

        self.pump_alerts(lambda: find().is_valid(), msg="add")
        handle = find()
        self.assertTrue(handle.is_valid())
        return handle
