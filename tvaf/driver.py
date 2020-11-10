import collections.abc
import concurrent.futures
import contextlib
import io
import logging
import selectors
import threading
import time
from typing import Any
from typing import cast
from typing import Collection
from typing import Deque
from typing import Dict
from typing import Iterable
from typing import Iterator as TypingIterator
from typing import List
from typing import Optional
from typing import Set
from typing import Type
import weakref

import libtorrent as lt

from tvaf import ltpy
from tvaf import notify_selector
from tvaf import session as session_lib
from tvaf import task as task_lib
from tvaf import util

_LOG = logging.getLogger(__name__)


def log_alert(
    alert: lt.alert, message: str = "", args: Iterable[Any] = (), method=None
) -> None:
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
        prefix_args += [
            error.message(),
            error.category().name(),
            error.value(),
        ]
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


class Error(Exception):

    pass


class DriverShutdown(Error):

    pass


class CheckpointTimeout(Error):

    pass


class Iterator(collections.abc.Iterator, contextlib.AbstractContextManager):
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._deque: Deque[lt.alert] = collections.deque()
        self._exception: Optional[BaseException] = None
        self._safe: bool = True
        self._notify_safe_file: Optional[io.RawIOBase] = None

    def __next__(self) -> lt.alert:
        with self._condition:
            while True:
                if self._exception:
                    self._set_safe()
                    raise self._exception
                if self._deque:
                    return self._deque.popleft()
                self._set_safe()
                self._condition.wait()

    def set_safe(self) -> None:
        with self._condition:
            if not self._exception:
                raise ValueError("must be closed before being marked safe")
            self._set_safe()

    def _set_safe(self) -> None:
        with self._condition:
            if self._safe:
                return
            self._safe = True
            if self._notify_safe_file:
                self._notify_safe_file.write(b"\0")

    def set_notify_safe_file(
        self, file: Optional[io.RawIOBase]
    ) -> Optional[io.RawIOBase]:
        with self._condition:
            old, self._notify_safe_file = self._notify_safe_file, file
            return old

    def feed(self, *alerts: lt.alert) -> bool:
        if not alerts:
            return False
        with self._condition:
            if self._exception:
                return False
            self._deque.extend(alerts)
            self._safe = False
            self._condition.notify_all()
            return True

    def close(self, exception: BaseException = None) -> None:
        with self._condition:
            if self._exception:
                return
            if exception is None:
                exception = StopIteration()
            self._exception = exception
            self._deque.clear()
            self._condition.notify_all()

    def is_closed(self) -> bool:
        with self._condition:
            return self._exception is not None

    def is_safe(self) -> bool:
        with self._condition:
            return self._safe

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
        self.set_safe()


_Type = Type[lt.alert]


class _IndexEntry:
    def __init__(
        self,
        iterator: Iterator,
        types: Collection[_Type],
        handle: Optional[lt.torrent_handle],
        alert_mask: int,
    ) -> None:
        self.ref = weakref.ref(iterator)
        self.types = set(types)
        self.handle = handle
        self.alert_mask = alert_mask

    def accept(self, alert: lt.alert) -> bool:
        if self.handle:
            if (
                isinstance(alert, lt.torrent_alert)
                and alert.handle != self.handle
            ):
                return False
        if self.types:
            if alert.__class__ not in self.types:
                return False
        return True

    def get_indexed_types(self) -> Collection[Optional[_Type]]:
        if self.types:
            return self.types
        return {None}


class _Index:
    def __init__(self) -> None:
        # Holders indexed by their filter parameters. If type or handle is
        # None, it indicates the type/handle is not filtered, and those
        # iterators should receive all alerts
        self.type_to_handle_to_entries: Dict[
            Optional[_Type],
            Dict[Optional[lt.torrent_handle], Set[_IndexEntry]],
        ] = collections.defaultdict(lambda: collections.defaultdict(set))

    def add(
        self,
        iterator: Iterator,
        types: Collection[_Type],
        handle: Optional[lt.torrent_handle],
        alert_mask: int,
    ) -> _IndexEntry:
        entry = _IndexEntry(iterator, types, handle, alert_mask)
        for type_ in entry.get_indexed_types():
            self.type_to_handle_to_entries[type_][handle].add(entry)
        return entry

    def remove(self, entry: _IndexEntry) -> None:
        for type_ in entry.get_indexed_types():
            handle_to_entries = self.type_to_handle_to_entries[type_]
            entries = handle_to_entries[entry.handle]
            entries.discard(entry)
            if not entries:
                del handle_to_entries[entry.handle]
                if not handle_to_entries:
                    del self.type_to_handle_to_entries[type_]

    def iter_entries(self) -> TypingIterator[_IndexEntry]:
        for handle_to_entries in self.type_to_handle_to_entries.values():
            for entries in handle_to_entries.values():
                for entry in entries:
                    yield entry

    def get_dispatch_plan(
        self, alerts: Collection[lt.alert]
    ) -> Dict[Iterator, List[lt.alert]]:
        # Get a dispatch plan of which iterators shall receive which alerts
        iter_to_alerts = collections.defaultdict(list)
        type_to_handle_to_entries = self.type_to_handle_to_entries
        for alert in alerts:
            lookup_types = (alert.__class__, None)
            lookup_handles: Collection[Optional[lt.torrent_handle]]
            if isinstance(alert, lt.torrent_alert):
                lookup_handles = (alert.handle, None)
            else:
                lookup_handles = (None,)
            for type_ in lookup_types:
                handle_to_entries = type_to_handle_to_entries.get(type_, {})
                for handle in lookup_handles:
                    entries = handle_to_entries.get(handle, ())
                    for entry in entries:
                        iterator = entry.ref()
                        if iterator is None:
                            continue
                        iter_to_alerts[iterator].append(alert)
        return iter_to_alerts


def _dying_gasp(wfile: io.RawIOBase) -> None:
    # It's hard to reason about whether there are any cases where the rfile
    # could get closed before the wfile, especially if we change the code; but
    # this could only happen after we no longer care about it.  Capture
    # BrokenPipeError so we don't spam the console
    try:
        wfile.write(b"\0")
    except BrokenPipeError:
        pass


def _close_if_removed(
    session: lt.session, handle: lt.torrent_handle, iterator: Iterator
) -> None:
    if not ltpy.handle_in_session(handle, session):
        # TODO: make this constructor nicer
        ec = lt.error_code(
            ltpy.LibtorrentErrorValue.INVALID_TORRENT_HANDLE,
            lt.libtorrent_category(),
        )
        iterator.close(ltpy.InvalidTorrentHandleError(ec))


class _IteratorCollection:
    def __init__(self, *, session_service: session_lib.SessionService) -> None:
        self._session_service = session_service
        self._session = session_service.session
        self._lock = threading.Lock()
        self._index = _Index()
        # All iterators to which we've fed some alerts from the current batch
        self._unsafe_iters = (
            weakref.WeakSet()
        )  # type: weakref.WeakSet[Iterator]
        # We use file descriptors (or sockets) with select() to be notified
        # when all our iterators are in the safe state. This may be less
        # pythonic than using condition variables or other primitives, but it's
        # clearer to me that we avoid "surprise" references or any trouble
        # caused by taking a lock in a finalizer
        self._selector = notify_selector.DefaultNotifySelector()
        # The current batch of alerts, used for add(start=...).
        self._alerts: List[lt.alert] = []
        self._alert_to_index: Dict[lt.alert, int] = {}
        self._check_executor = concurrent.futures.ThreadPoolExecutor()

    def add(
        self,
        alert_mask: int,
        *types: _Type,
        handle: lt.torrent_handle = None,
        start: lt.alert = None
    ) -> Iterator:
        iterator = Iterator()
        alerts = []
        rfile, wfile = util.selectable_pipe()
        iterator.set_notify_safe_file(wfile)
        # Finalizer should be a top-level function, so it doesn't hold a
        # reference to the iterator
        weakref.finalize(iterator, _dying_gasp, wfile)

        with self._lock:
            if start is not None:
                index = self._alert_to_index.get(start)
                if index is None:
                    raise ValueError("unknown start alert")
                alerts = self._alerts[index:]
            entry = self._index.add(iterator, types, handle, alert_mask)
            alerts = [alert for alert in alerts if entry.accept(alert)]
            self._selector.register(rfile, selectors.EVENT_READ, data=entry)
            if iterator.feed(*alerts):
                self._unsafe_iters.add(iterator)
            self._session_service.inc_alert_mask(alert_mask)

        if handle is not None and start is None:
            future = self._check_executor.submit(
                _close_if_removed, self._session, handle, iterator
            )

            def close_on_error(_) -> None:
                exc = future.exception()
                if exc is not None:
                    iterator.close(exc)

            future.add_done_callback(close_on_error)

        return iterator

    def _select_events_locked(self, timeout: float = None) -> None:
        self._lock.release()
        try:
            events = self._selector.select(timeout=timeout)
        finally:
            self._lock.acquire()

        for key, _ in events:
            try:
                cast(io.RawIOBase, key.fileobj).read()
            except (ValueError, OSError):
                pass
            if key.data == notify_selector.SENTINEL:
                continue
            index_entry = key.data
            iterator = index_entry.ref()
            # On close, we can remove from our dispatch index
            if iterator is None or iterator.is_closed():
                self._index.remove(index_entry)
                self._session_service.dec_alert_mask(index_entry.alert_mask)
            # On close + safe, we can forget it completely
            if iterator is None or (
                iterator.is_closed() and iterator.is_safe()
            ):
                self._selector.unregister(key.fileobj)
            # On safe, remove from our pending set. Note that a dead iterator
            # is implicitly safe, but will already have been removed (actually
            # pending removal) from unsafe_iters
            if iterator is not None and iterator.is_safe():
                self._unsafe_iters.discard(iterator)

    def _dispatch_locked(self, alerts: List[lt.alert]) -> None:
        assert not self._unsafe_iters

        self._alerts = alerts
        self._alert_to_index = {alert: i for i, alert in enumerate(alerts)}

        for alert in alerts:
            log_alert(alert)

        iter_to_alerts = self._index.get_dispatch_plan(alerts)
        for iterator, iterator_alerts in iter_to_alerts.items():
            # If the iterator has been closed, it won't accept new alerts
            if iterator.feed(*iterator_alerts):
                self._unsafe_iters.add(iterator)

    def wait_for_checkpoint(self, timeout: float = None) -> bool:
        start_time = time.monotonic()
        with self._lock:
            while self._unsafe_iters:
                if timeout is None:
                    sub_timeout: Optional[float] = None
                else:
                    sub_timeout = start_time + timeout - time.monotonic()
                    if sub_timeout <= 0:
                        return False
                self._select_events_locked(timeout=sub_timeout)

            # Clear our alerts list so that any add(start=...) calls will fail
            self._alerts.clear()
            self._alert_to_index.clear()
            return True

    def pump_alerts(self, timeout: float = None) -> None:
        if not self.wait_for_checkpoint(timeout=timeout):
            raise CheckpointTimeout()

        with ltpy.translate_exceptions():
            alerts = self._session.pop_alerts()

        with self._lock:
            self._dispatch_locked(alerts)

    def close(self, exception: BaseException) -> None:
        with self._lock:
            for entry in self._index.iter_entries():
                iterator = entry.ref()
                if iterator is not None:
                    iterator.close(exception)


class AlertDriver(task_lib.Task):

    ABORT_CHECK_INTERVAL = 1.0
    CHECKPOINT_TIMEOUT = 10.0

    def __init__(self, *, session_service: session_lib.SessionService) -> None:
        super().__init__(title="AlertDriver", thread_name="alert-driver")
        self._session = session_service.session
        self._collection = _IteratorCollection(session_service=session_service)
        self._notify_rfile, self._notify_wfile = util.selectable_pipe()

    def iter_alerts(
        self,
        alert_mask: int,
        *types: _Type,
        handle: lt.torrent_handle = None,
        start: lt.alert = None
    ) -> Iterator:
        if self._terminated.is_set():
            raise DriverShutdown()
        return self._collection.add(
            alert_mask, *types, handle=handle, start=start
        )

    def _terminate(self) -> None:
        self._collection.close(DriverShutdown())
        try:
            self._notify_wfile.write(b"\0")
        except BrokenPipeError:
            pass

    def pump_alerts(self, timeout: float = None) -> None:
        if timeout is None:
            timeout = self.CHECKPOINT_TIMEOUT
        self._collection.pump_alerts(timeout=timeout)

    def _try_pump_alerts(self) -> None:
        try:
            self.pump_alerts()
        except CheckpointTimeout:
            _LOG.error(
                "Some alert iterators still marked unsafe after %ss. Alert "
                "handling cannot proceed.",
                self.CHECKPOINT_TIMEOUT,
            )

    def _run_select(self) -> None:
        with ltpy.translate_exceptions():
            # TODO: how do I make this type kosher?
            session = cast(Any, self._session)
            session.set_alert_fd(self._notify_wfile.fileno())

        selector = selectors.DefaultSelector()
        selector.register(self._notify_rfile, selectors.EVENT_READ)

        while not self._terminated.is_set():
            self._try_pump_alerts()
            for key, _ in selector.select():
                cast(io.RawIOBase, key.fileobj).read()

    def _run_polling(self) -> None:
        while not self._terminated.is_set():
            self._try_pump_alerts()
            with ltpy.translate_exceptions():
                self._session.wait_for_alert(
                    int(self.ABORT_CHECK_INTERVAL * 1000)
                )

    def _run(self) -> None:
        if hasattr(self._session, "set_alert_fd"):
            self._run_select()
        else:
            self._run_polling()

        self._log_terminate()
        self._collection.wait_for_checkpoint()
