# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for the request-level functions in the tvaf.dal module."""

import apsw

import tvaf.dal as dal
import tvaf.exceptions as exc_lib
from tvaf.tests import lib
from tvaf.types import Request


def add_fixture_data(conn: apsw.Connection, piece_bitmap: bytes) -> None:
    """Adds some fixture TorrentStatus, with variable piece bitmap."""
    lib.add_fixture_row(conn,
                        "torrent_status",
                        infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        tracker="foo",
                        piece_length=65536,
                        piece_bitmap=piece_bitmap,
                        length=1048576,
                        seeders=0,
                        leechers=0,
                        announce_message="ok")
    lib.add_fixture_row(conn,
                        "file",
                        infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        file_index=0,
                        path="/downloads/movie/movie.en.srt",
                        start=0,
                        stop=10000)
    lib.add_fixture_row(conn,
                        "file",
                        infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        file_index=1,
                        path="/downloads/movie/movie.mkv",
                        start=0,
                        stop=1038576)


class TestGetStatus(lib.TestCase):
    """Tests for tvaf.dal.get_request_status()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)
        self.req = Request(request_id=1,
                           infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                           origin="some_user",
                           priority=1000,
                           start=0,
                           stop=1048576,
                           time=12345678)

    def test_no_status(self) -> None:
        status = dal.get_request_status(self.conn, self.req)

        self.assertEqual(status.progress, 0)
        self.assertEqual(status.progress_percent, 0)
        self.assert_golden_request_status(status)

    def test_complete_progress(self) -> None:
        add_fixture_data(self.conn, b"\xff\xff")

        status = dal.get_request_status(self.conn, self.req)

        self.assertEqual(status.progress, self.req.stop - self.req.start)
        self.assertEqual(status.progress_percent, 1.0)
        self.assert_golden_request_status(status)

    def test_partial_progress(self) -> None:
        add_fixture_data(self.conn, b"\xff\xcf")

        status = dal.get_request_status(self.conn, self.req)

        self.assertLess(status.progress, self.req.stop - self.req.start)
        self.assertGreater(status.progress, 0)
        self.assertLess(status.progress_percent, 1.0)
        self.assertGreater(status.progress_percent, 0)
        self.assert_golden_request_status(status)

    def test_bad_start(self) -> None:
        self.req.start = -1
        with self.assertRaises(exc_lib.BadRequest):
            dal.get_request_status(self.conn, self.req)

        self.req.start = self.req.stop
        with self.assertRaises(exc_lib.BadRequest):
            dal.get_request_status(self.conn, self.req)

    def test_bad_range(self) -> None:
        self.req.start, self.req.stop = self.req.stop, self.req.start
        with self.assertRaises(exc_lib.BadRequest):
            dal.get_request_status(self.conn, self.req)


class TestGet(lib.TestCase):
    """Tests for tvaf.dal.get_requests()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def test_empty(self):
        reqs = dal.get_requests(self.conn)
        self.assertEqual(reqs, [])

    def test_get_avoid_deactivated(self):
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=1,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=2,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)

        reqs = dal.get_requests(self.conn)

        self.assertEqual(len(reqs), 1)
        self.assert_golden_requests(*reqs)

    def test_get_deactivated(self):
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=1,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=2,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)

        reqs = dal.get_requests(self.conn, include_deactivated=True)

        self.assertEqual(len(reqs), 2)
        self.assert_golden_requests(*reqs)

    def test_get_by_infohash(self):
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=1,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=2,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=3,
                            tracker="foo",
                            infohash="other_infohash",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567)

        reqs = dal.get_requests(
            self.conn, infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assertEqual(len(reqs), 1)
        self.assert_golden_requests(*reqs)

    def test_get_infohash_deactivated(self):
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=1,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=2,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=3,
                            tracker="foo",
                            infohash="other_infohash",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567)

        reqs = dal.get_requests(
            self.conn,
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            include_deactivated=True)

        self.assertEqual(len(reqs), 2)
        self.assert_golden_requests(*reqs)

    def test_get_by_id(self):
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=1,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)

        reqs = dal.get_requests(self.conn, request_id=1)

        self.assertEqual(len(reqs), 1)
        self.assert_golden_requests(*reqs)


class TestAdd(lib.TestCase):
    """Tests for tvaf.dal.add_request()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)
        self.req = Request(tracker="foo",
                           infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                           origin="some_user",
                           start=0,
                           stop=1048576)

    def test_bad_start(self):
        self.req.start = -1
        with self.assertRaises(exc_lib.BadRequest):
            dal.add_request(self.conn, self.req)

        self.req.start = self.req.stop
        with self.assertRaises(exc_lib.BadRequest):
            dal.add_request(self.conn, self.req)

    def test_bad_range(self):
        self.req.start, self.req.stop = self.req.stop, self.req.start
        with self.assertRaises(exc_lib.BadRequest):
            dal.add_request(self.conn, self.req)

    def test_bad_origin(self):
        self.req.origin = None
        with self.assertRaises(exc_lib.BadRequest):
            dal.add_request(self.conn, self.req)

    def test_add(self):
        with lib.mock_time(1234567, autoincrement=1):
            req = dal.add_request(self.conn, self.req)

        self.assertNotEqual(req.request_id, None)
        self.assertEqual(req.infohash,
                         "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertGreaterEqual(req.time, 1234567)
        self.assertNotEqual(req.priority, None)

        meta = dal.get_meta(self.conn,
                            "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assertEqual(meta.atime, req.time)

        reqs = dal.get_requests(self.conn, request_id=1)
        self.assertEqual(len(list(reqs)), 1)

    def test_add_already_fulfilled(self):
        lib.add_fixture_row(self.conn,
                            "torrent_status",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            tracker="foo",
                            piece_length=65536,
                            piece_bitmap=b"\xff\xff",
                            length=1048576,
                            seeders=0,
                            leechers=0,
                            announce_message="ok")
        lib.add_fixture_row(self.conn,
                            "file",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            file_index=0,
                            path="/downloads/movie/movie.en.srt",
                            start=0,
                            stop=10000)
        lib.add_fixture_row(self.conn,
                            "file",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            file_index=1,
                            path="/downloads/movie/movie.mkv",
                            start=0,
                            stop=1038576)

        with lib.mock_time(1234567, autoincrement=1):
            req = dal.add_request(self.conn, self.req)

        self.assertEqual(req.request_id, None)
        self.assertEqual(req.infohash,
                         "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertGreaterEqual(req.time, 1234567)
        self.assertNotEqual(req.priority, None)
        meta = dal.get_meta(self.conn,
                            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta.atime, req.time)


class TestDeactivate(lib.TestCase):
    """Tests for tvaf.dal.deactivate_request()."""

    def setUp(self):
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def test_delete_auto_time(self):
        lib.add_fixture_row(self.conn,
                            "request",
                            request_id=1,
                            tracker="foo",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)

        with lib.mock_time(1234567, autoincrement=1):
            did_deactivate = dal.deactivate_request(self.conn, 1)

        self.assertTrue(did_deactivate)
        reqs = dal.get_requests(self.conn, request_id=1)
        self.assertEqual(reqs, [])

        did_deactivate = dal.deactivate_request(self.conn, 1)
        self.assertFalse(did_deactivate)
