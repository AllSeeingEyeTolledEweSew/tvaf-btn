import pathlib
import tempfile
import unittest

import libtorrent as lt

from tvaf import resume as resume_lib

from . import tdummy
from . import test_utils


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


class BaseTest(unittest.TestCase):

    def setUp(self):
        self.session = test_utils.create_isolated_session()
        self.torrent = tdummy.DEFAULT
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_dir = pathlib.Path(self.tempdir.name)
        self.resume_data_dir = self.config_dir.joinpath(
            resume_lib.RESUME_DATA_DIR_NAME)
        self.resume = resume_lib.ResumeService(session=self.session,
                                               config_dir=self.config_dir,
                                               inline=True)
        self.driver = test_utils.InlineDriver()
        self.driver.session = self.session
        self.driver.handlers.append(self.resume.handle_alert)
        self.driver.tickers.append(self.resume)

    def tearDown(self):
        self.tempdir.cleanup()

    def assert_atp_equal(self, got, expected):
        self.assertEqual(atp_comparable(got), atp_comparable(expected))

    def assert_atp_list_equal(self, got, expected):
        self.assertEqual([atp_comparable(atp) for atp in got],
                         [atp_comparable(atp) for atp in expected])

    def assert_atp_sets_equal(self, got, expected):
        self.assertEqual(set(atp_hashable(atp) for atp in got),
                         set(atp_hashable(atp) for atp in expected))


class IterResumeDataTest(BaseTest):

    maxDiff = None

    TORRENT1 = tdummy.Torrent.single_file(name=b"1.txt", length=1024)
    TORRENT2 = tdummy.Torrent.single_file(name=b"2.txt", length=1024)
    TORRENT3 = tdummy.Torrent.single_file(name=b"3.txt", length=1024)

    def setUp(self):
        super().setUp()

        def write(torrent):
            self.resume_data_dir.mkdir(parents=True, exist_ok=True)
            path = self.resume_data_dir.joinpath(
                torrent.infohash).with_suffix(".resume")
            data = lt.bencode(lt.write_resume_data(torrent.atp()))
            path.write_bytes(data)

        write(self.TORRENT1)
        write(self.TORRENT2)

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


class AbortTest(BaseTest):

    def test_mid_download(self):
        have_block = set()

        def handle_alert(alert):
            if isinstance(alert, lt.block_finished_alert):
                have_block.add((alert.piece_index, alert.block_index))

        self.driver.handlers.append(handle_alert)
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)

        def is_downloading():
            status = handle.status()
            return status.state == status.downloading

        self.driver.pump(is_downloading, msg="downloading state")
        # NB: bug in libtorrent where add_piece accepts str but not bytes
        handle.add_piece(0, self.torrent.pieces[0].decode(), 0)
        self.driver.pump(lambda: have_block, msg="piece finish")
        self.session.pause()
        self.resume.abort()

        def check_atp():
            atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
            if not atps:
                return False
            atp = atps[0]
            return atp.have_pieces and atp.have_pieces[0]

        self.driver.pump(check_atp, msg="resume data write")
        self.driver.pump(self.resume.done, msg="resume data write")
        self.resume.wait()

    def test_finished(self):
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)

        def is_downloading():
            status = handle.status()
            return status.state == status.downloading

        self.driver.pump(is_downloading, msg="downloading state")
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        def is_finished():
            status = handle.status()
            return status.state in (status.finished, status.seeding)

        self.driver.pump(is_finished, msg="finished state")
        self.session.pause()
        self.resume.abort()

        def check_atp():
            atps = list(resume_lib.iter_resume_data_from_disk(self.config_dir))
            if not atps:
                return False
            atp = atps[0]
            return atp.have_pieces and all(atp.have_pieces)

        self.driver.pump(check_atp, msg="resume data write")
        self.driver.pump(self.resume.done, msg="finalize")
        self.resume.wait()

    def test_finish_remove_abort_quickly(self):
        atp = self.torrent.atp()
        atp.flags &= ~lt.torrent_flags.paused
        atp.save_path = self.tempdir.name
        handle = self.session.add_torrent(atp)

        def is_downloading():
            status = handle.status()
            return status.state == status.downloading

        self.driver.pump(is_downloading, msg="downloading state")
        for i, piece in enumerate(self.torrent.pieces):
            # NB: bug in libtorrent where add_piece accepts str but not bytes
            handle.add_piece(i, piece.decode(), 0)

        def is_finished():
            status = handle.status()
            return status.state in (status.finished, status.seeding)

        self.driver.pump(is_finished, msg="finished state")
        # Remove, pause and abort before we process any alerts. ResumeService
        # should try to save_resume_data() on an invalid handle. This is
        # timing-dependent but I don't have a way to force it.
        self.session.remove_torrent(handle)
        self.session.pause()
        self.resume.abort()

        def no_resume_data():
            return not list(
                resume_lib.iter_resume_data_from_disk(self.config_dir))

        self.driver.pump(no_resume_data, msg="resume data delete")
        self.driver.pump(self.resume.done, msg="finalize")
        self.resume.wait()
