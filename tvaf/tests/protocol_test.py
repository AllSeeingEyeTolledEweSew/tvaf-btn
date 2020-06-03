import unittest
import dataclasses
from tvaf import protocol

class IterFilesTest(unittest.TestCase):

    def test_single_file(self):
        info = protocol.Info({
            b"name": b"file name \xff.txt",
            b"length": 10000})
        files = list(info.iter_files())
        self.assertEqual(len(files), 1)
        f = files[0]
        self.assertEqual(f.index, 0)
        self.assertEqual(f.length, 10000)
        self.assertEqual(f.start, 0)
        self.assertEqual(f.stop, 10000)

        self.assertEqual(f.path_bytes, [])
        self.assertEqual(f.path, [])
        self.assertEqual(f.full_path_bytes, [b"file name \xff.txt"])
        self.assertEqual(f.full_path, ["file name \udcff.txt"])

        self.assertEqual(f.attr_bytes, b"")
        self.assertEqual(f.attr, "")
        self.assertFalse(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertFalse(f.is_executable)

    def test_single_file_attr(self):
        info = protocol.Info({
            b"attr": b"hx\xff",
            b"name": b"file name \xff.txt",
            b"length": 10000})
        files = list(info.iter_files())
        self.assertEqual(len(files), 1)
        f = files[0]
        self.assertEqual(f.index, 0)
        self.assertEqual(f.length, 10000)
        self.assertEqual(f.start, 0)
        self.assertEqual(f.stop, 10000)

        self.assertEqual(f.path_bytes, [])
        self.assertEqual(f.path, [])
        self.assertEqual(f.full_path_bytes, [b"file name \xff.txt"])
        self.assertEqual(f.full_path, ["file name \udcff.txt"])

        self.assertEqual(f.attr_bytes, b"hx\xff")
        self.assertEqual(f.attr, "hx\udcff")
        self.assertFalse(f.is_symlink)
        self.assertTrue(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertTrue(f.is_executable)

    def test_multi_file(self):
        info = protocol.Info({
            b"name": b"parent",
            b"files": [
                {
                    b"length": 20000,
                    b"path": [b"directory", b"file.zip"],
                },
                {
                    b"length": 1000,
                    b"path": [b"directory", b"info.nfo"],
                },
            ]})
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        f = files[0]
        self.assertEqual(f.index, 0)
        self.assertEqual(f.length, 20000)
        self.assertEqual(f.start, 0)
        self.assertEqual(f.stop, 20000)

        self.assertEqual(f.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(f.path, ["directory", "file.zip"])
        self.assertEqual(f.full_path_bytes, [b"parent", b"directory",
        b"file.zip"])
        self.assertEqual(f.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(f.attr_bytes, b"")
        self.assertEqual(f.attr, "")
        self.assertFalse(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertFalse(f.is_executable)

        f = files[1]
        self.assertEqual(f.index, 1)
        self.assertEqual(f.length, 1000)
        self.assertEqual(f.start, 20000)
        self.assertEqual(f.stop, 21000)

        self.assertEqual(f.path_bytes, [b"directory", b"info.nfo"])
        self.assertEqual(f.path, ["directory", "info.nfo"])
        self.assertEqual(f.full_path_bytes, [b"parent", b"directory",
        b"info.nfo"])
        self.assertEqual(f.full_path, ["parent", "directory", "info.nfo"])

        self.assertEqual(f.attr_bytes, b"")
        self.assertEqual(f.attr, "")
        self.assertFalse(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertFalse(f.is_executable)

    def test_pad(self):
        info = protocol.Info({
            b"name": b"parent",
            b"files": [
                {
                    b"length": 16000,
                    b"path": [b"directory", b"file.zip"],
                },
                {
                    b"attr": b"p",
                    b"length": 384,
                    b"path": [b".pad", b"384"],
                },
            ]})
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        f = files[0]
        self.assertEqual(f.index, 0)
        self.assertEqual(f.length, 16000)
        self.assertEqual(f.start, 0)
        self.assertEqual(f.stop, 16000)

        self.assertEqual(f.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(f.path, ["directory", "file.zip"])
        self.assertEqual(f.full_path_bytes, [b"parent", b"directory",
        b"file.zip"])
        self.assertEqual(f.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(f.attr_bytes, b"")
        self.assertEqual(f.attr, "")
        self.assertFalse(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertFalse(f.is_executable)

        f = files[1]
        self.assertEqual(f.index, 1)
        self.assertEqual(f.length, 384)
        self.assertEqual(f.start, 16000)
        self.assertEqual(f.stop, 16384)

        self.assertEqual(f.path_bytes, [b".pad", b"384"])
        self.assertEqual(f.path, [".pad", "384"])
        self.assertEqual(f.full_path_bytes, [b"parent", b".pad",
        b"384"])
        self.assertEqual(f.full_path, ["parent", ".pad", "384"])

        self.assertEqual(f.attr_bytes, b"p")
        self.assertEqual(f.attr, "p")
        self.assertFalse(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertTrue(f.is_pad)
        self.assertFalse(f.is_executable)

    def test_multi_file_attr(self):
        info = protocol.Info({
            b"name": b"parent",
            b"files": [
                {
                    b"length": 20000,
                    b"path": [b"directory", b"file.zip"],
                },
                {
                    b"attr": b"hx?",
                    b"length": 1000,
                    b"path": [b"directory", b".sig"],
                },
            ]})
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        f = files[0]
        self.assertEqual(f.index, 0)
        self.assertEqual(f.length, 20000)
        self.assertEqual(f.start, 0)
        self.assertEqual(f.stop, 20000)

        self.assertEqual(f.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(f.path, ["directory", "file.zip"])
        self.assertEqual(f.full_path_bytes, [b"parent", b"directory",
        b"file.zip"])
        self.assertEqual(f.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(f.attr_bytes, b"")
        self.assertEqual(f.attr, "")
        self.assertFalse(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertFalse(f.is_executable)

        f = files[1]
        self.assertEqual(f.index, 1)
        self.assertEqual(f.length, 1000)
        self.assertEqual(f.start, 20000)
        self.assertEqual(f.stop, 21000)

        self.assertEqual(f.path_bytes, [b"directory", b".sig"])
        self.assertEqual(f.path, ["directory", ".sig"])
        self.assertEqual(f.full_path_bytes, [b"parent", b"directory",
        b".sig"])
        self.assertEqual(f.full_path, ["parent", "directory", ".sig"])

        self.assertEqual(f.attr_bytes, b"hx?")
        self.assertEqual(f.attr, "hx?")
        self.assertFalse(f.is_symlink)
        self.assertTrue(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertTrue(f.is_executable)

    def test_symlink(self):
        info = protocol.Info({
            b"name": b"parent",
            b"files": [
                {
                    b"length": 20000,
                    b"path": [b"directory", b"file.zip"],
                },
                {
                    b"attr": b"l",
                    b"path": [b"directory", b"FILE.ZIP"],
                    b"symlink path": [b"directory", b"file.zip"],
                },
            ]})
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        f = files[0]
        self.assertEqual(f.index, 0)
        self.assertEqual(f.length, 20000)
        self.assertEqual(f.start, 0)
        self.assertEqual(f.stop, 20000)

        self.assertEqual(f.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(f.path, ["directory", "file.zip"])
        self.assertEqual(f.full_path_bytes, [b"parent", b"directory",
        b"file.zip"])
        self.assertEqual(f.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(f.attr_bytes, b"")
        self.assertEqual(f.attr, "")
        self.assertFalse(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertFalse(f.is_executable)

        f = files[1]
        self.assertEqual(f.index, 1)
        self.assertEqual(f.length, 0)

        self.assertEqual(f.path_bytes, [b"directory", b"FILE.ZIP"])
        self.assertEqual(f.path, ["directory", "FILE.ZIP"])
        self.assertEqual(f.full_path_bytes, [b"parent", b"directory",
        b"FILE.ZIP"])
        self.assertEqual(f.full_path, ["parent", "directory", "FILE.ZIP"])

        self.assertEqual(f.target_bytes, [b"directory", b"file.zip"])
        self.assertEqual(f.target, ["directory", "file.zip"])
        self.assertEqual(f.full_target_bytes, [b"parent", b"directory",
        b"file.zip"])
        self.assertEqual(f.full_target, ["parent", "directory", "file.zip"])

        self.assertEqual(f.attr_bytes, b"l")
        self.assertEqual(f.attr, "l")
        self.assertTrue(f.is_symlink)
        self.assertFalse(f.is_hidden)
        self.assertFalse(f.is_pad)
        self.assertFalse(f.is_executable)
