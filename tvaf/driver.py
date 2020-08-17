import errno
import logging
import math
import threading
import time
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Optional
from typing import Sequence
from typing import Set

import libtorrent as lt

from tvaf import ltpy

AlertHandler = Callable[[lt.alert], None]

_LOG = logging.getLogger(__name__)


def dispatch(obj, alert: lt.alert, prefix="handle_"):
    type_name = alert.__class__.__name__
    handler = getattr(obj, prefix + type_name, None)
    if handler:
        handler(alert)


def log_alert(alert: lt.alert,
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
            method = _LOG.error
    if method is None:
        method = _LOG.debug

    if message:
        message = prefix + ": " + message
    else:
        message = prefix

    args = prefix_args + list(args)

    method(message, *args)


def allow_alert(alert: lt.alert):
    if isinstance(alert, lt.read_piece_alert):
        if (alert.error.category() == lt.generic_category() and
                alert.error.value() == errno.ECANCELED):
            return False
    return True


class AlertDriver:

    ABORT_CHECK_INTERVAL = 1.0

    def __init__(self, *, session: lt.session):
        self.session = session

        self._handlers: Set[AlertHandler] = set()
        self._thread: Optional[threading.Thread] = None
        self._aborted = False

    def add(self, handler: AlertHandler):
        self._handlers.add(handler)

    def remove(self, handler: AlertHandler):
        self._handlers.remove(handler)

    def discard(self, handler: AlertHandler):
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

    def pump_alerts(self, raise_exceptions=True) -> Sequence[lt.alert]:
        with ltpy.translate_exceptions():
            alerts = self.session.pop_alerts()
        for alert in alerts:
            log_alert(alert)
            for handler in list(self._handlers):
                try:
                    handler(alert)
                except Exception:
                    if raise_exceptions:
                        raise
                    _LOG.exception("while handling %s with %s", alert, handler)
        return alerts

    def _run_inner(self):
        while True:
            with ltpy.translate_exceptions():
                self.session.wait_for_alert(
                    int(self.ABORT_CHECK_INTERVAL * 1000))
            self.pump_alerts(raise_exceptions=False)
            if self._aborted:
                break

    def run(self):
        try:
            self._run_inner()
        except Exception:
            _LOG.exception("fatal error")
        finally:
            _LOG.debug("shutting down")


class Ticker:

    def get_tick_deadline(self) -> float:
        # pylint: disable=no-self-use
        return math.inf

    def tick(self, now: float):
        pass


class TickDriver:

    def __init__(self):
        self._tickers: Set[Ticker] = set()
        self._thread: Optional[threading.Thread] = None
        self._condition = threading.Condition(threading.RLock())
        self._aborted = False

    def add(self, ticker: Ticker):
        with self._condition:
            self._tickers.add(ticker)
            self._condition.notify_all()

    def remove(self, ticker: Ticker):
        with self._condition:
            self._tickers.remove(ticker)
            self._condition.notify_all()

    def discard(self, ticker: Ticker):
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

    def tick(self, now: float):
        with self._condition:
            for ticker in list(self._tickers):
                try:
                    if ticker.get_tick_deadline() <= now:
                        ticker.tick(now)
                except Exception:
                    _LOG.exception("during tick")

    def get_tick_deadline(self):
        with self._condition:

            def iter_deadlines():
                yield math.inf
                for ticker in self._tickers:
                    try:
                        yield ticker.get_tick_deadline()
                    except Exception:
                        _LOG.exception("while getting deadline")
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
            _LOG.exception("fatal error")
            raise
        finally:
            _LOG.debug("shutting down")
