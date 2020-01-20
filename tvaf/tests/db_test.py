# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for tvaf.dal.create_schema()."""

import apsw

from tvaf import dal
from tvaf.tests import lib
from tvaf import db


class TestDatabase(lib.TestCase):
    """Tests for tvaf.dal.create_schema()."""

    def test_schema(self) -> None:
        conn = apsw.Connection(":memory:")
        dal.create_schema(conn)
        self.assert_golden_db(conn, include_schema=True)


class TestBegin(lib.TestCase):
    """Tests for tvaf.db.begin()."""

    def test_positive(self) -> None:
        conn = apsw.Connection(":memory:")
        conn.cursor().execute("create table foo (foo integer primary key)")
        with db.begin(conn):
            conn.cursor().execute("insert into foo (foo) values (1)")
        rows = conn.cursor().execute("select * from foo").fetchall()
        self.assertEqual(rows, [(1,)])

    def test_exception_rollback(self) -> None:
        conn = apsw.Connection(":memory:")
        conn.cursor().execute("create table foo (foo integer primary key)")
        try:
            with db.begin(conn):
                conn.cursor().execute("insert into foo (foo) values (1)")
                raise AssertionError
        except AssertionError:
            pass
        rows = conn.cursor().execute("select * from foo").fetchall()
        self.assertEqual(rows, [])
