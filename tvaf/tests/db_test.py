# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for tvaf.dal.create_schema()."""

import apsw

import tvaf.dal as dal
from tvaf.tests import lib


class TestDatabase(lib.TestCase):
    """Tests for tvaf.dal.create_schema()."""

    def test_schema(self) -> None:
        conn = apsw.Connection(":memory:")
        dal.create_schema(conn)
        self.assert_golden_db(conn, include_schema=True)
