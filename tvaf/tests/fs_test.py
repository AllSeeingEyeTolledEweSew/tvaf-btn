"""Tests for the tvaf.fs module."""
from __future__ import annotations

import io
import pathlib
import stat as stat_lib
import unittest
from typing import Dict

from tvaf import fs


class TestTraverse(unittest.TestCase):

    def setUp(self):
        self.root = fs.StaticDir()
        self.directory = fs.StaticDir()
        self.file = DummyFile(size=0)
        self.root.mkchild("directory", self.directory)
        self.directory.mkchild("file", self.file)
        self.symlink = fs.Symlink(target=self.file)
        self.directory.mkchild("symlink", self.symlink)

    def test_empty(self):
        self.assertIs(self.root.traverse(""), self.root)
        self.assertIsNone(self.root.parent)
        self.assertIsNone(self.root.name)

    def test_directory(self):
        self.assertIs(self.root.traverse("directory"), self.directory)
        self.assertIs(self.directory.parent, self.root)
        self.assertEqual(self.directory.name, "directory")

    def test_file(self):
        self.assertIs(self.root.traverse("directory/file"), self.file)
        self.assertIs(self.directory.parent, self.root)
        self.assertEqual(self.directory.name, "directory")
        self.assertIs(self.file.parent, self.directory)
        self.assertEqual(self.file.name, "file")

    def test_normalize(self):
        self.assertIs(self.root.traverse("directory//file/"), self.file)

    def test_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.root.traverse("does_not_exist")

    def test_not_dir(self):
        with self.assertRaises(NotADirectoryError):
            self.root.traverse("directory/file/subpath")

    def test_absolute(self):
        self.assertIs(self.root.traverse("/directory/file"), self.file)

    def test_absolute_from_subdir(self):
        self.assertIs(self.directory.traverse("/directory/file"), self.file)

    def test_symlink_follow_default(self):
        self.assertIs(self.directory.traverse("symlink"), self.file)

    def test_symlink_follow(self):
        self.assertIs(self.directory.traverse("symlink", follow_symlinks=True),
                      self.file)

    def test_symlink_no_follow(self):
        self.assertIs(self.directory.traverse("symlink", follow_symlinks=False),
                      self.symlink)

    def test_symlink_follow_self_loop(self):
        loop = fs.Symlink()
        loop.target = loop
        self.directory.mkchild("loop", loop)
        with self.assertRaises(OSError):
            self.directory.traverse("loop", follow_symlinks=True)

    def test_symlink_no_self_loop(self):
        loop = fs.Symlink()
        loop.target = loop
        self.directory.mkchild("loop", loop)
        self.assertIs(self.directory.traverse("loop", follow_symlinks=False),
                      loop)
        with self.assertRaises(OSError):
            self.directory.traverse("loop/a", follow_symlinks=False)

    def test_symlink_follow_two_loop(self):
        loop1 = fs.Symlink()
        loop2 = fs.Symlink()
        loop1.target = loop2
        loop2.target = loop1
        self.directory.mkchild("loop1", loop1)
        self.directory.mkchild("loop2", loop2)
        with self.assertRaises(OSError):
            self.directory.traverse("loop1", follow_symlinks=True)
        with self.assertRaises(OSError):
            self.directory.traverse("loop2", follow_symlinks=True)

    def test_symlink_no_follow_two_loop(self):
        loop1 = fs.Symlink()
        loop2 = fs.Symlink()
        loop1.target = loop2
        loop2.target = loop1
        self.directory.mkchild("loop1", loop1)
        self.directory.mkchild("loop2", loop2)
        self.assertIs(self.directory.traverse("loop1", follow_symlinks=False),
                      loop1)
        self.assertIs(self.directory.traverse("loop2", follow_symlinks=False),
                      loop2)
        with self.assertRaises(OSError):
            self.directory.traverse("loop1/a", follow_symlinks=False)
        with self.assertRaises(OSError):
            self.directory.traverse("loop2/a", follow_symlinks=False)

    def test_readlink_error_follow(self):
        self.symlink.target = None
        with self.assertRaises(OSError):
            self.directory.traverse("symlink", follow_symlinks=True)

    def test_readlink_error_no_follow(self):
        self.symlink.target = None
        self.assertIs(self.directory.traverse("symlink", follow_symlinks=False),
                      self.symlink)

    def test_dotdot(self):
        self.assertIs(self.root.traverse(".."), self.root)
        self.assertIs(self.directory.traverse(".."), self.root)

    def test_symlink_repeat_no_loop(self):
        dir_symlink = fs.Symlink(target=self.directory)
        self.root.mkchild("dir_symlink", dir_symlink)
        self.assertIs(self.root.traverse("dir_symlink/../dir_symlink/file"),
                      self.file)


class TestRealpath(unittest.TestCase):

    def setUp(self):
        self.root = fs.StaticDir()
        self.directory = fs.StaticDir()
        self.file = DummyFile(size=0)
        self.root.mkchild("directory", self.directory)
        self.directory.mkchild("file", self.file)
        self.symlink = fs.Symlink(target=self.file)
        self.directory.mkchild("symlink", self.symlink)

    def test_empty(self):
        self.assertEqual(self.root.realpath(""), fs.Path("/"))

    def test_matches_nothing(self):
        self.assertEqual(self.root.realpath("does/not/exist"),
                         fs.Path("/does/not/exist"))

    def test_symlink(self):
        self.assertEqual(self.root.realpath("directory/symlink/a"),
                         fs.Path("/directory/file/a"))

    def test_symlink_follow_self_loop(self):
        loop = fs.Symlink()
        loop.target = loop
        self.root.mkchild("loop", loop)
        self.assertEqual(self.root.realpath("loop/a"), fs.Path("/loop/a"))

    def test_symlink_follow_two_loop(self):
        loop1 = fs.Symlink()
        loop2 = fs.Symlink()
        loop1.target = loop2
        loop2.target = loop1
        self.root.mkchild("loop1", loop1)
        self.root.mkchild("loop2", loop2)
        self.assertEqual(self.root.realpath("loop1/a"), fs.Path("/loop1/a"))
        self.assertEqual(self.root.realpath("loop2/a"), fs.Path("/loop2/a"))

    def test_dotdot(self):
        self.assertEqual(self.root.realpath("directory/.."), fs.Path("/"))
        self.assertEqual(self.root.realpath("../../.."), fs.Path("/"))


class TestFile(unittest.TestCase):
    """Tests for tvaf.fs.File."""

    def test_file(self):
        node = DummyFile(size=0)
        self.assertTrue(node.is_file())
        self.assertFalse(node.is_link())
        self.assertFalse(node.is_dir())

    def test_stat(self):
        stat = DummyFile(size=0).stat()
        self.assertEqual(stat.filetype, stat_lib.S_IFREG)
        self.assertEqual(stat.size, 0)
        self.assertIs(stat.mtime, None)

    def test_os_stat(self):
        os_stat = DummyFile(size=123).stat().os()
        self.assertEqual(stat_lib.S_IFMT(os_stat.st_mode), stat_lib.S_IFREG)
        self.assertEqual(os_stat.st_size, 123)

        os_stat = DummyFile(size=123, mtime=12345).stat().os()
        self.assertEqual(os_stat.st_mtime, 12345)


class TestOpen(unittest.TestCase):

    def test_mode_rb(self):
        node = DummyFile(size=0)
        contents = b"test contents"

        def open_raw(mode):
            self.assertEqual(mode, "r")
            return io.BufferedReader(io.BytesIO(contents))

        node.open_raw = open_raw
        fp = node.open(mode="rb")
        self.assertEqual(fp.read(), contents)


class TestGetRoot(unittest.TestCase):

    def setUp(self):
        self.dir = fs.StaticDir()
        self.inner = fs.StaticDir()
        self.dir.mkchild("inner", self.inner)

    def test_root_from_root(self):
        self.assertIs(self.dir.get_root(), self.dir)

    def test_root_from_inner(self):
        self.assertIs(self.inner.get_root(), self.dir)


class DummyDir(fs.Dir):

    def __init__(self, dummy_file: DummyFile):
        super().__init__()
        self.dummy_file = dummy_file

    def get_node(self, name):
        if name == "foo":
            return self.dummy_file
        return None

    def readdir(self):
        return [fs.Dirent(name="foo", stat=self.dummy_file.stat())]


class DummyFile(fs.File):

    def open_raw(self, mode: str = "r") -> io.IOBase:
        return io.BytesIO(b"foo")


class TestDir(unittest.TestCase):
    """Tests for tvaf.fs.Dir."""

    def setUp(self):
        self.file = DummyFile(size=100)
        self.dir = DummyDir(self.file)

    def test_is_dir(self):
        self.assertTrue(self.dir.is_dir())
        self.assertFalse(self.dir.is_file())
        self.assertFalse(self.dir.is_link())

    def test_stat(self):
        self.assertEqual(self.dir.filetype, stat_lib.S_IFDIR)
        self.assertEqual(self.dir.stat().filetype, stat_lib.S_IFDIR)

    def test_os_stat(self):
        os_stat = self.dir.stat().os()
        self.assertEqual(stat_lib.S_IFMT(os_stat.st_mode), stat_lib.S_IFDIR)

        self.dir.mtime = 12345
        os_stat = self.dir.stat().os()
        self.assertEqual(os_stat.st_mtime, 12345)

    def test_lookup(self):
        obj = self.dir.lookup("foo")
        self.assertIs(obj, self.file)
        self.assertIs(obj.parent, self.dir)
        self.assertEqual(obj.name, "foo")

    def test_noent(self):
        with self.assertRaises(OSError):
            self.dir.lookup("does-not-exist")


class DummyDictDir(fs.DictDir):

    def __init__(self, file1: fs.File, file2: fs.File):
        super().__init__()
        self.file1 = file1
        self.file2 = file2

    def get_dict(self) -> Dict[str, fs.Node]:
        return dict(foo=self.file1, bar=self.file2)


class TestDictDir(unittest.TestCase):
    """Tests for tvaf.fs.Dir."""

    def setUp(self):
        self.file1 = DummyFile(size=100, mtime=0)
        self.file2 = DummyFile(size=200, mtime=12345)
        self.dir = DummyDictDir(self.file1, self.file2)

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
        self.file1 = DummyFile(size=10, mtime=0)
        self.file2 = DummyFile(size=100, mtime=12345)
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
        self.file = DummyFile()
        self.dir2.mkchild("file", self.file)
        self.symlink = fs.Symlink()
        self.dir1.mkchild("symlink", self.symlink)

    def test_is_link(self):
        self.symlink.target = "."
        self.assertTrue(self.symlink.is_link())
        self.assertFalse(self.symlink.is_file())
        self.assertFalse(self.symlink.is_dir())

    def test_no_target(self):
        with self.assertRaises(OSError):
            self.symlink.readlink()

    def test_str_target(self):
        self.symlink.target = "other"
        self.assertEqual(self.symlink.readlink(), pathlib.PurePath("other"))

    def test_obj_target(self):
        # Ensure lookup
        self.root.traverse("dir1/symlink", follow_symlinks=False)
        self.root.traverse("dir2/file")
        self.symlink.target = self.file
        self.assertEqual(self.symlink.readlink(),
                         pathlib.PurePath("../dir2/file"))
