# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Support code for other tests."""

from __future__ import annotations

import dataclasses
import importlib.resources
import io
import json
import os
import re
import unittest
import unittest.mock
from typing import Any
from typing import ContextManager
from typing import SupportsFloat

import apsw

from tvaf.types import Request
from tvaf.types import TorrentMeta
from tvaf.types import TorrentStatus
from tvaf.types import RequestStatus
from tvaf.types import Audit


class TimeMocker:
    """A class to assist with mocking time functions for testing.

    mock_time() returns an instance of TimeMocker as part of the context
    manager protocol.

    The attributes can be changed at any time to change the passage of time
    while time functions are mocked.

    Attributes:
        time: The current time, in seconds since epoch.
        autoincrement: The amount of time to automatically increment time
            whenever time functions are called.
    """

    def __init__(self, time: SupportsFloat, autoincrement: SupportsFloat = 0):
        self.time = float(time)
        self.autoincrement = float(autoincrement)
        assert self.autoincrement >= 0
        self._patches = [
            unittest.mock.patch("time.time", new=self._time),
            unittest.mock.patch("time.monotonic", new=self._monotonic),
            unittest.mock.patch("time.sleep", new=self._sleep),
        ]

    def _time(self) -> float:
        """Mock version of time.time()."""
        self.time += self.autoincrement
        return self.time

    def _monotonic(self) -> float:
        """Mock version of time.monotonic()."""
        return self._time()

    def _sleep(self, time: SupportsFloat) -> None:
        """Mock version of time.sleep()."""
        self.time += float(time) + self.autoincrement

    def __enter__(self) -> TimeMocker:
        """Returns itself after enabling all time function patches."""
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc_info) -> None:
        """Disables all time function patches."""
        patches = list(self._patches)
        patches.reverse()
        for patch in patches:
            patch.stop()


def mock_time(time: SupportsFloat,
              autoincrement: SupportsFloat = 0) -> ContextManager[TimeMocker]:
    """Mock out time functions.

    While the returned context is active, the following functions are mocked:
        time.time
        time.sleep
        time.monotonic

    In particular time.sleep will return instantly, and functions like
    time.time and time.monotonic will return a synthetic value.

    Args:
        time: The starting synthetic time, in seconds since epoch.
        autoincrement: If not None, time will automatically increment by this
            amout whenever time functions are called. This simulates the
            normal passage of time.

    Returns:
        A TimeMocker instance. The t and autoincrement functions can be changed
            at any time to simulate changes in the passage of time.
    """
    return TimeMocker(time, autoincrement=autoincrement)


def add_fixture_row(conn: apsw.Connection, table: str, **kwargs: Any) -> None:
    """Adds a row to a database.

    Args:
        conn: The database to modify.
        table: The name of the table to update.
        kwargs: A mapping from column names to binding values.
    """
    keys = sorted(kwargs.keys())
    columns = ",".join(keys)
    params = ",".join(":" + k for k in keys)
    conn.cursor().execute(f"insert into {table} ({columns}) values ({params})",
                          kwargs)


def add_fixture_torrent_status(conn: apsw.Connection,
                               status: TorrentStatus) -> None:
    """Adds a TorrentStatus to the database."""
    status_dict = dataclasses.asdict(status)
    files_dicts = status_dict.pop("files")
    add_fixture_row(conn, "torrent_status", **status_dict)
    for file_dict in files_dicts:
        file_dict["infohash"] = status_dict["infohash"]
        add_fixture_row(conn, "file", **file_dict)


def add_fixture_torrent_meta(conn: apsw.Connection, meta: TorrentMeta) -> None:
    """Adds a TorrentMeta to the database."""
    meta_dict = dataclasses.asdict(meta)
    add_fixture_row(conn, "torrent_meta", **meta_dict)


def add_fixture_request(conn: apsw.Connection, request: Request) -> None:
    """Adds a Request to the database."""
    request_dict = dataclasses.asdict(request)
    add_fixture_row(conn, "request", **request_dict)


class TestCase(unittest.TestCase):
    """A base unittest.TestCase to provide some useful utilities."""

    maxDiff = None

    def get_meld_path(self, suffix: str) -> str:
        """Returns the path to write to update a golden data file."""
        # importlib.resources doesn't provide any way for updating files
        # that are assumed to be individually accessible on the filesystem. So
        # for updating golden data, we use the "naive" approach of referencing
        # a file based off of the __file__ path.
        return os.path.join(os.path.dirname(__file__), "data",
                            f"{self.id()}.{suffix}")

    def get_data(self, suffix: str) -> str:
        """Returns golden reference data for this test."""
        return importlib.resources.read_text("tvaf.tests.data",
                                             f"{self.id()}.{suffix}")

    def assert_golden(self, value: str, suffix: str = "golden.txt") -> None:
        """Asserts a value is equal to golden data, or update the golden data.

        Normally, this function reads a data file corresponding to the
        currently-running test, and compares the contents with the given value.
        If the values don't match, it raises AssertionError.

        If the GOLDEN_MELD environment variable is set to a nonempty string, it
        will update the golden data file with the contents instead, and no
        correctness test will be performed. This will only work if the tvaf
        project is laid out "normally" in the filesystem, i.e. not compressed
        in an egg.

        Args:
            value: The text value to test.
            suffix: A distinguishing suffix for the filename of the golden
                data.

        Raises:
            AssertionError: If the given value doesn't match the golden data,
                and GOLDEN_MELD is unset.
        """
        if os.environ.get("GOLDEN_MELD"):
            with open(self.get_meld_path(suffix), mode="w") as golden_fp:
                golden_fp.write(value)
        else:
            second = self.get_data(suffix)
            self.assertEqual(value, second)

    def assert_golden_json(self,
                           value: Any,
                           suffix: str = "golden.json",
                           **kwargs: Any):
        """Like assert_golden for the json text representation of a value.

        Args:
            value: Any value that will work with json.dump.
            suffix: A distinguishing suffix for the filename of the golden
                data.
            kwargs: Passed on to json.dump for comparison. This function
                overrides indent=4 in accordance with tvaf's formatting
                standards, and overrides sort_keys=True, which is essential for
                stable comparisons.

        Raises:
            AssertionError: If the given value doesn't match the golden data,
                and GOLDEN_MELD is unset.
        """
        kwargs["indent"] = 4
        kwargs["sort_keys"] = True
        value_text = json.dumps(value, **kwargs)
        self.assert_golden(value_text, suffix=suffix)

    def assert_golden_db(self,
                         conn: apsw.Connection,
                         suffix: str = "golden.sql",
                         include_schema: bool = False) -> None:
        """Like assert_golden for the contents of the database.

        This internally uses apsw's ".dump" command. Comments and whitespace
        are stripped to ensure stable comparisons.

        Args:
            conn: The database to check.
            suffix: A distinguishing suffix for the filename of the golden
                data.
            include_schema: If True, all SQL statements will be included. If
                False, only INSERT statements will be included.

        Raises:
            AssertionError: If the given value doesn't match the golden data,
                and GOLDEN_MELD is unset.
        """
        output_file = io.StringIO()
        shell = apsw.Shell(db=conn, stdout=output_file)
        shell.process_command(".dump")
        output = output_file.getvalue()
        # Remove comments, which include unstable data like timestamps,
        # usernames and hostnames.
        output = re.sub(r"-- (.*?)\n", "", output)
        if not include_schema:
            output = "\n".join(line for line in output.split("\n")
                               if line.startswith("INSERT "))
        self.assert_golden(output, suffix=suffix)

    def assert_golden_audit(self,
                            *audits: Audit,
                            suffix: str = "audits.golden.json") -> None:
        """Compares a list of Audit records to golden data."""
        self.assert_golden_json([a.to_dict() for a in audits], suffix=suffix)

    def assert_golden_request_status(
            self,
            *status: RequestStatus,
            suffix: str = "status.golden.json") -> None:
        """Compares a list of TorrentStatus to golden data."""
        self.assert_golden_json([s.to_dict() for s in status], suffix=suffix)

    def assert_golden_requests(self,
                               *reqs: Request,
                               suffix: str = "requests.golden.json") -> None:
        """Compares a list of Requests to golden data."""
        self.assert_golden_json([r.to_dict() for r in reqs], suffix=suffix)

    def assert_golden_torrent_status(
            self,
            *status: TorrentStatus,
            suffix: str = "status.golden.json") -> None:
        """Compares a list of TorrentStatuses to golden data."""
        self.assert_golden_json([s.to_dict() for s in status], suffix=suffix)

    def assert_golden_torrent_meta(self,
                                   *meta: TorrentMeta,
                                   suffix: str = "status.golden.json") -> None:
        """Compares a list of TorrentMetas to golden data."""
        self.assert_golden_json([m.to_dict() for m in meta], suffix=suffix)
