import logging
import time

import libtorrent as lt


def create_isolated_session():
    return lt.session({
        "enable_dht": False,
        "enable_lsd": False,
        "enable_natpmp": False,
        "enable_upnp": False,
        "listen_interfaces": "127.0.0.1:0",
        "alert_mask": -1
    })


class InlineDriver:

    def __init__(self, timeout=5):
        self.timeout = timeout
        self.session = None
        self.tickers = []
        self.handlers = []

    def pump(self, condition, msg="condition", timeout=None):
        if timeout is None:
            timeout = self.timeout
        deadline = time.monotonic() + timeout
        while not condition():
            now = time.monotonic()
            assert now <= deadline, f"{msg} timed out"
            if self.session is not None:
                for alert in self.session.pop_alerts():
                    error = getattr(alert, "error", None)
                    if error and error.value():
                        method = logging.error
                    else:
                        method = logging.info
                    method("%s: %s", alert.__class__.__name__, alert.message())
                    for handler in self.handlers:
                        handler(alert)
            for ticker in self.tickers:
                if ticker.get_tick_deadline() <= now:
                    ticker.tick(now)
