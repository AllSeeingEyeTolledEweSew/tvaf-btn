# Copyright (c) 2020 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

"""Database functions for tvaf."""

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
