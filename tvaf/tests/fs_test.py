"""Tests for the tvaf.fs module."""

import unittest
import stat as stat_lib

from tvaf import fs


class TestLookup(unittest.TestCase):
    """Tests for tvaf.fs.lookup()."""

    def setUp(self):
        self.root = fs.StaticDir()
        self.directory = fs.StaticDir()
        self.file = fs.File()
        self.root.mkchild("directory", self.directory)
        self.directory.mkchild("file", self.file)

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
        self.dir.mkchild("foo", self.file1)
        self.dir.mkchild("bar", self.file2)

    def test_readdir(self):
        dirents = list(self.dir.readdir())
        self.assertEqual(len(dirents), 2)
        self.assertEqual({d.name for d in dirents}, {"foo", "bar"})
        self.assertEqual({d.stat.size for d in dirents}, {10, 100})

    def test_readdir_offset(self):
        dirents = list(self.dir.readdir(offset=0))
        first = dirents[0]
        offset = first.next_offset
        dirents = list(self.dir.readdir(offset=offset))
        self.assertEqual(len(dirents), 1)
        second = dirents[0]
        self.assertNotEqual(first.name, second.name)


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
