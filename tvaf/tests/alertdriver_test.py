import threading
import unittest
import unittest.mock

from tvaf import driver as driver_lib

from . import lib
from . import tdummy
from . import test_utils


class DummyException(Exception):
    pass


class PumpAlertsTest(unittest.TestCase):

    def setUp(self):
        self.session = test_utils.create_isolated_session()
        self.driver = driver_lib.AlertDriver(session=self.session)

    def test_pump_alerts(self):
        handle = self.session.add_torrent(tdummy.DEFAULT.atp())
        self.session.remove_torrent(handle)

        seen_alerts = []

        def handler(alert):
            type_name = alert.__class__.__name__
            if type_name in ("add_torrent_alert", "torrent_removed_alert"):
                seen_alerts.append(type_name)

        self.driver.add(handler)
        for _ in lib.loop_until_timeout(5):
            self.driver.pump_alerts()
            if "torrent_removed_alert" in seen_alerts:
                break

        self.assertEqual(seen_alerts,
                         ["add_torrent_alert", "torrent_removed_alert"])

    def test_pump_alerts_with_exception(self):

        def handler(alert):
            raise DummyException("whoops")

        self.driver.add(handler)
        with self.assertRaises(DummyException):
            for _ in lib.loop_until_timeout(5):
                self.driver.pump_alerts()


class RunTest(unittest.TestCase):

    def setUp(self):
        self.session = test_utils.create_isolated_session()
        self.driver = driver_lib.AlertDriver(session=self.session)

    def test_run(self):
        handle = self.session.add_torrent(tdummy.DEFAULT.atp())
        self.session.remove_torrent(handle)

        seen_alerts = []

        def handler(alert):
            type_name = alert.__class__.__name__
            if type_name in ("add_torrent_alert", "torrent_removed_alert"):
                seen_alerts.append(type_name)
            if type_name == "torrent_removed_alert":
                self.driver.abort()

        self.driver.add(handler)

        with unittest.mock.patch.object(self.driver, "ABORT_CHECK_INTERVAL",
                                        0.1):
            self.driver.run()

        self.assertEqual(seen_alerts,
                         ["add_torrent_alert", "torrent_removed_alert"])

    def test_run_fed_by_thread(self):

        def run_in_thread():
            handle = self.session.add_torrent(tdummy.DEFAULT.atp())
            self.session.remove_torrent(handle)

        thread = threading.Thread(target=run_in_thread)

        seen_alerts = []

        def handler(alert):
            if thread.ident is None:
                thread.start()
            type_name = alert.__class__.__name__
            if type_name in ("add_torrent_alert", "torrent_removed_alert"):
                seen_alerts.append(type_name)
            if type_name == "torrent_removed_alert":
                self.driver.abort()

        self.driver.add(handler)

        with unittest.mock.patch.object(self.driver, "ABORT_CHECK_INTERVAL",
                                        0.1):
            self.driver.run()
        thread.join()

        self.assertEqual(seen_alerts,
                         ["add_torrent_alert", "torrent_removed_alert"])

    def test_run_with_failer(self):
        handle = self.session.add_torrent(tdummy.DEFAULT.atp())
        self.session.remove_torrent(handle)

        seen_alerts = []

        def handler(alert):
            type_name = alert.__class__.__name__
            if type_name in ("add_torrent_alert", "torrent_removed_alert"):
                seen_alerts.append(type_name)
            if type_name == "torrent_removed_alert":
                self.driver.abort()

        self.driver.add(handler)

        def failer(alert):
            raise Exception("whoopsie")

        self.driver.add(failer)

        with unittest.mock.patch.object(self.driver, "ABORT_CHECK_INTERVAL",
                                        0.1):
            self.driver.run()

        self.assertEqual(seen_alerts,
                         ["add_torrent_alert", "torrent_removed_alert"])


class ThreadTest(unittest.TestCase):

    def setUp(self):
        self.session = test_utils.create_isolated_session()
        self.driver = driver_lib.AlertDriver(session=self.session)

    def test_thread(self):
        handle = self.session.add_torrent(tdummy.DEFAULT.atp())
        self.session.remove_torrent(handle)

        seen_alerts = []

        def handler(alert):
            type_name = alert.__class__.__name__
            if type_name in ("add_torrent_alert", "torrent_removed_alert"):
                seen_alerts.append(type_name)
            if type_name == "torrent_removed_alert":
                self.driver.abort()

        self.driver.add(handler)

        with unittest.mock.patch.object(self.driver, "ABORT_CHECK_INTERVAL",
                                        0.1):
            self.driver.start()
            self.driver.wait()

        self.assertEqual(seen_alerts,
                         ["add_torrent_alert", "torrent_removed_alert"])

    def test_thread_fed_by_thread(self):

        def run_in_thread():
            handle = self.session.add_torrent(tdummy.DEFAULT.atp())
            self.session.remove_torrent(handle)

        thread = threading.Thread(target=run_in_thread)

        seen_alerts = []

        def handler(alert):
            if thread.ident is None:
                thread.start()
            type_name = alert.__class__.__name__
            if type_name in ("add_torrent_alert", "torrent_removed_alert"):
                seen_alerts.append(type_name)
            if type_name == "torrent_removed_alert":
                self.driver.abort()

        self.driver.add(handler)

        with unittest.mock.patch.object(self.driver, "ABORT_CHECK_INTERVAL",
                                        0.1):
            self.driver.start()
            self.driver.wait()
        thread.join()

        self.assertEqual(seen_alerts,
                         ["add_torrent_alert", "torrent_removed_alert"])
