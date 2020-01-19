# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Database functions for tvaf."""

from __future__ import annotations

import contextlib
import threading
import os
from typing import Iterator
from typing import ContextManager

import apsw

import tvaf.app as app_lib


@contextlib.contextmanager
def begin(db: apsw.Connection, mode: str = "immediate") -> Iterator[None]:
    """Return a context manager for BEGIN/COMMIT/ROLLBACK.

    This will execute "BEGIN <mode>" on the database connection before
    returning control. On a successful exit, it will execute "COMMIT". On an
    unsuccessful exit, it will execute "ROLLBACK".

    Sqlite does not support nested BEGIN statements, so this context manager
    can't be nested. The current best practice is to use this function only at
    the outermost level.

    Args:
        db: A database connection.
        mode: "IMMEDIATE", "DEFERRED" or "EXCLUSIVE".

    Returns:
        A context manager.
    """
    db.cursor().execute("begin " + mode)
    try:
        yield
    except:
        db.cursor().execute("rollback")
        raise
    else:
        db.cursor().execute("commit")


class Database:
    """Database class for the tvaf app.

    The primary role of this class is to vend thread-local sqlite3
    connections with get(). Thread-local connections are an extremely
    convenient way to use sqlite3; only one cursor can be active on a
    connection at a time, so sharing a connection across threads requires an
    external lock. Thread-local connections lets us use sqlite3's builtin
    locking for synchronization, and the code is very straightforward.

    Attributes:
        app: Our instance of the tvaf app object.
    """

    def __init__(self, app: app_lib.App) -> None:
        self.app = app
        self._local = threading.local()

    def create_schema(self) -> None:
        """Creates all tables and indexes in the database."""
        self.app.torrents.create_schema()
        self.app.requests.create_schema()
        self.app.audit.create_schema()

    def path(self) -> str:
        """Returns the path of the sqlite3 database."""
        raise NotImplementedError

    def get(self) -> apsw.Connection:
        """Returns a thread-local database connection."""
        db = getattr(self._local, "db", None)
        if db is not None:
            return db
        path = self.path()
        if path != ":memory:":
            if not os.path.exists(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
        db = apsw.Connection(path)
        db.setbusytimeout(120000)
        self._local.db = db
        db.cursor().execute("pragma journal_mode=wal").fetchall()
        self.create_schema()
        return db

    def begin(self, mode: str = "immediate") -> ContextManager[None]:
        """Returns a context manager for BEGIN/COMMIT/ROLLBACK."""
        return begin(self.get(), mode=mode)
