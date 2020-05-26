"""Tests for the tvaf.fs module."""

import stat as stat_lib
import unittest
import pathlib

from tvaf import fs


class TestLookup(unittest.TestCase):
    """Tests for tvaf.fs.lookup()."""

    def setUp(self):
        self.root = fs.StaticDir()
        self.directory = fs.StaticDir()
        self.file = fs.File(size=0)
        self.root.mkchild(self.directory, "directory")
        self.directory.mkchild(self.file, "file")

    def test_empty(self):
        self.assertIs(fs.lookup(self.root, ""), self.root)

    def test_directory(self):
        self.assertIs(fs.lookup(self.root, "directory"), self.directory)

    def test_file(self):
        self.assertIs(fs.lookup(self.root, "directory/file"), self.file)

    def test_normalize(self):
        self.assertIs(fs.lookup(self.root, "directory//file/"), self.file)

    def test_not_found(self):
        with self.assertRaises(FileNotFoundError):
            fs.lookup(self.root, "does_not_exist")

    def test_not_dir(self):
        with self.assertRaises(NotADirectoryError):
            fs.lookup(self.root, "directory/file/subpath")


class TestFile(unittest.TestCase):
    """Tests for tvaf.fs.File."""

    def test_stat(self):
        stat = fs.File(size=0).stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFREG)
        self.assertEqual(stat.size, 0)
        self.assertIs(stat.mtime, None)

    def test_torrent_ref_none(self):
        # pylint: disable=assignment-from-none
        ref = fs.File().get_torrent_ref()
        self.assertIs(ref, None)


class TestDir(unittest.TestCase):
    """Tests for tvaf.fs.Dir."""

    def get_dir(self):
        """Returns a Dir object to test."""
        # pylint: disable=no-self-use
        return fs.Dir()

    def test_stat(self):
        obj = self.get_dir()
        self.assertEqual(obj.filetype, stat_lib.S_IFDIR)
        stat = obj.stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFDIR)


class TestStaticDir(TestDir):
    """Tests for tvaf.fs.StaticDir."""

    def get_dir(self):
        """Returns a StaticDir object to test."""
        # pylint: disable=no-self-use
        return fs.StaticDir()

    def setUp(self):
        self.dir = self.get_dir()
        self.file1 = fs.TorrentFile(start=0, stop=10, mtime=0)
        self.file2 = fs.TorrentFile(start=0, stop=100, mtime=12345)
        self.dir.mkchild(self.file1, "foo")
        self.dir.mkchild(self.file2, "bar")

    def test_readdir(self):
        dirents = list(self.dir.readdir())
        self.assertEqual(len(dirents), 2)
        self.assertEqual({d.name for d in dirents}, {"foo", "bar"})
        self.assertEqual({d.stat.size for d in dirents}, {10, 100})


class TestTorrentFile(unittest.TestCase):
    """Tests for tvaf.fs.TorrentFile."""

    def setUp(self):
        self.tfile = fs.TorrentFile(
            tracker="foo",
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            start=0,
            stop=1048576,
            mtime=12345678)

    def test_stat(self):
        stat = self.tfile.stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFREG)
        self.assertEqual(stat.size, 1048576)
        self.assertEqual(stat.mtime, 12345678)

    def test_torrent_ref(self):
        ref = self.tfile.get_torrent_ref()
        self.assertEqual(
            ref,
            fs.TorrentRef(tracker="foo",
                          infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                          start=0,
                          stop=1048576))


class TestSymlink(unittest.TestCase):

    def setUp(self):
        self.root = fs.StaticDir()
        self.dir1 = fs.StaticDir(name="dir1")
        self.dir2 = fs.StaticDir(name="dir2")
        self.root.mkchild(self.dir1)
        self.root.mkchild(self.dir2)
        self.file = fs.File(name="file")
        self.dir2.mkchild(self.file)
        self.symlink = fs.Symlink(name="symlink")
        self.dir1.mkchild(self.symlink)

    def test_no_target(self):
        with self.assertRaises(OSError):
            self.symlink.readlink()

    def test_str_target(self):
        self.symlink.target = "other"
        self.assertEqual(self.symlink.readlink(), pathlib.PurePath("other"))

    def test_obj_target(self):
        self.symlink.target = self.file
        self.assertEqual(self.symlink.readlink(),
                pathlib.PurePath("../dir2/file"))
