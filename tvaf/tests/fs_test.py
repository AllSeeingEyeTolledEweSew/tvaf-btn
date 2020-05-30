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
        self.root.mkchild("directory", self.directory)
        self.directory.mkchild("file", self.file)

    def test_empty(self):
        self.assertIs(fs.lookup(self.root, ""), self.root)
        self.assertIsNone(self.root.parent)
        self.assertIsNone(self.root.name)

    def test_directory(self):
        self.assertIs(fs.lookup(self.root, "directory"), self.directory)
        self.assertIs(self.directory.parent, self.root)
        self.assertEqual(self.directory.name, "directory")

    def test_file(self):
        self.assertIs(fs.lookup(self.root, "directory/file"), self.file)
        self.assertIs(self.directory.parent, self.root)
        self.assertEqual(self.directory.name, "directory")
        self.assertIs(self.file.parent, self.directory)
        self.assertEqual(self.file.name, "file")

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


class TestDir(unittest.TestCase):
    """Tests for tvaf.fs.Dir."""

    def setUp(self):
        self.dir = fs.Dir()
        self.file = fs.File(size=100)

        def lookup(name):
            if name == "foo":
                return self.file
            return None

        def readdir(self):
            return [fs.Dirent(name="foo", stat=self.file.stat())]

        self.dir._do_lookup = lookup
        self.dir.readdir = readdir

    def test_stat(self):
        self.assertEqual(self.dir.filetype, stat_lib.S_IFDIR)
        self.assertEqual(self.dir.stat().filetype, stat_lib.S_IFDIR)

    def test_lookup(self):
        obj = self.dir.lookup("foo")
        self.assertIs(obj, self.file)
        self.assertIs(obj.parent, self.dir)
        self.assertEqual(obj.name, "foo")

    def test_noent(self):
        with self.assertRaises(OSError):
            self.dir.lookup("does-not-exist")


class TestDictDir(unittest.TestCase):
    """Tests for tvaf.fs.Dir."""

    def setUp(self):
        self.dir = fs.DictDir()
        self.file1 = fs.File(size=100, mtime=0)
        self.file2 = fs.File(size=200, mtime=12345)
        self.dir.get_dict = lambda: dict(foo=self.file1, bar=self.file2)

    def test_stat(self):
        self.assertEqual(self.dir.filetype, stat_lib.S_IFDIR)
        self.assertEqual(self.dir.stat().filetype, stat_lib.S_IFDIR)

    def test_readdir(self):
        dirents = list(self.dir.readdir())
        self.assertEqual(len(dirents), 2)
        self.assertEqual({d.name for d in dirents}, {"foo", "bar"})
        self.assertEqual({d.stat.size for d in dirents}, {100, 200})

    def test_lookup(self):
        obj = self.dir.lookup("foo")
        self.assertIs(obj, self.file1)
        self.assertIs(obj.parent, self.dir)
        self.assertEqual(obj.name, "foo")

    def test_noent(self):
        with self.assertRaises(OSError):
            self.dir.lookup("does-not-exist")


class TestStaticDir(unittest.TestCase):
    """Tests for tvaf.fs.StaticDir."""

    def setUp(self):
        self.dir = fs.StaticDir()
        self.file1 = fs.File(size=10, mtime=0)
        self.file2 = fs.File(size=100, mtime=12345)
        self.dir.mkchild("foo", self.file1)
        self.dir.mkchild("bar", self.file2)

    def test_stat(self):
        self.assertEqual(self.dir.filetype, stat_lib.S_IFDIR)
        self.assertEqual(self.dir.stat().filetype, stat_lib.S_IFDIR)

    def test_readdir(self):
        dirents = list(self.dir.readdir())
        self.assertEqual(len(dirents), 2)
        self.assertEqual({d.name for d in dirents}, {"foo", "bar"})
        self.assertEqual({d.stat.size for d in dirents}, {10, 100})

    def test_lookup(self):
        obj = self.dir.lookup("foo")
        self.assertIs(obj, self.file1)
        self.assertIs(obj.parent, self.dir)
        self.assertEqual(obj.name, "foo")


class TestSymlink(unittest.TestCase):

    def setUp(self):
        self.root = fs.StaticDir()
        self.dir1 = fs.StaticDir()
        self.dir2 = fs.StaticDir()
        self.root.mkchild("dir1", self.dir1)
        self.root.mkchild("dir2", self.dir2)
        self.file = fs.File()
        self.dir2.mkchild("file", self.file)
        self.symlink = fs.Symlink()
        self.dir1.mkchild("symlink", self.symlink)

    def test_no_target(self):
        with self.assertRaises(OSError):
            self.symlink.readlink()

    def test_str_target(self):
        self.symlink.target = "other"
        self.assertEqual(self.symlink.readlink(), pathlib.PurePath("other"))

    def test_obj_target(self):
        # Ensure lookup
        fs.lookup(self.root, "dir1/symlink")
        fs.lookup(self.root, "dir2/file")
        self.symlink.target = self.file
        self.assertEqual(self.symlink.readlink(),
                pathlib.PurePath("../dir2/file"))
