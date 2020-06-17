import unittest
import stat as stat_lib
from typing import Iterable
from typing import Tuple
from typing import Optional
from typing import cast
import io
from . import tdummy
from tvaf import library
from typing import Union
import libtorrent as lt
from tvaf import fs
from tvaf import protocol
from typing import Dict


SINGLE = tdummy.Torrent.single_file(name=b"test.txt", length=16384 * 9 + 1000)
MULTI = tdummy.Torrent(files=[
    dict(length=10000, path=b"multi/file.tar.gz"),
    dict(length=100, path=b"multi/info.nfo"),
])
PADDED = tdummy.Torrent(files=[
    dict(length=10000, path=b"padded/file.tar.gz"),
    dict(length=6384, path=b"padded/.pad/6834", attr=b"p"),
    dict(length=100, path=b"padded/info.nfo"),
])
CONFLICT_FILE = tdummy.Torrent(files=[
    dict(length=100, path=b"conflict/file.zip"),
    dict(length=200, path=b"conflict/file.zip"),
])
CONFLICT_FILE_DIR = tdummy.Torrent(files=[
    dict(length=100, path=b"conflict/path/file.zip"),
    dict(length=200, path=b"conflict/path"),
])
CONFLICT_DIR_FILE = tdummy.Torrent(files=[
    dict(length=100, path=b"conflict/path"),
    dict(length=200, path=b"conflict/path/file.zip"),
])
BAD_PATHS = tdummy.Torrent(files=[
    dict(length=10, path=b"bad/./file"),
    dict(length=20, path=b"bad/../file"),
    dict(length=30, path_split=[b"bad", b"slash/slash", b"file"]),
])


def get_placeholder_data(info_hash:str, start:int, stop:int) -> bytes:
    data = "%s:%d:%d" % (info_hash, start, stop)
    return data.encode()


class TestLibraryService(unittest.TestCase):

    def setUp(self):
        self.torrents = {t.infohash: t for t in (SINGLE, MULTI, PADDED,
            CONFLICT_FILE, CONFLICT_FILE_DIR, CONFLICT_DIR_FILE, BAD_PATHS)}
        self.hints = {
            (SINGLE.infohash, 0): library.Hints(mime_type="text/plain"),
            (MULTI.infohash, 0): library.Hints(mime_type="application/x-tar",
                content_encoding="gzip"),
            (MULTI.infohash, 1): library.Hints(mime_type="text/plain"),
        }

        def opener(infohash:str, start:int, stop:int,
                get_torrent:library.GetTorrent):
            raw = io.BytesIO(get_placeholder_data(infohash, start, stop))
            # opener can normally return a RawIOBase, but we'll mimic
            # IOService returning BufferedTorrentIO here.
            return io.BufferedReader(raw)

        self.libs = library.LibraryService(opener=opener)
        self.libs.get_layout_info_dict_funcs["test"] = self.get_layout_info_dict
        self.libs.get_hints_funcs["test"] = self.get_hints
        self.libs.get_access_funcs["test"] = self.get_access

    def get_layout_info_dict(self, info_hash):
        return self.torrents[info_hash].info

    def get_hints(self, info_hash, index):
        return self.hints[(info_hash, index)]

    def get_access(self, info_hash):
        t = self.torrents[info_hash]
        return library.Access(seeders=100, get_torrent=lambda: lt.bencode(t.dict))

    def assert_torrent_file(self, tfile:library.TorrentFile, *,
            info_hash:str=None, start:int=None, stop:int=None, torrent:bytes=None,
            dummy:tdummy.Torrent=None, dummy_file:Union[tdummy.File, int]=None,
            mime_type:str=None, content_encoding:str=None, mtime:int=None,
            filename:str=None):
        if dummy is not None:
            info_hash = dummy.infohash
            torrent = lt.bencode(dummy.dict)
        if dummy_file is not None:
            if type(dummy_file) is int:
                assert dummy is not None
                dummy_file = dummy.files[dummy_file]
            start = dummy_file.start
            stop = dummy_file.stop
            filename = protocol.decode(dummy_file.path_split[-1])
        assert filename is not None
        assert info_hash is not None
        assert start is not None
        assert stop is not None
        assert torrent is not None

        self.assertEqual(tfile.info_hash, info_hash)
        self.assertEqual(tfile.start, start)
        self.assertEqual(tfile.stop, stop)
        self.assertEqual(tfile.get_torrent(), torrent)
        self.assertEqual(tfile.hints.get("mtime"), mtime)
        self.assertEqual(tfile.hints.get("mime_type"), mime_type)
        self.assertEqual(tfile.hints.get("content_encoding"), content_encoding)
        self.assertEqual(tfile.hints.get("filename"), filename)
        self.assertEqual(tfile.open(mode="rb").read(),
                get_placeholder_data(info_hash, start, stop))

    def assert_is_dir(self, node:fs.Node):
        self.assertEqual(node.stat().filetype, stat_lib.S_IFDIR)

    def assert_is_regular_file(self, node:fs.Node):
        self.assertEqual(node.stat().filetype, stat_lib.S_IFREG)

    def assert_is_symlink(self, node:fs.Node):
        self.assertEqual(node.stat().filetype, stat_lib.S_IFLNK)

    def assert_dirents_like(self, dirents:Iterable[fs.Dirent],
            expected:Iterable[Tuple[str, Optional[int], str]]):
        got = [(stat_lib.filemode(d.stat.filetype), d.stat.mtime, d.name) for d in dirents]
        expected = list(expected)
        # Test file types only
        if expected and len(expected[0][0]) == 1:
            got = [(mode[0], mtime, name) for mode, mtime, name in got]
        self.assertCountEqual(got, expected)

    def test_get_torrent_path(self):
        for info_hash in self.torrents:
            path = self.libs.get_torrent_path(info_hash)
            torrent_dir = self.libs.root.traverse(path)
            self.assert_is_dir(torrent_dir)

    def test_lookup_torrent(self):
        for info_hash in self.torrents:
            torrent_dir = self.libs.lookup_torrent(info_hash)
            self.assert_is_dir(torrent_dir)

    def test_get_info_dict_func_fails(self):
        def whoops(info_hash):
            raise RuntimeError("whoops")
        self.libs.get_layout_info_dict_funcs["whoops"] = whoops

        # Test the failer doesn't interfere with torrents known to other
        # libraries
        self.libs.root.traverse(f"v1/{SINGLE.infohash}/test/i/0")

        # Ensure it gets called, but correct error is thrown
        with self.assertRaises(FileNotFoundError):
            self.libs.root.traverse(f"v1/{'0'*40}")

    def test_get_access_func_fails(self):
        def whoops(info_hash):
            raise RuntimeError("whoops")
        self.libs.get_access_funcs["whoops"] = whoops

        # Test the failer doesn't show up in readdir
        torrent_dir = self.libs.root.traverse(f"v1/{SINGLE.infohash}")
        self.assert_dirents_like(torrent_dir.readdir(), [("d", None, "test")])

        # Ensure it gets called, but correct error is thrown
        with self.assertRaises(FileNotFoundError):
            self.libs.root.traverse(f"v1/{SINGLE.infohash}/whoops/i/0")

    def test_get_hints_func_fails(self):
        def whoops(info_hash, index):
            raise RuntimeError("whoops")
        self.libs.get_hints_funcs["whoops"] = whoops

        # Test the failer doesn't interfere with other hints
        tfile = cast(library.TorrentFile, self.libs.root.traverse(
            f"v1/{SINGLE.infohash}/test/i/0"))
        self.assert_torrent_file(tfile, dummy=SINGLE,
                dummy_file=0, mime_type="text/plain")

    def test_hints_with_mtime(self):
        def get_mtime(info_hash, index):
            return library.Hints(mtime=12345)
        self.libs.get_hints_funcs["mtime"] = get_mtime

        tfile = cast(library.TorrentFile, self.libs.root.traverse(
            f"v1/{SINGLE.infohash}/test/i/0"))
        self.assertEqual(tfile.hints["mtime"], 12345)
        self.assertEqual(tfile.stat().mtime, 12345)

        by_index = cast(fs.Dir, self.libs.root.traverse(f"v1/{SINGLE.infohash}/test/i"))
        self.assert_dirents_like(by_index.readdir(), [("-", 12345, "0")])

    def test_browse(self):
        test_dir = fs.StaticDir()
        test_dir.mkchild("single", fs.Symlink(target=self.libs.lookup_torrent(
            SINGLE.infohash)))
        self.libs.browse_nodes["test"] = test_dir

        browse = self.libs.root.traverse("browse")
        self.assert_dirents_like(browse.readdir(), [("d", None, "test")])

        test_dir = cast(fs.Dir, browse.lookup("test"))
        self.assert_is_dir(test_dir)

        link = cast(fs.Symlink, self.libs.root.traverse(
            "browse/test/single", follow_symlinks=False))
        self.assertEqual(str(link.readlink()), f"../../v1/{SINGLE.infohash}")

    def test_v1_lookup(self):
        for info_hash in self.torrents:
            self.assert_is_dir(self.libs.root.traverse(f"v1/{info_hash}"))

    def test_v1_lookup_bad(self):
        v1 = self.libs.root.traverse("v1")
        with self.assertRaises(FileNotFoundError):
            v1.lookup("0" * 40)

    def test_v1_readdir(self):
        v1 = self.libs.root.traverse("v1")
        with self.assertRaises(OSError):
            list(v1.readdir())

    def test_torrent_dir_readdir(self):
        for info_hash in self.torrents:
            torrent_dir = cast(fs.Dir, self.libs.root.traverse(f"v1/{info_hash}"))
            self.assert_dirents_like(torrent_dir.readdir(), [("d", None,
                "test")])

    def test_torrent_dir_lookup(self):
        for info_hash in self.torrents:
            self.assert_is_dir(self.libs.root.traverse(
                f"v1/{info_hash}/test"))

    def test_torrent_dir_lookup_bad(self):
        for info_hash in self.torrents:
            with self.assertRaises(FileNotFoundError):
                self.assert_is_dir(self.libs.root.traverse(
                    f"v1/{info_hash}/does-not-exist"))

    def test_torrent_dir_with_no_access(self):
        dummy = tdummy.Torrent.single_file(name=b"test.txt", length=100)
        def get_info_dict(info_hash):
            return {dummy.infohash: dummy}[info_hash]
        self.libs.get_layout_info_dict_funcs["dummy"] = get_info_dict

        torrent_dir = self.libs.root.traverse(f"v1/{dummy.infohash}")
        self.assert_dirents_like(torrent_dir.readdir(), [])

    def test_torrent_dir_with_redirect_access(self):
        def get_redirect(info_hash):
            return library.Access(redirect_to="test")
        self.libs.get_access_funcs["redirect"] = get_redirect

        torrent_dir = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{SINGLE.infohash}"))
        self.assert_dirents_like(torrent_dir.readdir(), [("l", None,
            "redirect"), ("d", None, "test")])

        link = cast(fs.Symlink, torrent_dir.lookup("redirect"))
        self.assertEqual(str(link.readlink()), "test")

    def test_access_readdir(self):
        for info_hash in self.torrents:
            access = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{info_hash}/test"))
            self.assert_dirents_like(access.readdir(), [("d", None, "f"), ("d",
                None, "i")])

    def test_access_lookup(self):
        for info_hash in self.torrents:
            self.assert_is_dir(self.libs.root.traverse(f"v1/{info_hash}/test/f"))
            self.assert_is_dir(self.libs.root.traverse(f"v1/{info_hash}/test/i"))

    def test_by_path_single(self):
        by_path = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{SINGLE.infohash}/test/f"))

        self.assert_dirents_like(by_path.readdir(), [("l", None, "test.txt")])

        link = cast(fs.Symlink, by_path.lookup("test.txt"))
        self.assert_is_symlink(link)
        self.assertEqual(str(link.readlink()), "../i/0")

    def test_by_index_single(self):
        by_index = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{SINGLE.infohash}/test/i"))

        self.assert_dirents_like(by_index.readdir(), [("-", None, "0")])

        tfile = cast(library.TorrentFile, by_index.lookup("0"))
        self.assert_torrent_file(tfile, dummy=SINGLE,
                dummy_file=0, mime_type="text/plain")

    def test_by_path_multi(self):
        by_path = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{MULTI.infohash}/test/f"))

        self.assert_dirents_like(by_path.readdir(), [("d", None, "multi")])

        subdir = cast(fs.Dir, by_path.lookup("multi"))
        self.assert_is_dir(subdir)

        self.assert_dirents_like(subdir.readdir(), [("l", None, "file.tar.gz"),
            ("l", None, "info.nfo")])

        link = cast(fs.Symlink, subdir.lookup("file.tar.gz"))
        self.assert_is_symlink(link)
        self.assertEqual(str(link.readlink()), "../../i/0")

        link = cast(fs.Symlink, subdir.lookup("info.nfo"))
        self.assert_is_symlink(link)
        self.assertEqual(str(link.readlink()), "../../i/1")

    def test_by_index_multi(self):
        by_index = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{MULTI.infohash}/test/i"))

        self.assert_dirents_like(by_index.readdir(), [("-", None, "0"), ("-",
            None, "1")])

        tfile = cast(library.TorrentFile, by_index.lookup("0"))
        self.assert_torrent_file(tfile, dummy=MULTI,
                dummy_file=0, mime_type="application/x-tar",
                content_encoding="gzip")

        tfile = cast(library.TorrentFile, by_index.lookup("1"))
        self.assert_torrent_file(tfile, dummy=MULTI,
                dummy_file=1, mime_type="text/plain")

    def test_conflict_file(self):
        # Don't test by-path directory, as its contents are undefined. Do test
        # that the by-index path still holds file references.
        by_index = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{CONFLICT_FILE.infohash}/test/i"))

        self.assert_dirents_like(by_index.readdir(), [("-", None, "0"), ("-",
            None, "1")])

        for i in range(len(CONFLICT_FILE.files)):
            tfile = cast(library.TorrentFile, by_index.lookup(str(i)))
            self.assert_torrent_file(tfile, dummy=CONFLICT_FILE,
                    dummy_file=i)

    def test_conflict_file_dir(self):
        # Don't test by-path directory, as its contents are undefined. Do test
        # that the by-index path still holds file references.
        by_index = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{CONFLICT_FILE_DIR.infohash}/test/i"))

        self.assert_dirents_like(by_index.readdir(), [("-", None, "0"), ("-",
            None, "1")])

        for i in range(len(CONFLICT_FILE_DIR.files)):
            tfile = cast(library.TorrentFile, by_index.lookup(str(i)))
            self.assert_torrent_file(tfile, dummy=CONFLICT_FILE_DIR,
                    dummy_file=i)

    def test_conflict_dir_file(self):
        # Don't test by-path directory, as its contents are undefined. Do test
        # that the by-index path still holds file references.
        by_index = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{CONFLICT_DIR_FILE.infohash}/test/i"))

        self.assert_dirents_like(by_index.readdir(), [("-", None, "0"), ("-",
            None, "1")])

        for i in range(len(CONFLICT_DIR_FILE.files)):
            tfile = cast(library.TorrentFile, by_index.lookup(str(i)))
            self.assert_torrent_file(tfile, dummy=CONFLICT_DIR_FILE,
                    dummy_file=i)

    def test_bad_paths(self):
        # All paths in BAD_PATHS are bad, so the by-path directory should be
        # empty.
        by_path = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{BAD_PATHS.infohash}/test/f"))
        self.assert_dirents_like(by_path.readdir(), [])

        by_index = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{BAD_PATHS.infohash}/test/i"))

        # Ensure we can still access files by index.
        self.assert_dirents_like(by_index.readdir(), [("-", None, "0"), ("-",
            None, "1"), ("-", None, "2")])

        for i in range(len(BAD_PATHS.files)):
            tfile = cast(library.TorrentFile, by_index.lookup(str(i)))
            self.assert_torrent_file(tfile, dummy=BAD_PATHS,
                    dummy_file=i)

    def test_padded(self):
        by_path = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{PADDED.infohash}/test/f/padded"))
        self.assert_dirents_like(by_path.readdir(), [("l", None,
            "file.tar.gz"), ("l", None, "info.nfo")])

        by_index = cast(fs.Dir, self.libs.root.traverse(
            f"v1/{PADDED.infohash}/test/i"))

        # Ensure we can still access files by index.
        self.assert_dirents_like(by_index.readdir(), [("-", None, "0"), ("-", None, "2")])

        for i in range(len(PADDED.files)):
            if b"p" in PADDED.files[i].attr:
                with self.assertRaises(FileNotFoundError):
                    by_index.lookup(str(i))
            else:
                tfile = cast(library.TorrentFile, by_index.lookup(str(i)))
                self.assert_torrent_file(tfile, dummy=PADDED,
                        dummy_file=i)
