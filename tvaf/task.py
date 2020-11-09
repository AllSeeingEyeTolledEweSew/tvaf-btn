from __future__ import annotations

import abc
import concurrent.futures
import logging
import threading
from typing import Any
from typing import Callable
from typing import Collection
from typing import List
from typing import Optional
import weakref

_LOG = logging.getLogger(__name__)


class Error(Exception):

    pass


class PrematureTermination(Error):

    pass


Callback = Callable[["Task"], Any]


class Task(abc.ABC):
    def __init__(self, *, title: str, thread_name: str = None, forever=True):
        self._title = title
        self._thread = threading.Thread(
            name=thread_name, target=self._run_wrapper
        )
        self._lock = threading.RLock()
        self.__exception: Optional[Exception] = None
        self._terminated = threading.Event()
        self._forever = forever
        self.__done_callbacks: List[Callback] = []
        self.__done_callbacks_called = False
        # NB: As of 3.8, weakref.WeakSet is not subscriptable
        self.__children = weakref.WeakSet()  # type: weakref.WeakSet[Task]

    def _add_child(self, child: Task, start=True, terminate_me_on_error=True):
        with self._lock:
            self.__children.add(child)
        if terminate_me_on_error:

            def callback(_: Task):
                exception = child.exception()
                if exception is not None:
                    self.terminate(exception)

            child.add_done_callback(callback)
        if start:
            child.start()

    def _get_children(self) -> Collection[Task]:
        with self._lock:
            return list(self.__children)

    def add_done_callback(self, callback: Callback):
        with self._lock:
            if not self.__done_callbacks_called:
                self.__done_callbacks.append(callback)
                return
        try:
            callback(self)
        except Exception:
            _LOG.exception("calling callback for %r", self)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _get_exception(self) -> Optional[Exception]:
        with self._lock:
            return self.__exception

    def _set_exception(self, exception: Exception):
        with self._lock:
            if self.__exception is None:
                self.__exception = exception

    def terminate(self, exception: Exception = None):
        with self._lock:
            self._terminated.set()
            if exception is not None:
                self._set_exception(exception)
        self._terminate()

    def _log_terminate(self):
        _LOG.debug("gracefully shutting down: %s", self._title)

    @abc.abstractmethod
    def _terminate(self):
        raise NotImplementedError

    @abc.abstractmethod
    def _run(self):
        raise NotImplementedError

    def _run_wrapper(self):
        _LOG.debug("starting: %s", self._title)
        try:
            self._run()
            with self._lock:
                if self._forever and not self._terminated.is_set():
                    raise PrematureTermination()
        except Exception as exc:
            _LOG.exception("fatal error in: %s", self._title)
            self.terminate(exc)
        else:
            _LOG.debug("shutdown complete: %s", self._title)

        for child in self._get_children():
            child.terminate()
        for child in self._get_children():
            child.join()

        with self._lock:
            callbacks = list(self.__done_callbacks)
            self.__done_callbacks_called = True
        for callback in callbacks:
            try:
                callback(self)
            except Exception:
                _LOG.exception("calling callback for %r", self)

    def start(self):
        self._thread.start()

    def join(self, timeout: float = None):
        self._thread.join(timeout=timeout)

    def exception(self, timeout: float = None) -> Optional[Exception]:
        if self._thread != threading.current_thread():
            self.join(timeout=timeout)
        with self._lock:
            return self._get_exception()

    def result(self, timeout: float = None):
        if self._thread != threading.current_thread():
            self.join(timeout=timeout)
        with self._lock:
            exception = self._get_exception()
            if exception is not None:
                raise exception


def terminate_task_on_future_fail(
    task: Task, future: concurrent.futures.Future
):
    def check(_):
        exception = future.exception()
        if exception is not None:
            task.terminate(exception)

    future.add_done_callback(check)


def log_future_exceptions(future: concurrent.futures.Future, msg: str, *args):
    def check(_):
        try:
            future.result()
        except Exception:
            _LOG.exception(msg, *args)

    future.add_done_callback(check)
