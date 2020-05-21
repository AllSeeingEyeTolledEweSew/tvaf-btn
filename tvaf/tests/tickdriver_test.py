from tvaf import driver as driver_lib
import contextlib
import unittest
import time
import math
from . import mock_time


class NormalTicker(driver_lib.Ticker):

    def __init__(self, *, last=None, interval=60):
        if last is None:
            last = time.monotonic()
        self.last = last
        self.calls = []
        self.interval = interval

    def tick(self, now:float):
        self.calls.append(now)
        self.last = now

    def get_tick_deadline(self):
        return self.last + self.interval


class AbortingTicker(NormalTicker):

    def __init__(self, driver:driver_lib.TickDriver, *, last=None,
            interval=60,
            abort_at=120):
        super().__init__(last=last, interval=interval)
        self.driver = driver
        self.abort_at = abort_at

    def tick(self, now:float):
        super().tick(now)
        if now >= self.abort_at:
            self.driver.abort()

class FailTicker(NormalTicker):

    def __init__(self, *, last=None, interval=60, fail_tick=True,
            fail_get_tick_deadline=True):
        super().__init__(last=last, interval=interval)
        self.fail_tick = fail_tick
        self.fail_get_tick_deadline = fail_get_tick_deadline

    def tick(self, now:float):
        super().tick(now)
        if self.fail_tick:
            raise Exception("whoops")

    def get_tick_deadline(self):
        if self.fail_get_tick_deadline:
            raise Exception("whoops")
        return super().get_tick_deadline()


class TickDriverTestBase(unittest.TestCase):

    @contextlib.contextmanager
    def mock_time(self, driver, autoincrement=0):
        with mock_time.MockTime(1234, autoincrement=autoincrement) as mocker:
            mocker.patch_condition(driver._condition)
            yield mocker


class TickDriverDeadlinesTest(unittest.TestCase):

    def test_deadlines(self):
        driver = driver_lib.TickDriver()
        self.assertEqual(driver.get_tick_deadline(), math.inf)

        longer = NormalTicker(last=0, interval=60)
        driver.add(longer)
        self.assertEqual(driver.get_tick_deadline(), 60)

        shorter = NormalTicker(last=0, interval=30)
        driver.add(shorter)
        self.assertEqual(driver.get_tick_deadline(), 30)

        failer = FailTicker()
        driver.add(failer)
        self.assertEqual(driver.get_tick_deadline(), -math.inf)

        driver.remove(failer)
        self.assertEqual(driver.get_tick_deadline(), 30)

        driver.remove(shorter)
        self.assertEqual(driver.get_tick_deadline(), 60)

        driver.discard(shorter)
        self.assertEqual(driver.get_tick_deadline(), 60)

        driver.remove(longer)
        self.assertEqual(driver.get_tick_deadline(), math.inf)


class TickDriverIterTicksTest(TickDriverTestBase):

    def test_iter_ticks_with_progression(self):
        driver = driver_lib.TickDriver()
        with self.mock_time(driver):
            ticker = NormalTicker(last=0, interval=60)
            driver.add(ticker)
            for now in driver.iter_ticks():
                ticker.tick(now)
                if now >= 360:
                    driver.abort()
        self.assertEqual(ticker.calls, [60, 120, 180, 240, 300, 360])

    def test_iter_ticks_no_progression(self):
        driver = driver_lib.TickDriver()
        with self.mock_time(driver):
            ticker = NormalTicker(last=0, interval=60)
            driver.add(ticker)
            ticks = []
            for now in driver.iter_ticks():
                ticks.append(now)
                if len(ticks) >= 5:
                    driver.abort()
        self.assertEqual(ticks, [60, 60, 60, 60, 60])

    def test_iter_ticks_forever(self):
        driver = driver_lib.TickDriver()
        with self.mock_time(driver):
            with self.assertRaises(mock_time.WaitForever):
                list(driver.iter_ticks())


class TickDriverRunTest(TickDriverTestBase):

    def test_run_with_progression(self):
        driver = driver_lib.TickDriver()
        with self.mock_time(driver):
            ticker = AbortingTicker(driver=driver, last=0, interval=60,
                    abort_at=360)
            driver.add(ticker)
            driver.run()
        self.assertEqual(ticker.calls, [60, 120, 180, 240, 300, 360])

    def test_run_with_progression_and_failer(self):
        driver = driver_lib.TickDriver()
        # need autoincrement due to infinite spin
        with self.mock_time(driver, autoincrement=1):
            ticker = AbortingTicker(driver=driver, last=0, interval=60,
                    abort_at=360)
            driver.add(ticker)
            driver.add(FailTicker())
            driver.run()
        # check timestamps are off by a consistent amount
        expected = [60, 120, 180, 240, 300, 360]
        deltas = [i - j for i, j in zip(ticker.calls, expected)]
        self.assertEqual(len(set(deltas)), 1)

    def test_run_with_progression_in_thread(self):
        driver = driver_lib.TickDriver()
        with self.mock_time(driver):
            ticker = AbortingTicker(driver=driver, last=0, interval=60,
                    abort_at=360)
            driver.add(ticker)
            driver.start()
            driver.wait()
        self.assertEqual(ticker.calls, [60, 120, 180, 240, 300, 360])

    def test_run_with_progression_in_thread_and_failer(self):
        driver = driver_lib.TickDriver()
        # need autoincrement due to infinite spin
        with self.mock_time(driver, autoincrement=1):
            ticker = AbortingTicker(driver=driver, last=0, interval=60,
                    abort_at=360)
            driver.add(ticker)
            driver.add(FailTicker())
            driver.start()
            driver.wait()
        # check timestamps are off by a consistent amount
        expected = [60, 120, 180, 240, 300, 360]
        deltas = [i - j for i, j in zip(ticker.calls, expected)]
        self.assertEqual(len(set(deltas)), 1)

    def test_run_forever(self):
        driver = driver_lib.TickDriver()
        with self.mock_time(driver):
            with self.assertRaises(mock_time.WaitForever):
                driver.run()
