import pathlib
import tempfile
import time
from typing import List
import unittest

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import lt4604
from tvaf import task as task_lib

from . import lib
from . import request_test_utils
from . import tdummy

MANY_PIECES = tdummy.Torrent.single_file(
    piece_length=16384, name=b"test.txt", length=16384 * 100
)


class CaptureStates(task_lib.Task):
    def __init__(self, alert_driver: driver_lib.AlertDriver, stop_state=None):
        super().__init__(title="capture states", forever=False)
        self._iterator = alert_driver.iter_alerts(
            lt.alert_category.status,
            lt.add_torrent_alert,
            lt.torrent_removed_alert,
            lt.state_changed_alert,
        )
        self._stop_state = stop_state
        self.states: List[str] = []

    def _terminate(self):
        self._iterator.close()

    def _run(self):
        with self._iterator:
            for alert in self._iterator:
                if isinstance(alert, lt.add_torrent_alert):
                    self.states.append("checking_resume_data")
                elif isinstance(alert, lt.state_changed_alert):
                    state = alert.state.name
                    self.states.append(state)
                    if state == self._stop_state:
                        self._iterator.close()
                elif isinstance(alert, lt.torrent_removed_alert):
                    self._iterator.close()


class Test4604(unittest.TestCase):

    maxDiff = None

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.config_dir = pathlib.Path(self.dir.name)
        self.session_service = lib.create_isolated_session_service()
        self.session = self.session_service.session
        self.alert_driver = driver_lib.AlertDriver(
            session_service=self.session_service
        )
        self.fixup = lt4604.Fixup(
            alert_driver=self.alert_driver, pedantic=True
        )

    def tearDown(self):
        self.session.pause()
        self.fixup.terminate()
        self.fixup.join()
        self.alert_driver.terminate()
        self.alert_driver.join()

        self.dir.cleanup()

    def start(self):
        self.fixup.start()
        self.alert_driver.start()

    def trigger_4604(self):
        atp = lt.add_torrent_params()
        atp.ti = MANY_PIECES.torrent_info()
        atp.save_path = self.dir.name
        atp.flags &= ~lt.torrent_flags.paused

        handle = self.session.add_torrent(atp)
        request_test_utils.wait_done_checking_or_error(handle)

        for i, piece in enumerate(MANY_PIECES.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        handle.pause(flags=0)
        handle.resume()

        return handle

    def test_4604(self):
        capture = CaptureStates(self.alert_driver, stop_state="seeding")
        capture.start()

        self.trigger_4604()

        self.start()

        capture.result(timeout=10)
        states = capture.states

        if lt4604.HAVE_BUG:
            # Test we actually triggered the bug
            self.assertEqual(
                states,
                [
                    "checking_resume_data",
                    "downloading",
                    "checking_resume_data",
                    "checking_files",
                    "finished",
                    "seeding",
                ],
            )
        else:
            self.assertEqual(
                states,
                [
                    "checking_resume_data",
                    "downloading",
                    "finished",
                    "seeding",
                ],
            )

    def test_4604_and_remove(self):
        self.trigger_4604()

        iterator = self.alert_driver.iter_alerts(
            lt.alert_category.status,
            lt.torrent_removed_alert,
            lt.torrent_paused_alert,
        )
        self.start()
        for alert in iterator:
            if isinstance(alert, lt.torrent_removed_alert):
                iterator.close()
            elif isinstance(alert, lt.torrent_paused_alert):
                self.session.remove_torrent(alert.handle)

        # Just ensure we didn't terminate with an error
        self.fixup.terminate()
        self.fixup.result()

    def test_4604_just_slow(self):
        atp = lt.add_torrent_params()
        atp.ti = MANY_PIECES.torrent_info()
        atp.save_path = self.dir.name
        atp.flags &= ~lt.torrent_flags.paused

        self.session.async_add_torrent(atp)

        capture = CaptureStates(self.alert_driver)
        capture.start()

        self.start()

        # Just pump events for 5s
        time.sleep(5)

        capture.terminate()
        capture.join()
        states = capture.states

        # Test we never wrongly triggered a recheck
        self.assertEqual(
            states,
            [
                "checking_resume_data",
                "downloading",
            ],
        )
