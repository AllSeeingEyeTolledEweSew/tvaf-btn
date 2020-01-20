# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for the torrent-level functions in the tvaf.dal module."""

import apsw

from tvaf import dal
from tvaf.tests import lib
from tvaf.types import FileRef
from tvaf.types import TorrentMeta
from tvaf.types import TorrentStatus


class TestGetTorrentStatus(lib.TestCase):
    """Tests for tvaf.dal.get_torrent_status()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def test_none(self):
        status = dal.get_torrent_status(
            self.conn, "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(status, None)

    def test_get_status(self):
        lib.add_fixture_torrent_status(
            self.conn,
            TorrentStatus(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                          tracker="foo",
                          piece_length=65536,
                          piece_bitmap=b"\xff\xff",
                          length=1048576,
                          seeders=0,
                          leechers=0,
                          announce_message="ok",
                          files=[
                              FileRef(file_index=0,
                                      path="/downloads/movie/movie.en.srt",
                                      start=0,
                                      stop=10000),
                              FileRef(file_index=1,
                                      path="/downloads/movie/movie.mkv",
                                      start=0,
                                      stop=1038576)
                          ]))

        status = dal.get_torrent_status(
            self.conn, "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assertNotEqual(status.tracker, None)
        self.assertNotEqual(status.files, None)
        self.assertNotEqual(status.piece_bitmap, None)
        self.assertNotEqual(status.piece_length, None)
        self.assert_golden_torrent_status(status)


class TestGetTorrentMeta(lib.TestCase):
    """Tests for tvaf.dal.get_meta()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def test_get_meta(self):
        lib.add_fixture_torrent_meta(
            self.conn,
            TorrentMeta(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        managed=True,
                        generation=10,
                        atime=10000))

        meta = dal.get_meta(self.conn,
                            "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assert_golden_torrent_meta(meta)

    def test_get_none(self):
        meta = dal.get_meta(self.conn,
                            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta, None)


class TestMarkActive(lib.TestCase):
    """Tests for tvaf.dal.mark_torrent_active()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def test_mark_auto(self):
        with lib.mock_time(1234567):
            dal.mark_torrent_active(self.conn,
                                    "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        meta = dal.get_meta(self.conn,
                            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta.atime, 1234567)

    def test_mark_manual(self):
        dal.mark_torrent_active(self.conn,
                                "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                                atime=1234567.0)

        meta = dal.get_meta(self.conn,
                            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta.atime, 1234567)


class TestManage(lib.TestCase):
    """Tests for tvaf.dal.manage_torrent()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def test_manage(self):
        dal.manage_torrent(self.conn,
                           "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        meta = dal.get_meta(self.conn,
                            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertTrue(meta.managed)


def get_status_complete():
    """Get a complete TorrentStatus."""
    return TorrentStatus(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                         tracker="foo",
                         piece_bitmap=b"\xff\xff",
                         piece_length=65536,
                         length=1048576,
                         seeders=1,
                         leechers=0,
                         announce_message="ok",
                         files=[
                             FileRef(file_index=0,
                                     path="/downloads/movie/movie.en.srt",
                                     start=0,
                                     stop=10000),
                             FileRef(file_index=1,
                                     path="/downloads/movie/movie.mkv",
                                     start=0,
                                     stop=1038576),
                         ])


def get_status_incomplete():
    """Get an incomplete TorrentStatus."""
    return TorrentStatus(infohash="8d532e88704b4f747b3e1083c2e6fd7dc53fdacf",
                         tracker="foo",
                         piece_bitmap=b"\x00\x00",
                         piece_length=65536,
                         length=1048576,
                         seeders=1,
                         leechers=0,
                         announce_message="ok",
                         files=[])


class TestUpdate(lib.TestCase):
    """Tetss for dal.update_torrent_status()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def test_update_no_files(self):
        first = get_status_incomplete()

        dal.update_torrent_status(self.conn, [first], skip_audit=True)

        second = dal.get_torrent_status(self.conn, first.infohash)
        self.assertEqual(first, second)
        self.assert_golden_db(self.conn)

    def test_update_from_empty(self):
        first = get_status_complete()

        dal.update_torrent_status(self.conn, [first], skip_audit=True)

        second = dal.get_torrent_status(self.conn, first.infohash)
        self.assertEqual(first, second)
        self.assert_golden_db(self.conn)

    def test_update_with_progress(self):
        partial = get_status_complete()
        partial.piece_bitmap = b"\xff\x00"
        lib.add_fixture_torrent_status(self.conn, partial)
        complete = get_status_complete()

        dal.update_torrent_status(self.conn, [complete], skip_audit=True)

        second = dal.get_torrent_status(self.conn, complete.infohash)
        self.assertEqual(complete, second)
        self.assert_golden_db(self.conn)

    def test_delete_one_add_one(self):
        will_delete = get_status_complete()
        lib.add_fixture_torrent_status(self.conn, will_delete)
        will_add = get_status_incomplete()

        dal.update_torrent_status(self.conn, [will_add], skip_audit=True)

        should_have_deleted = dal.get_torrent_status(self.conn,
                                                     will_delete.infohash)
        self.assertEqual(should_have_deleted, None)
        self.assert_golden_db(self.conn)

    def test_delete_all(self):
        status = get_status_complete()
        lib.add_fixture_torrent_status(self.conn, status)

        dal.update_torrent_status(self.conn, [], skip_audit=True)

        status = dal.get_torrent_status(self.conn, status.infohash)
        self.assertEqual(status, None)
        self.assert_golden_db(self.conn)

    def test_first_generation(self):
        new = get_status_complete()

        dal.update_torrent_status(self.conn, [new], skip_audit=True)

        meta = dal.get_meta(self.conn, new.infohash)
        self.assertGreater(meta.generation, 0)
        self.assert_golden_db(self.conn)

    def test_second_generation(self):
        come_and_go = get_status_complete()

        # Add, then delete, then add again
        dal.update_torrent_status(self.conn, [come_and_go], skip_audit=True)
        dal.update_torrent_status(self.conn, [], skip_audit=True)
        dal.update_torrent_status(self.conn, [come_and_go], skip_audit=True)

        meta = dal.get_meta(self.conn, come_and_go.infohash)
        self.assertGreater(meta.generation, 1)
        self.assert_golden_db(self.conn)
