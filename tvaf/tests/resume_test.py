import pathlib
import tempfile
import unittest

import libtorrent as lt

from tvaf import driver as driver_lib
from tvaf import ltpy
from tvaf import resume as resume_lib

from . import lib
from . import request_test_utils
from . import tdummy


def atp_dict_fixup(atp_dict):
    return lt.bdecode(lt.bencode(atp_dict))


def hashable(obj):
    if isinstance(obj, (list, tuple)):
        return tuple(hashable(x) for x in obj)
    if isinstance(obj, dict):
        return tuple(sorted((k, hashable(v)) for k, v in obj.items()))
    return obj


def atp_hashable(atp):
    return hashable(atp_dict_fixup(lt.write_resume_data(atp)))


def atp_comparable(atp):
    return atp_dict_fixup(lt.write_resume_data(atp))


class IterResumeDataTest(unittest.TestCase):

    maxDiff = None

    TORRENT1 = tdummy.Torrent.single_file(name=b"1.txt", length=1024)
    TORRENT2 = tdummy.Torrent.single_file(name=b"2.txt", length=1024)
    TORRENT3 = tdummy.Torrent.single_file(name=b"3.txt", length=1024)

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_dir = pathlib.Path(self.tempdir.name)
        self.resume_data_dir = self.config_dir.joinpath(
            resume_lib.RESUME_DATA_DIR_NAME)

        def write(torrent):
            self.resume_data_dir.mkdir(parents=True, exist_ok=True)
            path = self.resume_data_dir.joinpath(
                torrent.infohash).with_suffix(".resume")
            atp = torrent.atp()
            atp.ti = None
            atp_data = lt.bencode(lt.write_resume_data(atp))
            path.write_bytes(atp_data)
            ti_data = lt.bencode(torrent.dict)
            path.with_suffix(".torrent").write_bytes(ti_data)

        write(self.TORRENT1)
        write(self.TORRENT2)

    def assert_atp_equal(self, got, expected):
        self.assertEqual(atp_comparable(got), atp_comparable(expected))

    def assert_atp_list_equal(self, got, expected):
        self.assertEqual([atp_comparable(atp) for atp in got],
                         [atp_comparable(atp) for atp in expected])

    def assert_atp_sets_equal(self, got, expected):
        self.assertEqual(set(atp_hashable(atp) for atp in got),
                         set(atp_hashable(atp) for atp in expected))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_normal(self):
        atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
        self.assert_atp_sets_equal(
            set(atps), set((self.TORRENT1.atp(), self.TORRENT2.atp())))

    def test_ignore_bad_data(self):
        # valid resume data, wrong filename
        path = self.resume_data_dir.joinpath("00" * 20).with_suffix(".tmp")
        data = lt.bencode(lt.write_resume_data(self.TORRENT3.atp()))
        path.write_bytes(data)

        # valid resume data, wrong filename
        path = self.resume_data_dir.joinpath("whoopsie").with_suffix(".resume")
        data = lt.bencode(lt.write_resume_data(self.TORRENT3.atp()))
        path.write_bytes(data)

        # good file name, non-bencoded data
        path = self.resume_data_dir.joinpath("00" * 20).with_suffix(".resume")
        path.write_text("whoopsie")

        # good file name, bencoded data, but not a resume file
        path = self.resume_data_dir.joinpath("01" * 20).with_suffix(".resume")
        path.write_bytes(lt.bencode(self.TORRENT1.info))

        # good file name, inaccessible
        path = self.resume_data_dir.joinpath("02" * 20).with_suffix(".resume")
        path.symlink_to("does_not_exist.resume")

        atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
        self.assert_atp_sets_equal(
            set(atps), set((self.TORRENT1.atp(), self.TORRENT2.atp())))


class TerminateTest(unittest.TestCase):

    def setUp(self):
        self.session_service = lib.create_isolated_session_service()
        self.session = self.session_service.session
        self.torrent = tdummy.DEFAULT
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_dir = pathlib.Path(self.tempdir.name)
        self.resume_data_dir = self.config_dir.joinpath(
            resume_lib.RESUME_DATA_DIR_NAME)
        self.alert_driver = driver_lib.AlertDriver(
            session_service=self.session_service)
        self.resume = resume_lib.ResumeService(session=self.session,
                                               config_dir=self.config_dir,
                                               alert_driver=self.alert_driver,
                                               pedantic=True)
        self.resume.start()
        self.alert_driver.start()

    def tearDown(self):
        self.resume.terminate()
        self.resume.join()
        self.alert_driver.terminate()
        self.alert_driver.join()

        self.tempdir.cleanup()

    def test_mid_download(self):
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        request_test_utils.wait_done_checking_or_error(handle)
        # NB: bug in libtorrent where add_piece accepts str but not bytes
        handle.add_piece(0, self.torrent.pieces[0].decode(), 0)

        for _ in lib.loop_until_timeout(5, msg="piece finish"):
            status = handle.status(flags=lt.torrent_handle.query_pieces)
            if any(status.pieces):
                break

        # In 1.2.11+, save_resume_data() includes downloaded-but-not-checked
        # pieces in the unfinished_pieces field. See
        # https://github.com/arvidn/libtorrent/issues/5121
        if ltpy.version_info < (1, 2, 11):
            iterator = self.alert_driver.iter_alerts(lt.alert_category.storage,
                                                     lt.cache_flushed_alert,
                                                     handle=handle)
            with iterator:
                handle.flush_cache()
                for alert in iterator:
                    if isinstance(alert, lt.cache_flushed_alert):
                        break

        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        def atp_have_piece(atp: lt.add_torrent_params, index: int) -> bool:
            if atp.have_pieces[index]:
                return True
            ti = self.torrent.torrent_info()
            num_blocks = ((ti.piece_size(index) - 1) // 16384 + 1)
            bitmask = atp.unfinished_pieces.get(index, [])
            if len(bitmask) < num_blocks:
                return False
            return all(bitmask[i] for i in range(num_blocks))

        atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertTrue(atp_have_piece(atp, 0))

    def test_finished(self):
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        for _ in lib.loop_until_timeout(5, msg="finished state"):
            status = handle.status()
            if status.state in (status.finished, status.seeding):
                break

        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
        self.assertEqual(len(atps), 1)
        atp = atps[0]
        self.assertNotEqual(len(atp.have_pieces), 0)
        self.assertTrue(all(atp.have_pieces))

    def test_remove_before_save(self):
        for _ in lib.loop_until_timeout(5, msg="remove-before-save"):
            atp = self.torrent.atp()
            atp.flags &= ~lt.torrent_flags.paused
            atp.save_path = self.tempdir.name
            handle = self.session.add_torrent(atp)
            request_test_utils.wait_done_checking_or_error(handle)

            try:
                with ltpy.translate_exceptions():
                    self.session.remove_torrent(handle)
                    self.resume.save(handle)
                break
            except ltpy.InvalidTorrentHandleError:
                pass

        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
        self.assertEqual(atps, [])

    def test_finish_remove_terminate(self):
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)
        request_test_utils.wait_done_checking_or_error(handle)
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        for _ in lib.loop_until_timeout(5, msg="finished state"):
            status = handle.status()
            if status.state in (status.finished, status.seeding):
                break

        # Remove, pause and terminate before we process any alerts.
        # ResumeService should try to save_resume_data() on an invalid handle.
        # This is timing-dependent but I don't have a way to force it.
        self.session.remove_torrent(handle)
        self.session.pause()
        self.resume.terminate()
        self.resume.join()

        atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
        self.assertEqual(atps, [])


# TODO: test underflow, with and without pedantic

# TODO: test magnets

# TODO: test io errors, with and without pedantic

# TODO: test io errors when loading

# TODO: at end of tests, load atp into new session

# TODO: test save with invalid handle
