# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import logging
import os
import os.path
import pathlib
import tempfile
import unittest
import unittest.mock

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import request as request_lib

from . import request_test_utils
from . import tdummy
from . import test_utils


class DummyException(Exception):

    pass


class TestAddRemove(request_test_utils.RequestServiceTestCase):

    def test_add_remove(self):
        req = self.add_req()
        self.pump_alerts(self.session.get_torrents, msg="add")
        handles = self.session.get_torrents()
        self.assertEqual([str(h.info_hash()) for h in handles],
                         [tdummy.INFOHASH])
        req.cancel()
        self.pump_alerts(lambda: not self.session.get_torrents(), msg="remove")
        self.assertIsInstance(req.exception, request_lib.CancelledError)

    def test_fetch_error(self):

        def raise_dummy():
            raise DummyException("dummy")

        req = self.add_req(get_torrent=raise_dummy)
        with self.assertRaises(request_lib.FetchError):
            req.get_next(timeout=5)
        self.assertIsInstance(req.exception, request_lib.FetchError)


class TestRead(request_test_utils.RequestServiceTestCase):

    def test_all(self):
        req = self.add_req()

        self.feed_pieces()

        data = self.read_all(req)
        self.assertEqual(data, tdummy.DATA)

        self.pump_alerts(lambda: not req.active, msg="request deactivated")
        self.assertIsNone(req.exception)

    def test_unaligned_multi_pieces(self):
        start = tdummy.PIECE_LENGTH // 2
        stop = min(start + tdummy.PIECE_LENGTH, len(tdummy.DATA))
        req = self.add_req(start=start, stop=stop)

        self.feed_pieces()

        data = self.read_all(req)

        self.assertEqual(data, tdummy.DATA[start:stop])

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

    def test_unaligned_single_piece(self):
        start = tdummy.PIECE_LENGTH // 4
        stop = 3 * tdummy.PIECE_LENGTH // 4
        req = self.add_req(start=start, stop=stop)

        self.feed_pieces()

        data = self.read_all(req)

        self.assertEqual(data, tdummy.DATA[start:stop])

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

    def test_existing_torrent(self):
        req = self.add_req()

        self.feed_pieces()

        self.read_all(req)

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

        req = self.add_req()
        data = self.read_all(req, msg="second read")

        self.assertEqual(data, tdummy.DATA)

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

    def test_simultaneous(self):
        req1 = self.add_req()
        req2 = self.add_req()

        self.feed_pieces()

        chunks1 = []
        chunks2 = []

        def read_and_check():
            while req1.has_next():
                chunk = req1.get_next(timeout=0)
                if not chunk:
                    break
                chunks1.append(bytes(chunk))
            while req2.has_next():
                chunk = req2.get_next(timeout=0)
                if not chunk:
                    break
                chunks2.append(bytes(chunk))
            return not (req1.has_next() or req2.has_next())

        self.pump_alerts(read_and_check, msg="read all data")
        self.assertEqual(b"".join(chunks1), tdummy.DATA)
        self.assertEqual(b"".join(chunks2), tdummy.DATA)

        self.pump_alerts(lambda: not (req1.active or req2.active),
                         msg="deactivate")
        self.assertIsNone(req1.exception)
        self.assertIsNone(req2.exception)

    def test_two_readers(self):
        req1 = self.add_req()
        req2 = self.add_req()

        self.feed_pieces()

        data1 = self.read_all(req1)
        data2 = self.read_all(req2)

        self.assertEqual(data1, tdummy.DATA)
        self.assertEqual(data2, tdummy.DATA)

        self.pump_alerts(lambda: not (req1.active or req2.active),
                         msg="deactivate")
        self.assertIsNone(req1.exception)
        self.assertIsNone(req2.exception)

    def test_download(self):
        seed = test_utils.create_isolated_session()
        seed_dir = tempfile.TemporaryDirectory()
        atp = lt.add_torrent_params()
        atp.ti = lt.torrent_info(tdummy.DICT)
        atp.save_path = seed_dir.name
        atp.flags &= ~lt.torrent_flags.paused
        handle = seed.add_torrent(atp)
        # https://github.com/arvidn/libtorrent/issues/4980: add_piece() while
        # checking silently fails in libtorrent 1.2.8.
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(tdummy.PIECES):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        req = self.add_req()
        self.wait_for_torrent().connect_peer(("127.0.0.1", seed.listen_port()))

        # The peer connection takes a long time, not sure why
        data = self.read_all(req, timeout=60)
        self.assertEqual(data, tdummy.DATA)

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

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
            self.read_all(req)

        self.assertFalse(req.active)
        self.assertIsInstance(req.exception, NotADirectoryError)

    def test_read_checked_pieces(self):
        # Download a torrent
        req = self.add_req()
        self.feed_pieces()
        data = self.read_all(req)
        self.assertEqual(data, tdummy.DATA)

        # Wait for the file to be written to disk
        def file_written():
            path = os.path.join(self.tempdir.name, tdummy.NAME.decode())
            if not os.path.exists(path):
                return False
            data = open(path, mode="rb").read()
            return data == tdummy.DATA

        self.pump_alerts(file_written, msg="write file")

        # Create a new session
        self.init_session()
        req = self.add_req()

        # We should be able to read the data without feeding pieces
        data = self.read_all(req)
        self.assertEqual(data, tdummy.DATA)

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

    def test_read_after_cancelled_read(self):
        # Start reading
        req = self.add_req()
        # Feed one piece, so the torrent stays in the session
        self.feed_pieces(piece_indexes=(0,))

        def prioritized():
            return all(self.wait_for_torrent().piece_priorities())

        self.pump_alerts(prioritized, msg="prioritize")

        # Cancel the request -- resets piece deadlines
        req.cancel()

        # Wait until deadlines have been reset
        def deprioritized():
            handle = self.wait_for_torrent()
            priorities = handle.piece_priorities()
            return not any(priorities[1:])

        self.pump_alerts(deprioritized, msg="deprioritize")

        # Recreate the request -- listens for read_piece_alert
        req = self.add_req()
        # Feed all pieces and check that we can read the data
        self.feed_pieces()

        data = self.read_all(req)
        self.assertEqual(data, tdummy.DATA)

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)


class TestPriorities(request_test_utils.RequestServiceTestCase):

    def test_priorities(self):

        def add_req(mode_name, start_piece, stop_piece):
            self.add_req(mode=getattr(request_lib.Mode, mode_name),
                         start=start_piece * tdummy.PIECE_LENGTH,
                         stop=stop_piece * tdummy.PIECE_LENGTH)

        assert len(tdummy.DATA) / tdummy.PIECE_LENGTH >= 9
        # One fill request for the whole torrent
        add_req("FILL", 0, 9)
        # Two readahead requests, actually "behind" and overlapping the read
        # requests
        add_req("READAHEAD", 1, 5)
        add_req("READAHEAD", 5, 9)
        # Two read requests, should be prioritized over readahead
        add_req("READ", 3, 5)
        add_req("READ", 7, 9)

        def check_prioritized():
            return any(self.wait_for_torrent().get_piece_priorities())

        self.pump_alerts(check_prioritized, msg="prioritize")
        handle = self.wait_for_torrent()

        self.assertLessEqual(
            set({
                0: 1,
                1: 7,
                2: 7,
                3: 7,
                4: 7,
                5: 7,
                6: 7,
                7: 7,
                8: 7
            }.items()),
            set(dict(enumerate(handle.get_piece_priorities())).items()))
        # libtorrent doesn't expose piece deadlines, so whitebox test here
        # pylint: disable=protected-access
        torrent = self.service._torrents[tdummy.INFOHASH]
        # pylint: disable=protected-access
        self.assertEqual(torrent._piece_seq, {
            1: 2,
            2: 3,
            3: 0,
            4: 1,
            5: 2,
            6: 3,
            7: 0,
            8: 1
        })
        # pylint: disable=protected-access
        self.assertEqual(torrent._piece_reading, {3, 4, 7, 8})

    def test_with_have_pieces(self):

        def add_req(mode_name, start_piece, stop_piece):
            self.add_req(mode=getattr(request_lib.Mode, mode_name),
                         start=start_piece * tdummy.PIECE_LENGTH,
                         stop=stop_piece * tdummy.PIECE_LENGTH)

        assert len(tdummy.DATA) / tdummy.PIECE_LENGTH >= 9
        # One fill request for the whole torrent
        add_req("FILL", 0, 9)
        # Two readahead requests, actually "behind" and overlapping the read
        # requests
        add_req("READAHEAD", 1, 5)
        add_req("READAHEAD", 5, 9)
        # Two read requests, should be prioritized over readahead
        add_req("READ", 3, 5)
        add_req("READ", 7, 9)

        self.feed_pieces(piece_indexes=(1, 3, 5, 7))

        def check_prioritized():
            handle = self.wait_for_torrent()
            prio_dict = dict(enumerate(handle.get_piece_priorities()))
            if set({
                    0: 1,
                    2: 7,
                    4: 7,
                    6: 7,
                    8: 7
            }.items()) > set(prio_dict.items()):
                logging.debug("prio is %s", handle.get_piece_priorities())
                return False
            # libtorrent doesn't expose piece deadlines, so whitebox test here
            # pylint: disable=protected-access
            torrent = self.service._torrents[tdummy.INFOHASH]
            # pylint: disable=protected-access
            if torrent._piece_seq != {2: 1, 4: 0, 6: 1, 8: 0}:
                # pylint: disable=protected-access
                logging.debug("seq is %s", torrent._piece_seq)
                return False
            # pylint: disable=protected-access
            if torrent._piece_reading != {4, 8}:
                # pylint: disable=protected-access
                logging.debug("reading is %s", torrent._piece_reading)
                return False
            return True

        self.pump_alerts(check_prioritized, msg="prioritize")


class TestRemoveTorrent(request_test_utils.RequestServiceTestCase):

    def test_with_active_requests(self):
        req = self.add_req()
        self.service.remove_torrent(tdummy.INFOHASH)
        self.assertIsInstance(req.exception, request_lib.CancelledError)

    def test_keep_data(self):
        req = self.add_req()
        self.feed_pieces()

        self.read_all(req)

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

        self.service.remove_torrent(tdummy.INFOHASH, remove_data=False)

        self.pump_alerts(lambda: not self.session.get_torrents(), msg="remove")

        self.assertEqual(os.listdir(self.tempdir.name), [tdummy.NAME.decode()])
        self.assertIsNone(req.exception)

    def test_remove_data(self):
        req = self.add_req()
        self.feed_pieces()

        self.read_all(req)

        self.pump_alerts(lambda: not req.active, msg="deactivate")
        self.assertIsNone(req.exception)

        self.service.remove_torrent(tdummy.INFOHASH, remove_data=True)

        def removed():
            return os.listdir(self.tempdir.name) == []

        self.pump_alerts(removed, msg="remove")
        self.assertIsNone(req.exception)


class TestLoad(request_test_utils.RequestServiceTestCase):

    def test_load_resume_data_and_read(self):
        # Download a torrent
        req = self.add_req()
        self.feed_pieces()
        self.pump_alerts(lambda: not req.active, "finish/deactivate")

        # Save the resume data
        handle = self.wait_for_torrent()
        self.session.pause()
        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
        alert = self.pump_and_find_first_alert(
            lambda alert: isinstance(alert, lt.save_resume_data_alert))
        resume_data = alert.resume_data

        # Start a new session and load the resume data
        self.init_session()
        atp = lt.read_resume_data(lt.bencode(resume_data))
        self.service.add_torrent(atp)

        # A request should complete as normal
        req = self.add_req()
        data = self.read_all(req)
        self.assertEqual(data, tdummy.DATA)

        self.pump_alerts(lambda: not req.active, msg="request deactivated")
        self.assertIsNone(req.exception)

    def test_load_corrupted_and_read(self):
        # Download a torrent
        req = self.add_req()
        self.feed_pieces()
        self.pump_alerts(lambda: not req.active, "finish/deactivate")

        # Close the session
        handle = self.wait_for_torrent()
        self.session.pause()
        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
        alert = self.pump_and_find_first_alert(
            lambda a: isinstance(a, lt.save_resume_data_alert))
        resume_data = alert.resume_data

        # Corrupt the data
        with open(os.path.join(self.tempdir.name, tdummy.NAME.decode()),
                  mode="w") as fp:
            fp.write("corrupted!")

        # Open a new session, and load the torrent with resume data
        self.init_session()
        atp = lt.read_resume_data(lt.bencode(resume_data))
        self.service.add_torrent(atp)
        req = self.add_req()

        # The torrent should find the files corrupted and try to download
        def not_checking():
            handle = self.wait_for_torrent()
            return handle.status().state not in (
                lt.torrent_status.states.allocating,
                lt.torrent_status.states.checking_resume_data,
                lt.torrent_status.states.checking_files)

        self.pump_alerts(not_checking, msg="finish checking")

        # Feed the pieces
        self.feed_pieces()

        # The request should read the correct data
        data = self.read_all(req, msg="second read")
        self.assertEqual(data, tdummy.DATA)

        self.pump_alerts(lambda: not req.active, msg="request deactivated")
        self.assertIsNone(req.exception)


class TestConfig(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_dir = pathlib.Path(self.tempdir.name)
        self.config = config_lib.Config()
        self.session = test_utils.create_isolated_session()
        self.service = request_lib.RequestService(session=self.session,
                                                  config=self.config,
                                                  config_dir=self.config_dir)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_config_defaults(self):
        save_path = str(self.config_dir.joinpath("downloads"))
        self.assertEqual(self.config,
                         config_lib.Config(torrent_default_save_path=save_path))

        self.assertEqual(self.service.get_atp_settings(),
                         dict(save_path=save_path))

    def test_set_config(self):
        # Set all non-default configs
        self.config["torrent_default_save_path"] = self.tempdir.name
        self.config["torrent_default_flags_apply_ip_filter"] = False
        self.config["torrent_default_storage_mode"] = "allocate"
        self.service.set_config(self.config)

        self.assertEqual(
            self.service.get_atp_settings(),
            dict(save_path=self.tempdir.name,
                 flags=lt.torrent_flags.default_flags &
                 ~lt.torrent_flags.apply_ip_filter,
                 storage_mode=lt.storage_mode_t.storage_mode_allocate))

        # Set some default configs
        self.config["torrent_default_flags_apply_ip_filter"] = True
        self.config["torrent_default_storage_mode"] = "sparse"
        self.service.set_config(self.config)

        self.assertEqual(
            self.service.get_atp_settings(),
            dict(save_path=self.tempdir.name,
                 flags=lt.torrent_flags.default_flags |
                 lt.torrent_flags.apply_ip_filter,
                 storage_mode=lt.storage_mode_t.storage_mode_sparse))

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
