import concurrent.futures
import contextlib
import gc
import tempfile
import threading
import unittest
from typing import List
from typing import Optional
from typing import Type

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import session as session_lib
from tvaf import util

from . import lib
from . import tdummy


@contextlib.contextmanager
def make_some_alerts():
    session = lib.create_isolated_session_service(
        alert_mask=lt.alert_category.session_log).session
    alert = session.wait_for_alert(10000)
    assert alert is not None
    alerts = session.pop_alerts()
    yield alerts
    # NB: session stays alive until the context exits, because this stack frame
    # references it


def executor():
    return concurrent.futures.ThreadPoolExecutor()


# NB: We'd like to test that iterators don't hold any unintended references to
# alerts, but this is hard to test because exceptions refer to stack frames
# which refer to alerts in many cases, including StopIteration.


class IteratorTest(unittest.TestCase):

    def test_close_inline_is_safe(self):
        iterator = driver_lib.Iterator()

        def iterate_and_close():
            for _ in iterator:
                iterator.close()

        future = executor().submit(iterate_and_close)
        with make_some_alerts() as alerts:
            iterator.feed(*alerts)
            future.result()
        self.assertTrue(iterator.is_closed())
        # We exited naturally, so we should be marked safe
        self.assertTrue(iterator.is_safe())

    def test_break_context_manager_is_safe(self):
        iterator = driver_lib.Iterator()

        def iterate_and_close():
            with iterator:
                for _ in iterator:
                    break

        future = executor().submit(iterate_and_close)
        with make_some_alerts() as alerts:
            iterator.feed(*alerts)
            future.result()
        self.assertTrue(iterator.is_closed())
        # We exited from a context manager, so we should be marked safe
        self.assertTrue(iterator.is_safe())

    def test_visit_order(self):
        iterator = driver_lib.Iterator()

        def iterate_and_close():
            message = None
            for alert in iterator:
                message = alert.message()
                iterator.close()
            return message

        future = executor().submit(iterate_and_close)
        with make_some_alerts() as alerts:
            iterator.feed(*alerts)
            expected_message = alerts[0].message()
            self.assertEqual(future.result(), expected_message)

    def test_feed_marks_unsafe(self):
        iterator = driver_lib.Iterator()
        with make_some_alerts() as alerts:
            result = iterator.feed(*alerts)
        self.assertTrue(result)
        self.assertFalse(iterator.is_safe())

    def test_feed_empty_not_unsafe(self):
        iterator = driver_lib.Iterator()
        result = iterator.feed()
        self.assertFalse(result)
        self.assertTrue(iterator.is_safe())

    def test_feed_after_close(self):
        iterator = driver_lib.Iterator()
        iterator.close()
        with make_some_alerts() as alerts:
            result = iterator.feed(*alerts)
        self.assertFalse(result)
        self.assertTrue(iterator.is_safe())

    def test_close(self):
        iterator = driver_lib.Iterator()
        iterator.close()
        self.assertTrue(iterator.is_closed())
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_close_twice(self):
        iterator = driver_lib.Iterator()
        iterator.close()
        iterator.close(Exception())
        self.assertTrue(iterator.is_closed())
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_safe(self):
        iterator = driver_lib.Iterator()
        with make_some_alerts() as alerts:
            iterator.feed(*alerts)
            iterator.close()
        self.assertFalse(iterator.is_safe())
        iterator.set_safe()
        self.assertTrue(iterator.is_safe())

    def test_safe_without_close(self):
        iterator = driver_lib.Iterator()
        with make_some_alerts() as alerts:
            iterator.feed(*alerts)
        with self.assertRaises(ValueError):
            iterator.set_safe()

    def test_safe_notify(self):
        iterator = driver_lib.Iterator()
        rfile, wfile = util.selectable_pipe()
        iterator.set_notify_safe_file(wfile)
        with make_some_alerts() as alerts:
            iterator.feed(*alerts)
            iterator.close()
        # Not safe, not notified
        self.assertFalse(iterator.is_safe())
        self.assertEqual(rfile.read(), None)

        iterator.set_safe()
        # We become safe, and should be notified
        self.assertTrue(iterator.is_safe())
        self.assertNotEqual(rfile.read(), None)

        # Second call to set_safe shouldn't notify again
        iterator.set_safe()
        self.assertEqual(rfile.read(), None)

    def test_safe_notify_return(self):
        iterator = driver_lib.Iterator()
        _, wfile = util.selectable_pipe()
        initial = iterator.set_notify_safe_file(wfile)
        self.assertEqual(initial, None)

        previous = iterator.set_notify_safe_file(None)
        self.assertEqual(previous, wfile)


class Pumper(threading.Thread):

    def __init__(self, driver: driver_lib.AlertDriver):
        super().__init__()
        self.driver = driver
        self.stopped = threading.Event()

    def run(self):
        while not self.stopped.is_set():
            self.driver.pump_alerts()

    def shutdown(self):
        self.stopped.set()
        self.join()


class PumpAlertsConcurrencyTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def do_concurrency_test(self, flags):
        session_service = lib.create_isolated_session_service()
        session = session_service.session
        driver = driver_lib.AlertDriver(session_service=session_service)
        pumper = Pumper(driver)

        # Do some combination of possible concurrent things
        if flags & 1:
            driver.pump_alerts()
        iterator = driver.iter_alerts(lt.alert_category.status,
                                      lt.add_torrent_alert)
        if flags & 2:
            driver.pump_alerts()
        atp = tdummy.DEFAULT.atp()
        atp.save_path = self.tempdir.name
        session.async_add_torrent(atp)
        pumper.start()

        saw_add_alert = False
        with iterator:
            for alert in iterator:
                if isinstance(alert, lt.add_torrent_alert):
                    saw_add_alert = True
                    break
                assert False, f"saw unexpected {alert}"

        self.assertTrue(saw_add_alert)
        pumper.shutdown()

    def test_concurrency(self):
        for flags in range(4):
            self.do_concurrency_test(flags)


class IterAlertsTest(unittest.TestCase):

    def setUp(self):
        self.config = lib.create_isolated_config()
        # Always enable session log, for iterator tests requiring alerts
        self.session_service = session_lib.SessionService(
            config=self.config, alert_mask=lt.alert_category.session_log)
        self.session = self.session_service.session
        self.driver = driver_lib.AlertDriver(
            session_service=self.session_service)
        self.pumper = Pumper(self.driver)
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_iter_alerts(self):
        iterator = self.driver.iter_alerts(lt.alert_category.status,
                                           lt.add_torrent_alert)
        atp = tdummy.DEFAULT.atp()
        atp.save_path = self.tempdir.name
        self.session.async_add_torrent(atp)
        self.pumper.start()

        saw_add_alert = False
        with iterator:
            for alert in iterator:
                if isinstance(alert, lt.add_torrent_alert):
                    saw_add_alert = True
                    break
                assert False, f"saw unexpected {alert}"

        self.assertTrue(saw_add_alert)
        self.pumper.shutdown()

    def test_fork_with_handle(self):
        self.pumper.start()

        iterator = self.driver.iter_alerts(lt.alert_category.status,
                                           lt.add_torrent_alert)
        # Trigger add and remove
        atp = tdummy.DEFAULT.atp()
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        self.session.remove_torrent(handle)
        forkee_saw_types: List[Type[lt.alert]] = []
        forkee: Optional[threading.Thread] = None

        def watch_handle(handle_iterator: driver_lib.Iterator):
            with handle_iterator:
                for alert in handle_iterator:
                    forkee_saw_types.append(alert.__class__)
                    if isinstance(alert, lt.torrent_removed_alert):
                        break

        with iterator:
            for alert in iterator:
                if isinstance(alert, lt.add_torrent_alert):
                    # Fork a task to watch add and remove alerts on this handle
                    handle_iterator = self.driver.iter_alerts(
                        lt.alert_category.status,
                        lt.add_torrent_alert,
                        lt.torrent_removed_alert,
                        handle=alert.handle,
                        start=alert)
                    forkee = threading.Thread(target=watch_handle,
                                              args=(handle_iterator,))
                    forkee.start()
                    break
                assert False, f"saw unexpected {alert}"

        self.assertIsNotNone(forkee)
        forkee.join()
        self.assertTrue(forkee_saw_types,
                        [lt.add_torrent_alert, lt.torrent_removed_alert])
        self.pumper.shutdown()

    def test_dead_iterator_detection(self):
        iterator = self.driver.iter_alerts(lt.alert_category.session_log)
        # Feed iterator some alerts
        self.driver.pump_alerts()
        self.assertFalse(iterator.is_safe())
        # Let iterator die without closing
        del iterator
        # Not necessary as of writing, but good defense
        gc.collect()
        # Should detect the dead iterator, and eventually proceed
        self.driver.pump_alerts()
        # NB: This test may fail for reasons that are meaningless in production
        # (I saw pytest's logger hold a reference due to log("%s", iterator)),
        # but I still think this test is useful as I want to catch *any*
        # unexpected references, so dead iterator protection works as well as
        # it can

    def test_checkpoint_timeout(self):
        iterator = self.driver.iter_alerts(lt.alert_category.session_log)
        # Feed iterator some alerts
        self.driver.pump_alerts()
        self.assertFalse(iterator.is_safe())
        # Second pump should wait for a checkpoint after the first pump, which
        # never comes
        with self.assertRaises(driver_lib.CheckpointTimeout):
            self.driver.pump_alerts(timeout=0.1)


class DriverTest(unittest.TestCase):

    def setUp(self):
        self.session_service = lib.create_isolated_session_service()
        self.driver = driver_lib.AlertDriver(
            session_service=self.session_service)

    def test_start_and_close(self):
        self.driver.start()
        iterator = self.driver.iter_alerts(lt.alert_category.session_log)
        # Consume iterator
        future = executor().submit(list, iterator)
        self.driver.terminate()
        with self.assertRaises(driver_lib.DriverShutdown):
            future.result()
        self.driver.join()

        # Further iter_alerts should fail
        with self.assertRaises(driver_lib.DriverShutdown):
            self.driver.iter_alerts(lt.alert_category.session_log)
