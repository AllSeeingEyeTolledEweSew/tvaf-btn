# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for the tvaf.torrents module."""

from tvaf.tests import lib
from tvaf.types import TorrentStatus
from tvaf.types import FileRef
from tvaf.types import TorrentMeta


class TestGetTorrentStatus(lib.TestCase):
    """Tests for tvaf.torrents.TorrentService.get_status()."""

    def setUp(self):
        self.app = lib.get_mock_app()

    def test_none(self):
        status = self.app.torrents.get_status(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(status, None)

    def test_get_status(self):
        lib.add_fixture_torrent_status(
            self.app,
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

        status = self.app.torrents.get_status(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assertNotEqual(status.tracker, None)
        self.assertNotEqual(status.files, None)
        self.assertNotEqual(status.piece_bitmap, None)
        self.assertNotEqual(status.piece_length, None)
        self.assert_golden_torrent_status(status)


class TestGetTorrentMeta(lib.TestCase):
    """Tests for tvaf.torrents.TorrentService.get_meta()."""

    def setUp(self):
        self.app = lib.get_mock_app()

    def test_get_meta(self):
        lib.add_fixture_torrent_meta(
            self.app,
            TorrentMeta(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        managed=True,
                        generation=10,
                        atime=10000))

        meta = self.app.torrents.get_meta(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        self.assert_golden_torrent_meta(meta)

    def test_get_none(self):
        meta = self.app.torrents.get_meta(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta, None)


class TestMarkActive(lib.TestCase):
    """Tests for tvaf.torrents.TorrentService.mark_active()."""

    def setUp(self):
        self.app = lib.get_mock_app()

    def test_mark_auto(self):
        with lib.mock_time(1234567):
            self.app.torrents.mark_active(
                "da39a3ee5e6b4b0d3255bfef95601890afd80709")

        meta = self.app.torrents.get_meta(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta.atime, 1234567)

    def test_mark_manual(self):
        self.app.torrents.mark_active(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709", atime=1234567.0)

        meta = self.app.torrents.get_meta(
            "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(meta.atime, 1234567)


class TestManage(lib.TestCase):
    """Tests for tvaf.torrents.TorrentService.manage()."""

    def setUp(self):
        self.app = lib.get_mock_app()

    def test_manage(self):
        self.app.torrents.manage("da39a3ee5e6b4b0d3255bfef95601890afd80709")

        meta = self.app.torrents.get_meta(
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
    """Tetss for tvaf.torrents.TorrentService.update()."""

    def setUp(self):
        self.app = lib.get_mock_app()

    def test_update_no_files(self):
        first = get_status_incomplete()

        self.app.torrents.update([first], skip_audit=True)

        second = self.app.torrents.get_status(first.infohash)
        self.assertEqual(first, second)
        self.assert_golden_db(self.app)

    def test_update_from_empty(self):
        first = get_status_complete()

        self.app.torrents.update([first], skip_audit=True)

        second = self.app.torrents.get_status(first.infohash)
        self.assertEqual(first, second)
        self.assert_golden_db(self.app)

    def test_update_with_progress(self):
        partial = get_status_complete()
        partial.piece_bitmap = b"\xff\x00"
        lib.add_fixture_torrent_status(self.app, partial)
        complete = get_status_complete()

        self.app.torrents.update([complete], skip_audit=True)

        second = self.app.torrents.get_status(complete.infohash)
        self.assertEqual(complete, second)
        self.assert_golden_db(self.app)

    def test_delete_one_add_one(self):
        will_delete = get_status_complete()
        lib.add_fixture_torrent_status(self.app, will_delete)
        will_add = get_status_incomplete()

        self.app.torrents.update([will_add], skip_audit=True)

        should_have_deleted = self.app.torrents.get_status(will_delete.infohash)
        self.assertEqual(should_have_deleted, None)
        self.assert_golden_db(self.app)

    def test_delete_all(self):
        status = get_status_complete()
        lib.add_fixture_torrent_status(self.app, status)

        self.app.torrents.update([], skip_audit=True)

        status = self.app.torrents.get_status(status.infohash)
        self.assertEqual(status, None)
        self.assert_golden_db(self.app)

    def test_first_generation(self):
        new = get_status_complete()

        self.app.torrents.update([new], skip_audit=True)

        meta = self.app.torrents.get_meta(new.infohash)
        self.assertGreater(meta.generation, 0)
        self.assert_golden_db(self.app)

    def test_second_generation(self):
        come_and_go = get_status_complete()

        # Add, then delete, then add again
        self.app.torrents.update([come_and_go], skip_audit=True)
        self.app.torrents.update([], skip_audit=True)
        self.app.torrents.update([come_and_go], skip_audit=True)

        meta = self.app.torrents.get_meta(come_and_go.infohash)
        self.assertGreater(meta.generation, 1)
        self.assert_golden_db(self.app)
