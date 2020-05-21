import threading
import time
import math
from typing import Callable
from typing import Optional
from typing import Set
import libtorrent as lt
import logging

AlertHandler = Callable[[lt.alert], None]

_log = logging.getLogger(__name__)


class AlertDriver:

    ABORT_CHECK_INTERVAL = 1.0

    def __init__(self, *, session:Optional[lt.session]=None):
        assert session is not None

        self.session = session

        self._handlers :Set[AlertHandler] = set()
        self._thread:Optional[threading.Thread] = None
        self._aborted = False

    def add(self, handler:AlertHandler):
        self._handlers.add(handler)

    def remove(self, handler:AlertHandler):
        self._handlers.remove(handler)

    def discard(self, handler:AlertHandler):
        self._handlers.discard(handler)

    def start(self):
        assert self._thread is None
        self._thread = threading.Thread(name="alert-driver", target=self.run)
        self._thread.start()

    def abort(self):
        self._aborted = True

    def wait(self):
        assert self._thread is not None
        self._thread.join()

    def iter_alerts(self):
        while True:
            self.session.wait_for_alert(int(self.ABORT_CHECK_INTERVAL * 1000))
            alerts = self.session.pop_alerts()
            if not alerts and self._aborted:
                return
            yield from alerts

    def run_inner(self):
        for alert in self.iter_alerts():
            for handler in list(self._handlers):
                try:
                    handler(alert)
                except Exception:
                    _log.exception("while handling %s with %s", alert, handler)

    def run(self):
        try:
            self.run_inner()
        except Exception:
            _log.exception("fatal error")
        finally:
            _log.debug("shutting down")


class Ticker:

    def get_tick_deadline(self) -> float:
        raise NotImplementedError

    def tick(self, now:float):
        raise NotImplementedError


class TickDriver:

    def __init__(self):
        self._tickers:Set[Ticker] = set()
        self._thread:Optional[threading.Thread] = None
        self._condition = threading.Condition(threading.RLock())
        self._aborted = False

    def add(self, ticker:Ticker):
        with self._condition:
            self._tickers.add(ticker)
            self._condition.notify_all()

    def remove(self, ticker:Ticker):
        with self._condition:
            self._tickers.remove(ticker)
            self._condition.notify_all()

    def discard(self, ticker:Ticker):
        with self._condition:
            self._tickers.discard(ticker)
            self._condition.notify_all()

    def start(self):
        with self._condition:
            assert self._thread is None
            self._thread = threading.Thread(name="tick-driver", target=self.run)
            self._thread.start()

    def abort(self):
        with self._condition:
            self._aborted = True
            self._condition.notify_all()

    def wait(self):
        assert self._thread is not None
        self._thread.join()

    def tick(self, now:float):
        with self._condition:
            for ticker in list(self._tickers):
                try:
                    if ticker.get_tick_deadline() <= now:
                        ticker.tick(now)
                except Exception:
                    _log.exception("during tick")

    def get_tick_deadline(self):
        with self._condition:
            def iter_deadlines():
                yield math.inf
                for ticker in self._tickers:
                    try:
                        yield ticker.get_tick_deadline()
                    except Exception:
                        _log.exception("while getting deadline")
                        yield -math.inf
            return float(min(iter_deadlines()))

    def notify(self):
        with self._condition:
            self._condition.notify_all()

    def iter_ticks(self):
        with self._condition:
            while True:
                now = time.monotonic()
                if self.get_tick_deadline() <= now:
                    yield now
                if self._aborted:
                    return
                timeout = self.get_tick_deadline() - now
                if timeout > 0:
                    if math.isinf(timeout):
                        timeout = None
                    else:
                        timeout = min(timeout, threading.TIMEOUT_MAX)
                    self._condition.wait(timeout)

    def run(self):
        try:
            for now in self.iter_ticks():
                self.tick(now)
        except Exception:
            _log.exception("fatal error")
            raise
        finally:
            _log.debug("shutting down")
