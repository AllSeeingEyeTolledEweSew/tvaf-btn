import contextlib
import http.server
import io
import logging
import selectors
import socket as socket_lib
import socketserver
import threading
from typing import Callable
from typing import cast
from typing import Iterator
from typing import Optional
from typing import Tuple
import wsgiref.simple_server

import flask
import libtorrent as lt

from tvaf import config as config_lib
from tvaf import notify_selector
from tvaf import task as task_lib
from tvaf.http import ltapi

_BHRH = http.server.BaseHTTPRequestHandler

_LOG = logging.getLogger(__name__)


class _ThreadingWSGIServer(
    wsgiref.simple_server.WSGIServer,
    socketserver.ThreadingMixIn,
    http.server.HTTPServer,
):

    daemon_threads = False

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: Callable[..., _BHRH],
    ):
        super().__init__(server_address, RequestHandlerClass)
        self.selector = notify_selector.NotifySelector()
        self.selector.register(self, selectors.EVENT_READ)
        self._is_shutdown = False

    def shutdown(self) -> None:
        self._is_shutdown = True
        self.server_close()
        self.selector.notify()

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        while not self._is_shutdown:
            for key, _ in self.selector.select():
                if key.data == notify_selector.SENTINEL:
                    try:
                        cast(io.RawIOBase, key.fileobj).read()
                    except (ValueError, OSError):
                        pass
                elif key.fileobj == self:
                    self._handle_request_noblock()  # type: ignore
            self.service_actions()


class HTTPD(task_lib.Task, config_lib.HasConfig):
    def __init__(self, *, session: lt.session, config: config_lib.Config):
        super().__init__(title="HTTPD")
        # TODO: fixup typing here
        self._lock: threading.Condition = threading.Condition(
            threading.RLock()
        )  # type: ignore

        self._ltapiv1_blueprint = ltapi.V1Blueprint(session)

        self._flask = flask.Flask(__name__)
        self._flask.register_blueprint(
            self._ltapiv1_blueprint.blueprint, url_prefix="/lt/v1"
        )

        self._address: Optional[Tuple[str, int]] = None
        self._server: Optional[socketserver.BaseServer] = None

        self.set_config(config)

    @contextlib.contextmanager
    def stage_config(self, config: config_lib.Config) -> Iterator[None]:
        config.setdefault("http_enabled", True)
        config.setdefault("http_bind_address", "localhost")
        config.setdefault("http_port", 8823)

        address: Optional[Tuple[str, int]] = None
        server: Optional[socketserver.BaseServer] = None

        # Only parse address and port if enabled
        if config.require_bool("http_enabled"):
            address = (
                config.require_str("http_bind_address"),
                config.require_int("http_port"),
            )

        with self._lock:
            if address != self._address and address is not None:
                host, port = address
                server = wsgiref.simple_server.make_server(
                    host, port, self._flask, server_class=_ThreadingWSGIServer
                )

            yield

            if self._terminated.is_set():
                return
            if address == self._address:
                return

            self._address = address
            self._terminate()
            self._server = server

    def _terminate(self):
        with self._lock:
            if self._server is not None:
                self._server.shutdown()
                self._server = None
            self._lock.notify_all()

    @property
    def socket(self) -> Optional[socket_lib.socket]:
        with self._lock:
            if self._server is None:
                return None
            return cast(socket_lib.socket, self._server.socket)

    def _run(self):
        while not self._terminated.is_set():
            with self._lock:
                while not self._terminated.is_set() and self._server is None:
                    self._lock.wait()
                server = self._server
            if server:
                if _LOG.isEnabledFor(logging.INFO):
                    host, port = server.socket.getsockname()
                    _LOG.info("web server listening on %s:%s", host, port)
                server.serve_forever()
                logging.info("web server shut down")
