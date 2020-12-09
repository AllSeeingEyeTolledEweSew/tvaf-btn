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

"""Tests for the tvaf.btn module."""

import hashlib
import stat as stat_lib
from typing import Any
import unittest

import apsw

import btn
import tvaf.btn as tvaf_btn
import tvaf.fs as fs

# flake8: noqa


def get_mock_db() -> apsw.Connection:
    """Returns a connection to an in-memory database with the btn schemas."""
    # TODO(AllSeeingEyeTolledEweSew): Probably cleaner way to do this.
    conn = apsw.Connection(":memory:")
    btn.Series._create_schema(conn)
    btn.Group._create_schema(conn)
    btn.TorrentEntry._create_schema(conn)
    return conn


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


def add_series(conn: apsw.Connection, **series: Any) -> None:
    """Adds a Series row to the database, with some default values.

    Args:
        conn: The database to modify.
        series: A mapping from column names to binding values.
    """
    data = dict(updated_at=0, deleted=0, id=100)
    data.update(series)
    add_fixture_row(conn, "series", **data)


def add_group(conn: apsw.Connection, **group: Any) -> None:
    """Adds a Group row to the database, with some default values.

    Args:
        conn: The database to modify.
        group: A mapping from column names to binding values.
    """
    data = dict(
        category="Episode", updated_at=0, series_id=100, id=110, deleted=0
    )
    data.update(group)
    add_fixture_row(conn, "torrent_entry_group", **data)


def add_entry(conn: apsw.Connection, **torrent_entry: Any) -> None:
    """Adds a TorrentEntry row to the database, with some default values.

    Args:
        conn: The database to modify.
        torrent_entry: A mapping from column names to binding values.
    """
    data = dict(
        codec="H.264",
        container="MKV",
        origin="Scene",
        release_name="Test",
        resolution="1080p",
        size=1048576,
        source="Bluray",
        snatched=0,
        leechers=0,
        seeders=0,
        time=1234567,
        updated_at=0,
        id=111,
        group_id=110,
        deleted=0,
    )
    data.update(torrent_entry)
    data["info_hash"] = hashlib.sha1(str(data["id"]).encode()).hexdigest()
    add_fixture_row(conn, "torrent_entry", **data)


def add_file(conn: apsw.Connection, **file_info: Any) -> None:
    """Adds a FileInfo row to the database, with some default values.

    Args:
        conn: The database to modify.
        file_info: A mapping from column names to binding values.
    """
    data = dict(updated_at=0, file_index=0, id=111)
    data.update(file_info)
    assert isinstance(data["path"], bytes)
    add_fixture_row(conn, "file_info", **data)


class TestBrowseFile(unittest.TestCase):
    """Tests for accessing a file under browse/..."""

    def test_file_access(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, time=12345678)
        add_file(conn, path=b"a.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/a.mkv")

        stat = node.stat()
        self.assertEqual(stat.mtime, 12345678)
        self.assertEqual(stat.size, 100)
        ref = node.get_torrent_ref()
        self.assertEqual(ref.tracker, "btn")
        self.assertEqual(ref.start, 0)
        self.assertEqual(ref.stop, 100)

    def test_file_in_dir(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/path/to/a/file.mkv")

        ref = node.get_torrent_ref()
        self.assertEqual(ref.tracker, "btn")

    def test_multiple_files(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"dir/2.mkv", file_index=0, start=0, stop=100)
        add_file(conn, path=b"dir/1.mkv", file_index=1, start=100, stop=200)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/dir/1.mkv")
        self.assertEqual(node.stat().size, 100)
        self.assertEqual(node.get_torrent_ref().start, 100)
        node = fs.lookup(root, "browse/S/G/dir/2.mkv")
        self.assertEqual(node.stat().size, 100)
        self.assertEqual(node.get_torrent_ref().start, 0)


class TestBrowseBase(unittest.TestCase):
    """Tests for the browse directory itself."""

    def test_access(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")

        stat = node.stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFDIR)

    def test_readdir(self):
        conn = get_mock_db()
        add_series(conn, name="S 100", id=100)
        add_series(conn, name="S 200", id=200)
        add_series(conn, name="S 300", id=300)
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 3)
        self.assertEqual(dirents[0].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual(dirents[1].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual(dirents[2].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual(
            {d.name for d in dirents}, {"S 100", "S 200", "S 300"}
        )

    def test_readdir_empty_name(self):
        conn = get_mock_db()
        add_series(conn, name="S", id=100)
        add_series(conn, name="", id=200)
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 1)
        self.assertEqual(dirents[0].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual({d.name for d in dirents}, {"S"})

    def test_readdir_deleted(self):
        conn = get_mock_db()
        add_series(conn, name="S 100", id=100)
        add_series(conn, name="S 200", id=200, deleted=1)
        add_series(conn, name="S 300", id=300)
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 2)
        self.assertEqual({d.name for d in dirents}, {"S 100", "S 300"})

    def test_readdir_slash(self):
        conn = get_mock_db()
        add_series(conn, name="S/Slash")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 1)
        self.assertEqual(dirents[0].name, "S_Slash")

    def test_readdir_under(self):
        conn = get_mock_db()
        add_series(conn, name="S_Under")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 1)
        self.assertEqual(dirents[0].name, "S_Under")

    def test_readdir_offset(self):
        conn = get_mock_db()
        add_series(conn, name="S 100", id=100)
        add_series(conn, name="S 200", id=200)
        add_series(conn, name="S 300", id=300)
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        dirents = list(node.readdir())

        next_dirents = list(node.readdir(offset=dirents[0].next_offset))
        self.assertEqual(len(next_dirents), 2)
        self.assertEqual(next_dirents[0].name, dirents[1].name)

    def test_lookup(self):
        conn = get_mock_db()
        add_series(conn, name="S 100", id=100)
        add_series(conn, name="S 200", id=200)
        add_series(conn, name="S 300", id=300)
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        node = node.lookup("S 200")
        self.assertNotEqual(node, None)

    def test_lookup_deleted(self):
        conn = get_mock_db()
        add_series(conn, name="S 100", id=100)
        add_series(conn, name="S 200", id=200, deleted=1)
        add_series(conn, name="S 300", id=300)
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        with self.assertRaises(FileNotFoundError):
            node = node.lookup("S 200")

    def test_lookup_slash(self):
        conn = get_mock_db()
        add_series(conn, name="S/Slash")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        node = node.lookup("S_Slash")
        self.assertNotEqual(node, None)

    def test_lookup_under(self):
        conn = get_mock_db()
        add_series(conn, name="S_Under")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")
        node = node.lookup("S_Under")
        self.assertNotEqual(node, None)

    def test_lookup_noent(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse")

        with self.assertRaises(FileNotFoundError):
            node.lookup("does_not_exist")


class TestBrowseSeries(unittest.TestCase):
    """Tests for a browse/<series> directory."""

    def test_access(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")

        stat = node.stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFDIR)

    def test_readdir(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G 110", id=110, series_id=100)
        add_group(conn, name="G 120", id=120, series_id=100)
        add_group(conn, name="G 130", id=130, series_id=100)
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 3)
        self.assertEqual(dirents[0].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual(dirents[1].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual(dirents[2].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual(
            {d.name for d in dirents}, {"G 110", "G 120", "G 130"}
        )

    def test_readdir_empty_name(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G", id=110, series_id=100)
        add_group(conn, name="", id=120, series_id=100)
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 1)
        self.assertEqual(dirents[0].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual({d.name for d in dirents}, {"G"})

    def test_readdir_deleted(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G 110", id=110, series_id=100)
        add_group(conn, name="G 120", id=120, series_id=100, deleted=1)
        add_group(conn, name="G 130", id=130, series_id=100)
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 2)
        self.assertEqual({d.name for d in dirents}, {"G 110", "G 130"})

    def test_readdir_slash(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G/Slash")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 1)
        self.assertEqual(dirents[0].name, "G_Slash")

    def test_readdir_under(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G_Under")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")
        dirents = list(node.readdir())

        self.assertEqual(len(dirents), 1)
        self.assertEqual(dirents[0].name, "G_Under")

    def test_readdir_offset(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G 110", id=110, series_id=100)
        add_group(conn, name="G 120", id=120, series_id=100)
        add_group(conn, name="G 130", id=130, series_id=100)
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")
        dirents = list(node.readdir())

        next_dirents = list(node.readdir(offset=dirents[0].next_offset))
        self.assertEqual(len(next_dirents), 2)
        self.assertEqual(next_dirents[0].name, dirents[1].name)

    def test_lookup(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G 110", id=110, series_id=100)
        add_group(conn, name="G 120", id=120, series_id=100)
        add_group(conn, name="G 130", id=130, series_id=100)
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")
        node = node.lookup("G 110")
        self.assertNotEqual(node, None)

    def test_lookup_deleted(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G 110", id=110, series_id=100)
        add_group(conn, name="G 120", id=120, series_id=100, deleted=1)
        add_group(conn, name="G 130", id=130, series_id=100)
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")

        with self.assertRaises(FileNotFoundError):
            node.lookup("G 120")

    def test_lookup_slash(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G/Slash")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")

        node = node.lookup("G_Slash")
        self.assertNotEqual(node, None)

    def test_lookup_under(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G_Under")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")

        node = node.lookup("G_Under")
        self.assertNotEqual(node, None)

    def test_lookup_noent(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(conn, path=b"path/to/a/file.mkv", start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S")

        with self.assertRaises(FileNotFoundError):
            node.lookup("does_not_exist")


class TestGroupSubdirBase(unittest.TestCase):
    """Tests for a browse/<series>/<group> directory."""

    def test_access(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b1/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"b1/2.mkv", file_index=1, start=100, stop=200)
        file_(id=111, path=b"a1/1.mkv", file_index=2, start=200, stop=300)
        file_(id=111, path=b"a1/2.mkv", file_index=3, start=300, stop=400)
        file_(id=112, path=b"a2.mkv", file_index=0, start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G")

        stat = node.stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFDIR)

    def test_readdir(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b1/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"b1/2.mkv", file_index=1, start=100, stop=200)
        file_(id=111, path=b"a1/1.mkv", file_index=2, start=200, stop=300)
        file_(id=111, path=b"a1/2.mkv", file_index=3, start=300, stop=400)
        file_(id=112, path=b"a2.mkv", file_index=0, start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G")
        dirents = node.readdir()
        dirents = sorted(dirents, key=lambda d: d.name)

        self.assertEqual([d.name for d in dirents], ["a1", "a2.mkv", "b1"])
        self.assertEqual(dirents[0].stat.filetype, stat_lib.S_IFDIR)
        self.assertEqual(dirents[1].stat.filetype, stat_lib.S_IFREG)
        self.assertEqual(dirents[2].stat.filetype, stat_lib.S_IFDIR)

    def test_readdir_offset(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b1/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"b1/2.mkv", file_index=1, start=100, stop=200)
        file_(id=111, path=b"a1/1.mkv", file_index=2, start=200, stop=300)
        file_(id=111, path=b"a1/2.mkv", file_index=3, start=300, stop=400)
        file_(id=112, path=b"a2.mkv", file_index=0, start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G")
        dirents = list(node.readdir())

        next_dirents = list(node.readdir(offset=dirents[0].next_offset))
        self.assertEqual(len(next_dirents), len(dirents) - 1)
        self.assertEqual(dirents[1:], next_dirents)

    def test_lookup(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b1/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"b1/2.mkv", file_index=1, start=100, stop=200)
        file_(id=111, path=b"a1/1.mkv", file_index=2, start=200, stop=300)
        file_(id=111, path=b"a1/2.mkv", file_index=3, start=300, stop=400)
        file_(id=112, path=b"a2.mkv", file_index=0, start=0, stop=100)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G")

        sub = node.lookup("a1")
        self.assertEqual(sub.stat().filetype, stat_lib.S_IFDIR)
        sub = node.lookup("b1")
        self.assertEqual(sub.stat().filetype, stat_lib.S_IFDIR)
        sub = node.lookup("a2.mkv")
        self.assertEqual(sub.stat().filetype, stat_lib.S_IFREG)

    def test_lookup_noent(self):
        conn = get_mock_db()
        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn)
        add_file(
            conn, id=111, path=b"a1/1.mkv", file_index=0, start=0, stop=100
        )

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G")

        with self.assertRaises(FileNotFoundError):
            node.lookup("does_not_exist")


class TestGroupSubdir(unittest.TestCase):
    """Tests for a nontrivial subdirectory of browse/<series>/<group>."""

    def test_access(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"a/1.mkv", file_index=1, start=100, stop=200)
        file_(id=112, path=b"b/c/2.mkv", file_index=0, start=0, stop=100)
        file_(id=112, path=b"a/c/2.mkv", file_index=1, start=100, stop=200)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/a")

        stat = node.stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFDIR)

    def test_readdir(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"a/1.mkv", file_index=1, start=100, stop=200)
        file_(id=112, path=b"b/c/2.mkv", file_index=0, start=0, stop=100)
        file_(id=112, path=b"a/c/2.mkv", file_index=1, start=100, stop=200)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/a")
        dirents = list(node.readdir())

        dirents = sorted(dirents, key=lambda d: d.name)
        self.assertEqual([d.name for d in dirents], ["1.mkv", "c"])
        self.assertEqual(dirents[0].stat.filetype, stat_lib.S_IFREG)
        self.assertEqual(dirents[1].stat.filetype, stat_lib.S_IFDIR)

    def test_readdir_offset(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"a/1.mkv", file_index=1, start=100, stop=200)
        file_(id=112, path=b"b/c/2.mkv", file_index=0, start=0, stop=100)
        file_(id=112, path=b"a/c/2.mkv", file_index=1, start=100, stop=200)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/a")
        dirents = list(node.readdir())

        next_dirents = list(node.readdir(offset=dirents[0].next_offset))
        self.assertEqual(len(next_dirents), len(dirents) - 1)
        self.assertEqual(dirents[1:], next_dirents)

    def test_lookup(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"a/1.mkv", file_index=1, start=100, stop=200)
        file_(id=112, path=b"b/c/2.mkv", file_index=0, start=0, stop=100)
        file_(id=112, path=b"a/c/2.mkv", file_index=1, start=100, stop=200)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/a")

        sub = node.lookup("1.mkv")
        self.assertEqual(sub.stat().filetype, stat_lib.S_IFREG)
        sub = node.lookup("c")
        self.assertEqual(sub.stat().filetype, stat_lib.S_IFDIR)

    def test_lookup_noent(self):
        conn = get_mock_db()

        # Readability
        def file_(**kwargs):
            add_file(conn, **kwargs)

        add_series(conn, name="S")
        add_group(conn, name="G")
        add_entry(conn, id=111)
        add_entry(conn, id=112)
        file_(id=111, path=b"b/1.mkv", file_index=0, start=0, stop=100)
        file_(id=111, path=b"a/1.mkv", file_index=1, start=100, stop=200)
        file_(id=112, path=b"b/c/2.mkv", file_index=0, start=0, stop=100)
        file_(id=112, path=b"a/c/2.mkv", file_index=1, start=100, stop=200)

        root = tvaf_btn.RootDir(conn)
        node = fs.lookup(root, "browse/S/G/a")

        with self.assertRaises(FileNotFoundError):
            node.lookup("does_not_exist")
