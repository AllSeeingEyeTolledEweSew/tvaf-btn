import unittest

from tvaf import protocol


class IterFilesTest(unittest.TestCase):

    def test_single_file(self):
        info = protocol.Info({b"name": b"file name \xff.txt", b"length": 10000})
        files = list(info.iter_files())
        self.assertEqual(len(files), 1)
        file_ = files[0]
        self.assertEqual(file_.index, 0)
        self.assertEqual(file_.length, 10000)
        self.assertEqual(file_.start, 0)
        self.assertEqual(file_.stop, 10000)

        self.assertEqual(file_.path_bytes, [])
        self.assertEqual(file_.path, [])
        self.assertEqual(file_.full_path_bytes, [b"file name \xff.txt"])
        self.assertEqual(file_.full_path, ["file name \udcff.txt"])

        self.assertEqual(file_.attr_bytes, b"")
        self.assertEqual(file_.attr, "")
        self.assertFalse(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertFalse(file_.is_executable)

    def test_single_file_attr(self):
        info = protocol.Info({
            b"attr": b"hx\xff",
            b"name": b"file name \xff.txt",
            b"length": 10000
        })
        files = list(info.iter_files())
        self.assertEqual(len(files), 1)
        file_ = files[0]
        self.assertEqual(file_.index, 0)
        self.assertEqual(file_.length, 10000)
        self.assertEqual(file_.start, 0)
        self.assertEqual(file_.stop, 10000)

        self.assertEqual(file_.path_bytes, [])
        self.assertEqual(file_.path, [])
        self.assertEqual(file_.full_path_bytes, [b"file name \xff.txt"])
        self.assertEqual(file_.full_path, ["file name \udcff.txt"])

        self.assertEqual(file_.attr_bytes, b"hx\xff")
        self.assertEqual(file_.attr, "hx\udcff")
        self.assertFalse(file_.is_symlink)
        self.assertTrue(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertTrue(file_.is_executable)

    def test_multi_file(self):
        info = protocol.Info({
            b"name":
                b"parent",
            b"files": [
                {
                    b"length": 20000,
                    b"path": [b"directory", b"file.zip"],
                },
                {
                    b"length": 1000,
                    b"path": [b"directory", b"info.nfo"],
                },
            ]
        })
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        file_ = files[0]
        self.assertEqual(file_.index, 0)
        self.assertEqual(file_.length, 20000)
        self.assertEqual(file_.start, 0)
        self.assertEqual(file_.stop, 20000)

        self.assertEqual(file_.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(file_.path, ["directory", "file.zip"])
        self.assertEqual(file_.full_path_bytes,
                         [b"parent", b"directory", b"file.zip"])
        self.assertEqual(file_.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(file_.attr_bytes, b"")
        self.assertEqual(file_.attr, "")
        self.assertFalse(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertFalse(file_.is_executable)

        file_ = files[1]
        self.assertEqual(file_.index, 1)
        self.assertEqual(file_.length, 1000)
        self.assertEqual(file_.start, 20000)
        self.assertEqual(file_.stop, 21000)

        self.assertEqual(file_.path_bytes, [b"directory", b"info.nfo"])
        self.assertEqual(file_.path, ["directory", "info.nfo"])
        self.assertEqual(file_.full_path_bytes,
                         [b"parent", b"directory", b"info.nfo"])
        self.assertEqual(file_.full_path, ["parent", "directory", "info.nfo"])

        self.assertEqual(file_.attr_bytes, b"")
        self.assertEqual(file_.attr, "")
        self.assertFalse(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertFalse(file_.is_executable)

    def test_pad(self):
        info = protocol.Info({
            b"name":
                b"parent",
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
            ]
        })
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        file_ = files[0]
        self.assertEqual(file_.index, 0)
        self.assertEqual(file_.length, 16000)
        self.assertEqual(file_.start, 0)
        self.assertEqual(file_.stop, 16000)

        self.assertEqual(file_.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(file_.path, ["directory", "file.zip"])
        self.assertEqual(file_.full_path_bytes,
                         [b"parent", b"directory", b"file.zip"])
        self.assertEqual(file_.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(file_.attr_bytes, b"")
        self.assertEqual(file_.attr, "")
        self.assertFalse(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertFalse(file_.is_executable)

        file_ = files[1]
        self.assertEqual(file_.index, 1)
        self.assertEqual(file_.length, 384)
        self.assertEqual(file_.start, 16000)
        self.assertEqual(file_.stop, 16384)

        self.assertEqual(file_.path_bytes, [b".pad", b"384"])
        self.assertEqual(file_.path, [".pad", "384"])
        self.assertEqual(file_.full_path_bytes, [b"parent", b".pad", b"384"])
        self.assertEqual(file_.full_path, ["parent", ".pad", "384"])

        self.assertEqual(file_.attr_bytes, b"p")
        self.assertEqual(file_.attr, "p")
        self.assertFalse(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertTrue(file_.is_pad)
        self.assertFalse(file_.is_executable)

    def test_multi_file_attr(self):
        info = protocol.Info({
            b"name":
                b"parent",
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
            ]
        })
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        file_ = files[0]
        self.assertEqual(file_.index, 0)
        self.assertEqual(file_.length, 20000)
        self.assertEqual(file_.start, 0)
        self.assertEqual(file_.stop, 20000)

        self.assertEqual(file_.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(file_.path, ["directory", "file.zip"])
        self.assertEqual(file_.full_path_bytes,
                         [b"parent", b"directory", b"file.zip"])
        self.assertEqual(file_.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(file_.attr_bytes, b"")
        self.assertEqual(file_.attr, "")
        self.assertFalse(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertFalse(file_.is_executable)

        file_ = files[1]
        self.assertEqual(file_.index, 1)
        self.assertEqual(file_.length, 1000)
        self.assertEqual(file_.start, 20000)
        self.assertEqual(file_.stop, 21000)

        self.assertEqual(file_.path_bytes, [b"directory", b".sig"])
        self.assertEqual(file_.path, ["directory", ".sig"])
        self.assertEqual(file_.full_path_bytes,
                         [b"parent", b"directory", b".sig"])
        self.assertEqual(file_.full_path, ["parent", "directory", ".sig"])

        self.assertEqual(file_.attr_bytes, b"hx?")
        self.assertEqual(file_.attr, "hx?")
        self.assertFalse(file_.is_symlink)
        self.assertTrue(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertTrue(file_.is_executable)

    def test_symlink(self):
        info = protocol.Info({
            b"name":
                b"parent",
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
            ]
        })
        files = list(info.iter_files())
        self.assertEqual(len(files), 2)
        file_ = files[0]
        self.assertEqual(file_.index, 0)
        self.assertEqual(file_.length, 20000)
        self.assertEqual(file_.start, 0)
        self.assertEqual(file_.stop, 20000)

        self.assertEqual(file_.path_bytes, [b"directory", b"file.zip"])
        self.assertEqual(file_.path, ["directory", "file.zip"])
        self.assertEqual(file_.full_path_bytes,
                         [b"parent", b"directory", b"file.zip"])
        self.assertEqual(file_.full_path, ["parent", "directory", "file.zip"])

        self.assertEqual(file_.attr_bytes, b"")
        self.assertEqual(file_.attr, "")
        self.assertFalse(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertFalse(file_.is_executable)

        file_ = files[1]
        self.assertEqual(file_.index, 1)
        self.assertEqual(file_.length, 0)

        self.assertEqual(file_.path_bytes, [b"directory", b"FILE.ZIP"])
        self.assertEqual(file_.path, ["directory", "FILE.ZIP"])
        self.assertEqual(file_.full_path_bytes,
                         [b"parent", b"directory", b"FILE.ZIP"])
        self.assertEqual(file_.full_path, ["parent", "directory", "FILE.ZIP"])

        self.assertEqual(file_.target_bytes, [b"directory", b"file.zip"])
        self.assertEqual(file_.target, ["directory", "file.zip"])
        self.assertEqual(file_.full_target_bytes,
                         [b"parent", b"directory", b"file.zip"])
        self.assertEqual(file_.full_target, ["parent", "directory", "file.zip"])

        self.assertEqual(file_.attr_bytes, b"l")
        self.assertEqual(file_.attr, "l")
        self.assertTrue(file_.is_symlink)
        self.assertFalse(file_.is_hidden)
        self.assertFalse(file_.is_pad)
        self.assertFalse(file_.is_executable)
