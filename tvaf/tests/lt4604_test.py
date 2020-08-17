import tempfile
import time
import unittest

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import lt4604

from . import lib
from . import request_test_utils
from . import tdummy
from . import test_utils

MANY_PIECES = tdummy.Torrent.single_file(piece_length=16384,
                                         name=b"test.txt",
                                         length=16384 * 100)


class Test4604(unittest.TestCase):

    maxDiff = None

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.session = test_utils.create_isolated_session()
        self.alert_driver = driver_lib.AlertDriver(session=self.session)
        self.tick_driver = driver_lib.TickDriver()
        self.fixup = lt4604.Fixup(tick_driver=self.tick_driver)
        self.alert_driver.add(self.fixup.handle_alert)

    def tearDown(self):
        self.dir.cleanup()

    def pump_events(self):
        self.tick_driver.tick(time.monotonic())
        return self.alert_driver.pump_alerts()

    def trigger_4604(self, save_path=None):
        atp = lt.add_torrent_params()
        atp.ti = MANY_PIECES.torrent_info()
        if save_path is None:
            save_path = self.dir.name
        atp.save_path = save_path
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
        self.trigger_4604()

        states = []

        def capture_states(alert):
            if isinstance(alert, lt.torrent_added_alert):
                states.append("checking_resume_data")
            if isinstance(alert, lt.state_changed_alert):
                states.append(alert.state.name)

        self.alert_driver.add(capture_states)

        for _ in lib.loop_until_timeout(10, msg="seeding"):
            self.pump_events()
            if "seeding" in states:
                break

        if lt4604.HAVE_BUG:
            # Test we actually triggered the bug
            self.assertEqual(states, [
                "checking_resume_data", "downloading", "checking_resume_data",
                "checking_files", "finished", "seeding"
            ])
        else:
            self.assertEqual(states, [
                "checking_resume_data",
                "downloading",
                "finished",
                "seeding",
            ])

    def test_4604_and_remove(self):
        handle = self.trigger_4604()
        # Just pump events and ensure no exceptions get thrown.
        # Should we test anything else?
        removed = False
        for _ in lib.loop_until_timeout(10, msg="remove"):
            alerts = self.pump_events()
            done = False
            for alert in alerts:
                if isinstance(alert, lt.torrent_removed_alert):
                    done = True
                if isinstance(alert, lt.torrent_paused_alert) and not removed:
                    self.session.remove_torrent(handle)
            if done:
                break

    def test_4604_just_slow(self):
        atp = lt.add_torrent_params()
        atp.ti = MANY_PIECES.torrent_info()
        atp.save_path = self.dir.name
        atp.flags &= ~lt.torrent_flags.paused

        self.session.async_add_torrent(atp)

        states = []

        def capture_states(alert):
            if isinstance(alert, lt.torrent_added_alert):
                states.append("checking_resume_data")
            if isinstance(alert, lt.state_changed_alert):
                states.append(alert.state.name)

        self.alert_driver.add(capture_states)

        # Just pump events for 5s
        start = time.monotonic()
        while time.monotonic() - start < 5:
            self.pump_events()

        # Test we never wrongly triggered a recheck
        self.assertEqual(states, [
            "checking_resume_data",
            "downloading",
        ])
