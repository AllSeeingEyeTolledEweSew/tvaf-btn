# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for the tvaf.requests module."""

import tvaf.app as app_lib
import tvaf.exceptions as exc_lib
from tvaf.tests import lib
from tvaf.types import Request


def add_fixture_data(app: app_lib.App, piece_bitmap: bytes) -> None:
    """Adds some fixture TorrentStatus, with variable piece bitmap."""
    lib.add_fixture_row(app,
                        "torrent_status",
                        infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        tracker="foo",
                        piece_length=65536,
                        piece_bitmap=piece_bitmap,
                        length=1048576,
                        seeders=0,
                        leechers=0,
                        announce_message="ok")
    lib.add_fixture_row(app,
                        "file",
                        infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        file_index=0,
                        path="/downloads/movie/movie.en.srt",
                        start=0,
                        stop=10000)
    lib.add_fixture_row(app,
                        "file",
                        infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        file_index=1,
                        path="/downloads/movie/movie.mkv",
                        start=0,
                        stop=1038576)


class TestGetStatus(lib.TestCase):
    """Tests for tvaf.requests.RequestService.get_status()."""

    def setUp(self):
        self.app = lib.get_mock_app()
        lib.set_mock_trackers(
            self.app,
            foo=[
                dict(torrent_id="123",
                     infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                     length=1048576),
                dict(torrent_id="456",
                     infohash="8d532e88704b4f747b3e1083c2e6fd7dc53fdacf",
                     length=1024)
            ])
        self.req = Request(request_id=1,
                           infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                           origin="some_user",
                           priority=1000,
                           start=0,
                           stop=1048576,
                           time=12345678)

    def test_no_status(self) -> None:
        status = self.app.requests.get_status(self.req)

        self.assertEqual(status.progress, 0)
        self.assertEqual(status.progress_percent, 0)
        self.assert_golden_request_status(status)

    def test_complete_progress(self) -> None:
        add_fixture_data(self.app, b"\xff\xff")

        status = self.app.requests.get_status(self.req)

        self.assertEqual(status.progress, self.req.stop - self.req.start)
        self.assertEqual(status.progress_percent, 1.0)
        self.assert_golden_request_status(status)

    def test_complete_with_torrent_id(self) -> None:
        self.req.infohash = None
        self.req.tracker = "foo"
        self.req.torrent_id = "123"
        add_fixture_data(self.app, b"\xff\xff")

        status = self.app.requests.get_status(self.req)

        self.assertEqual(status.progress, self.req.stop - self.req.start)
        self.assertEqual(status.progress_percent, 1.0)
        self.assert_golden_request_status(status)

    def test_partial_progress(self) -> None:
        add_fixture_data(self.app, b"\xff\xcf")

        status = self.app.requests.get_status(self.req)

        self.assertLess(status.progress, self.req.stop - self.req.start)
        self.assertGreater(status.progress, 0)
        self.assertLess(status.progress_percent, 1.0)
        self.assertGreater(status.progress_percent, 0)
        self.assert_golden_request_status(status)

    def test_bad_start(self) -> None:
        self.req.start = -1
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.get_status(self.req)

        self.req.start = self.req.stop
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.get_status(self.req)

    def test_bad_range(self) -> None:
        self.req.start, self.req.stop = (1048576, 2 * 1048576)
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.get_status(self.req)

        self.req.start, self.req.stop = self.req.stop, self.req.start
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.get_status(self.req)

    def test_bad_torrent_id(self) -> None:
        self.req.infohash = None
        self.req.tracker = "foo"
        self.req.torrent_id = "does_not_exist"
        with self.assertRaises(exc_lib.TorrentEntryNotFound):
            self.app.requests.get_status(self.req)

    def test_bad_infohash(self) -> None:
        self.req.infohash = "does_not_exist"
        self.req.tracker = None
        self.req.torrent_id = None
        with self.assertRaises(exc_lib.TorrentEntryNotFound):
            self.app.requests.get_status(self.req)

    def test_bad_tracker(self) -> None:
        self.req.infohash = None
        self.req.tracker = "does_not_exist"
        self.req.torrent_id = "123"
        with self.assertRaises(exc_lib.TrackerNotFound):
            self.app.requests.get_status(self.req)

    def test_bad_range_by_infohash(self) -> None:
        self.req.start, self.req.stop = (1048576, 2 * 1048576)
        self.req.infohash = "8d532e88704b4f747b3e1083c2e6fd7dc53fdacf"
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.get_status(self.req)


class TestGet(lib.TestCase):
    """Tests for tvaf.requests.RequestService.get()."""

    def setUp(self):
        self.app = lib.get_mock_app()

    def test_empty(self):
        reqs = self.app.requests.get()
        self.assertEqual(reqs, [])

    def test_get_avoid_deactivated(self):
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=1,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=2,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)

        reqs = self.app.requests.get()

        self.assertEqual(len(reqs), 1)
        self.assert_golden_requests(*reqs)

    def test_get_deactivated(self):
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=1,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=2,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)

        reqs = self.app.requests.get(include_deactivated=True)

        self.assertEqual(len(reqs), 2)
        self.assert_golden_requests(*reqs)

    def test_get_by_infohash(self):
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=1,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=2,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=3,
                            tracker="foo",
                            torrent_id="456",
                            infohash="other_infohash",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567)

        reqs = self.app.requests.get(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assertEqual(len(reqs), 1)
        self.assert_golden_requests(*reqs)

    def test_get_infohash_deactivated(self):
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=1,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=2,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567,
                            deactivated_at=1234568)
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=3,
                            tracker="foo",
                            torrent_id="456",
                            infohash="other_infohash",
                            start=10000,
                            stop=1048576,
                            origin="some_other_user",
                            priority=100,
                            time=1234567)

        reqs = self.app.requests.get(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            include_deactivated=True)

        self.assertEqual(len(reqs), 2)
        self.assert_golden_requests(*reqs)

    def test_get_by_id(self):
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=1,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)

        reqs = self.app.requests.get(request_id=1)

        self.assertEqual(len(reqs), 1)
        self.assert_golden_requests(*reqs)


class TestAdd(lib.TestCase):
    """Tests for tvaf.requests.RequestService.add()."""

    def setUp(self):
        self.app = lib.get_mock_app()
        lib.set_mock_trackers(
            self.app,
            foo=[
                dict(torrent_id="123",
                     infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                     length=1048576)
            ])
        self.req = Request(tracker="foo",
                           torrent_id="123",
                           origin="some_user",
                           start=0,
                           stop=1048576)

    def test_bad_start(self):
        self.req.start = -1
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.add(self.req)

        self.req.start = self.req.stop
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.add(self.req)

    def test_bad_range(self):
        self.req.start, self.req.stop = (1048576, 2 * 1048576)
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.add(self.req)

        self.req.start, self.req.stop = self.req.stop, self.req.start
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.add(self.req)

    def test_bad_origin(self):
        self.req.origin = None
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.add(self.req)

    def test_bad_torrent_id(self):
        self.req.torrent_id = "does_not_exist"
        with self.assertRaises(exc_lib.TorrentEntryNotFound):
            self.app.requests.add(self.req)

    def test_bad_tracker(self):
        self.req.tracker = "does_not_exist"
        with self.assertRaises(exc_lib.TrackerNotFound):
            self.app.requests.add(self.req)

    def test_need_torrent_id(self):
        self.req.tracker = None
        self.req.torrent_entry = None
        self.req.infohash = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        with self.assertRaises(exc_lib.BadRequest):
            self.app.requests.add(self.req)

    def test_add(self):
        with lib.mock_time(1234567, autoincrement=1):
            req = self.app.requests.add(self.req)

        self.assertNotEqual(req.id, None)
        self.assertEqual(req.infohash,
                         "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertGreaterEqual(req.time, 1234567)
        self.assertNotEqual(req.priority, None)

        meta = self.app.torrents.get_meta(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assertEqual(meta.atime, req.time)

        req = self.app.requests.get(1)
        self.assertNotEqual(req, None)

    def test_add_already_fulfilled(self):
        lib.add_fixture_row(self.app,
                            "torrent_status",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            tracker="foo",
                            piece_length=65536,
                            piece_bitmap=b"\xff\xff",
                            length=1048576,
                            seeders=0,
                            leechers=0,
                            announce_message="ok")
        lib.add_fixture_row(self.app,
                            "file",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            file_index=0,
                            path="/downloads/movie/movie.en.srt",
                            start=0,
                            stop=10000)
        lib.add_fixture_row(self.app,
                            "file",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            file_index=1,
                            path="/downloads/movie/movie.mkv",
                            start=0,
                            stop=1038576)

        with lib.mock_time(1234567, autoincrement=1):
            req = self.app.requests.add(self.req)

        self.assertEqual(req.request_id, None)
        self.assertEqual(req.infohash,
                         "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertGreaterEqual(req.time, 1234567)
        self.assertNotEqual(req.priority, None)
        meta = self.app.torrents.get_meta(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta.atime, req.time)


class TestDeactivate(lib.TestCase):
    """Tests for tvaf.requests.RequestService.deactivate()."""

    def setUp(self):
        self.app = lib.get_mock_app()

    def test_delete_auto_time(self):
        lib.add_fixture_row(self.app,
                            "request",
                            request_id=1,
                            tracker="foo",
                            torrent_id="123",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            start=0,
                            stop=1048576,
                            origin="some_user",
                            priority=1000,
                            time=1234567)

        with lib.mock_time(1234567, autoincrement=1):
            did_deactivate = self.app.requests.deactivate(1)

        self.assertTrue(did_deactivate)
        reqs = self.app.requests.get(1)
        self.assertEqual(reqs, [])

        did_deactivate = self.app.requests.deactivate(1)
        self.assertFalse(did_deactivate)
