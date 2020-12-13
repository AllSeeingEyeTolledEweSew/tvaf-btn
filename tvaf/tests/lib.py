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

"""Support code for other tests."""

# mypy currently chokes on importlib.resources; typeshed shadows the backported
# module no matter what I do


import dataclasses
import io
import json
import os
import re
import time
from typing import Any
from typing import Iterator
import unittest
import unittest.mock

import apsw
import importlib_resources

from tvaf import config as config_lib
from tvaf import session as session_lib
import tvaf.types


def create_isolated_config() -> config_lib.Config:
    return config_lib.Config(
        session_enable_dht=False,
        session_enable_lsd=False,
        session_enable_natpmp=False,
        session_enable_upnp=False,
        session_listen_interfaces="127.0.0.1:0",
        session_alert_mask=0,
        ftp_port=0,
        http_port=0,
    )


def create_isolated_session_service(
    *, alert_mask: int = 0
) -> session_lib.SessionService:
    return session_lib.SessionService(
        alert_mask=alert_mask, config=create_isolated_config()
    )


def loop_until_timeout(
    timeout: float, msg: str = "condition"
) -> Iterator[None]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        yield
    raise AssertionError(f"{msg} timed out")


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
    conn.cursor().execute(
        f"insert into {table} ({columns}) values ({params})", kwargs
    )


def add_fixture_torrent_meta(
    conn: apsw.Connection, meta: tvaf.types.TorrentMeta
) -> None:
    """Adds a TorrentMeta to the database."""
    meta_dict = dataclasses.asdict(meta)
    add_fixture_row(conn, "torrent_meta", **meta_dict)


class TestCase(unittest.TestCase):
    """A base unittest.TestCase to provide some useful utilities."""

    maxDiff = None

    def get_meld_path(self, suffix: str) -> str:
        """Returns the path to write to update a golden data file."""
        # importlib_resources doesn't provide any way for updating files
        # that are assumed to be individually accessible on the filesystem. So
        # for updating golden data, we use the "naive" approach of referencing
        # a file based off of the __file__ path.
        return os.path.join(
            os.path.dirname(__file__), "data", f"{self.id()}.{suffix}"
        )

    def get_data(self, suffix: str) -> str:
        """Returns golden reference data for this test."""
        return importlib_resources.read_text(
            "tvaf.tests.data", f"{self.id()}.{suffix}"
        )

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

    def assert_golden_json(
        self, value: Any, suffix: str = "golden.json", **kwargs: Any
    ):
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

    def assert_golden_db(
        self,
        conn: apsw.Connection,
        suffix: str = "golden.sql",
        include_schema: bool = False,
    ) -> None:
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
            output = "\n".join(
                line
                for line in output.split("\n")
                if line.startswith("INSERT ")
            )
        self.assert_golden(output, suffix=suffix)

    def assert_golden_acct(
        self, *audits: tvaf.types.Acct, suffix: str = "accts.golden.json"
    ) -> None:
        """Compares a list of Acct records to golden data."""
        self.assert_golden_json(
            [dataclasses.asdict(a) for a in audits], suffix=suffix
        )

    def assert_golden_torrent_meta(
        self, *meta: tvaf.types.TorrentMeta, suffix: str = "status.golden.json"
    ) -> None:
        """Compares a list of TorrentMetas to golden data."""
        self.assert_golden_json(
            [dataclasses.asdict(m) for m in meta], suffix=suffix
        )
