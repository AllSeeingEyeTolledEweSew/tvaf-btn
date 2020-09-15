# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import concurrent.futures
import os
import os.path
import tempfile

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import request as request_lib

from . import lib
from . import request_test_utils


class DummyException(Exception):

    pass


class TestCleanup(request_test_utils.RequestServiceTestCase):

    maxDiff = None

    def setUp(self):
        super().setUp()
        atp = self.torrent.atp()
        self.service.configure_add_torrent_params(atp)
        self.handle = self.session.add_torrent(atp)
        self.handle.prioritize_pieces([0] * len(self.torrent.pieces))
        # pylint: disable=protected-access
        self.cleanup = request_lib._Cleanup(handle=self.handle,
                                            session=self.session,
                                            alert_driver=self.alert_driver)

    def test_remove(self):
        self.cleanup.cleanup()
        self.assertEqual(self.session.get_torrents(), [])

    def test_have_priorities(self):
        self.handle.prioritize_pieces([4] * len(self.torrent.pieces))
        self.cleanup.cleanup()
        self.assertEqual(self.session.get_torrents(), [self.handle])

    def test_have_data(self):
        request_test_utils.wait_done_checking_or_error(self.handle)
        # NB: bug in libtorrent where add_piece accepts str but not bytes
        self.handle.add_piece(0, self.torrent.pieces[0].decode(), 0)
        # Hopefully, add_piece() followed immediately by cleanup() is an
        # effective test for "the torrent has any data", even if pieces haven't
        # been checked yet
        self.cleanup.cleanup()
        self.assertEqual(self.session.get_torrents(), [self.handle])

    # TODO: can we test the download-after-graceful-pause case?


class TestAddRemove(request_test_utils.RequestServiceTestCase):

    def test_add_remove(self):
        req = self.add_req()
        self.wait_for_torrent()
        self.assertEqual(
            [str(h.info_hash()) for h in self.session.get_torrents()],
            [self.torrent.infohash])
        self.service.discard_request(req)
        with self.assertRaises(request_lib.CanceledError):
            req.read(timeout=5)

    def test_fetch_error(self):

        def raise_dummy():
            raise DummyException("dummy")

        req = self.add_req(get_add_torrent_params=raise_dummy)
        with self.assertRaises(request_lib.FetchError):
            req.read(timeout=5)

    def test_shutdown(self):
        req = self.add_req()
        self.service.terminate()
        with self.assertRaises(request_lib.CanceledError):
            req.read(timeout=5)

    def test_already_shutdown(self):
        self.service.terminate()
        req = self.add_req()
        with self.assertRaises(request_lib.CanceledError):
            req.read(timeout=5)


class TestRead(request_test_utils.RequestServiceTestCase):

    def test_all(self):
        req = self.add_req()

        self.feed_pieces()

        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)

    def test_unaligned_multi_pieces(self):
        start = self.torrent.piece_length // 2
        stop = min(start + self.torrent.piece_length, self.torrent.length)
        req = self.add_req(start=start, stop=stop)

        self.feed_pieces()

        data = request_test_utils.read_all(req)

        self.assertEqual(data, self.torrent.data[start:stop])

    def test_unaligned_single_piece(self):
        start = self.torrent.piece_length // 4
        stop = 3 * self.torrent.piece_length // 4
        req = self.add_req(start=start, stop=stop)

        self.feed_pieces()

        data = request_test_utils.read_all(req)

        self.assertEqual(data, self.torrent.data[start:stop])

    def test_existing_torrent(self):
        req = self.add_req()

        self.feed_pieces()

        request_test_utils.read_all(req)

        req = self.add_req()
        data = request_test_utils.read_all(req, msg="second read")

        self.assertEqual(data, self.torrent.data)

    def test_simultaneous(self):
        req1 = self.add_req()
        req2 = self.add_req()
        executor = concurrent.futures.ThreadPoolExecutor()
        future1 = executor.submit(request_test_utils.read_all, req1)
        future2 = executor.submit(request_test_utils.read_all, req2)

        self.feed_pieces()

        self.assertEqual(future1.result(), self.torrent.data)
        self.assertEqual(future2.result(), self.torrent.data)

    def test_two_readers(self):
        req1 = self.add_req()
        req2 = self.add_req()

        self.feed_pieces()

        data1 = request_test_utils.read_all(req1)
        data2 = request_test_utils.read_all(req2)

        self.assertEqual(data1, self.torrent.data)
        self.assertEqual(data2, self.torrent.data)

    def test_download(self):
        seed = lib.create_isolated_session_service().session
        seed_dir = tempfile.TemporaryDirectory()
        atp = self.torrent.atp()
        atp.save_path = seed_dir.name
        atp.flags &= ~lt.torrent_flags.paused
        handle = seed.add_torrent(atp)
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        req = self.add_req()
        self.wait_for_torrent().connect_peer(("127.0.0.1", seed.listen_port()))

        # The peer connection takes a long time, not sure why
        data = request_test_utils.read_all(req, timeout=60)
        self.assertEqual(data, self.torrent.data)

    def test_file_error(self):
        # Create a file in tempdir, try to use it as the save_path
        path = os.path.join(self.tempdir.name, "file.txt")
        with open(path, mode="w"):
            pass
        self.config["torrent_default_save_path"] = path
        self.service.set_config(self.config)

        req = self.add_req()
        self.feed_pieces()

        with self.assertRaises(NotADirectoryError):
            request_test_utils.read_all(req)

    def test_read_checked_pieces(self):
        # Download a torrent
        req = self.add_req()
        self.feed_pieces()
        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)

        # query_save_path not bound in python
        save_path = self.wait_for_torrent().status(flags=128).save_path

        # Wait for the file to be written to disk
        for _ in lib.loop_until_timeout(5, msg="write file"):
            path = os.path.join(save_path, self.torrent.files[0].path.decode())
            if os.path.exists(path):
                data = open(path, mode="rb").read()
                if data == self.torrent.data:
                    break

        # Create a new session
        self.teardown_session()
        self.init_session()
        req = self.add_req()

        # We should be able to read the data without feeding pieces
        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)

    def test_read_after_cancelled_read(self):
        # Start reading
        req = self.add_req()
        # Feed one piece, so the torrent stays in the session
        self.feed_pieces(piece_indexes=(0,))

        # Wait for pieces to be prioritized
        for _ in lib.loop_until_timeout(5, msg="prioritize"):
            if all(self.wait_for_torrent().piece_priorities()):
                break

        # Cancel the request -- resets piece deadlines
        self.service.discard_request(req)

        # Wait until deadlines have been reset
        for _ in lib.loop_until_timeout(5, msg="deprioritize"):
            if not any(self.wait_for_torrent().piece_priorities()):
                break

        # Recreate the request -- listens for read_piece_alert
        req = self.add_req()
        # Feed all pieces and check that we can read the data
        self.feed_pieces()

        data = request_test_utils.read_all(req)
        self.assertEqual(data, self.torrent.data)


class TestRemoveTorrent(request_test_utils.RequestServiceTestCase):

    def test_with_active_requests(self):
        req = self.add_req()
        self.session.remove_torrent(self.wait_for_torrent())
        with self.assertRaises(request_lib.TorrentRemovedError):
            req.read(timeout=5)


class TestConfig(request_test_utils.RequestServiceTestCase):

    def test_config_defaults(self):
        save_path = str(self.config_dir.joinpath("downloads"))
        self.assertEqual(self.config,
                         config_lib.Config(torrent_default_save_path=save_path))

        atp = lt.add_torrent_params()
        self.service.configure_add_torrent_params(atp)

        self.assertEqual(atp.save_path, save_path)

    def test_set_config(self):
        # Set all non-default configs
        self.config["torrent_default_save_path"] = self.tempdir.name
        self.config["torrent_default_flags_apply_ip_filter"] = False
        self.config["torrent_default_storage_mode"] = "allocate"
        self.service.set_config(self.config)

        atp = lt.add_torrent_params()
        self.service.configure_add_torrent_params(atp)

        self.assertEqual(atp.save_path, self.tempdir.name)
        self.assertEqual(
            atp.flags,
            lt.torrent_flags.default_flags & ~lt.torrent_flags.apply_ip_filter)
        self.assertEqual(atp.storage_mode,
                         lt.storage_mode_t.storage_mode_allocate)

        # Set some default configs
        self.config["torrent_default_flags_apply_ip_filter"] = True
        self.config["torrent_default_storage_mode"] = "sparse"
        self.service.set_config(self.config)

        atp = lt.add_torrent_params()
        self.service.configure_add_torrent_params(atp)

        self.assertEqual(atp.save_path, self.tempdir.name)
        self.assertEqual(atp.flags, lt.torrent_flags.default_flags)
        self.assertEqual(atp.storage_mode,
                         lt.storage_mode_t.storage_mode_sparse)

    def test_save_path_loop(self):
        bad_link = self.config_dir.joinpath("bad_link")
        bad_link.symlink_to(bad_link, target_is_directory=True)

        self.config["torrent_default_save_path"] = str(bad_link)
        with self.assertRaises(config_lib.InvalidConfigError):
            self.service.set_config(self.config)

    def test_flags_apply_ip_filter_null(self):
        self.config["torrent_default_flags_apply_ip_filter"] = None
        with self.assertRaises(config_lib.InvalidConfigError):
            self.service.set_config(self.config)

    def test_storage_mode_invalid(self):
        self.config["torrent_default_storage_mode"] = "invalid"
        with self.assertRaises(config_lib.InvalidConfigError):
            self.service.set_config(self.config)
