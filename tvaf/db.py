# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Database functions for tvaf."""

from __future__ import annotations

import contextlib
from typing import Iterator

import apsw


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
    except Exception:
        db.cursor().execute("rollback")
        raise
    else:
        db.cursor().execute("commit")
