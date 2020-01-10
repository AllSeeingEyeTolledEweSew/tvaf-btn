# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for tvaf.db."""

from tvaf.tests import lib


class TestDatabase(lib.TestCase):
    """Tests for tvaf.db.Database."""

    def test_schema(self) -> None:
        app = lib.get_mock_app()
        _ = app.db.get()
        self.assert_golden_db(app, include_schema=True)
