import ftplib
import io
import unittest
from typing import Any

from tvaf import auth
from tvaf import ftp
from tvaf import library

from . import lib
from . import library_test_utils as ltu


class DummyException(Exception):

    pass


def _raise_dummy() -> None:
    raise DummyException()


class BaseFTPTest(unittest.TestCase):

    do_login = True

    def setUp(self):
        self.torrents = {t.info_hash: t for t in (ltu.SINGLE, ltu.MULTI)}

        def opener(info_hash: str, start: int, stop: int, _: Any):
            data = self.torrents[info_hash].data[start:stop]
            raw = io.BytesIO(data)
            # bug in pyftpdlib: tries to access fileobj.name for debug logging
            raw.name = "<bytes>"
            return raw

        self.libraries = library.Libraries()
        ltu.add_test_libraries(self.libraries)
        self.libs = library.LibraryService(opener=opener,
                                           libraries=self.libraries)

        self.auth_service = auth.AuthService()
        self.config = lib.create_isolated_config()
        self.ftpd = ftp.FTPD(root=self.libs.root,
                             auth_service=self.auth_service,
                             config=self.config)
        self.ftpd.start()
        self.address = self.ftpd.socket.getsockname()
        self.connect()

    def connect(self):
        # Can't seem to specify a port with constructor args
        self.ftp = ftplib.FTP()
        self.ftp.set_debuglevel(2)
        self.ftp.connect(host=self.address[0], port=self.address[1], timeout=5)
        if self.do_login:
            self.ftp.login(user=self.auth_service.USER,
                           passwd=self.auth_service.PASSWORD)

    def tearDown(self):
        self.ftp.quit()
        self.ftpd.terminate()
        self.ftpd.join()


class TestPathStructure(BaseFTPTest):

    def assert_mlsd(self, path, facts, expected):
        items = sorted(self.ftp.mlsd(path=path, facts=facts))
        self.assertEqual(items, expected)

    def test_LIST(self):
        lines = []
        self.ftp.retrlines("LIST", callback=lines.append)
        # The last token should be the name
        lines = sorted(line.split()[-1] for line in lines)
        self.assertEqual(lines, ["browse", "v1"])

    def test_LIST_with_symlinks(self):
        self.ftp.cwd(f"/v1/{ltu.SINGLE.info_hash}/test/f")
        lines = []
        self.ftp.retrlines("LIST", callback=lines.append)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith(" test.txt -> ../i/0"))

    def test_root(self):
        self.assertEqual(self.ftp.pwd(), "/")

        self.assert_mlsd("", ("perm", "type"),
                         [("browse", dict(perm="el", type="dir")),
                          ("v1", dict(perm="el", type="dir"))])

    def test_torrent_dir(self):
        self.ftp.cwd(f"/v1/{ltu.SINGLE.info_hash}/test/f")
        self.assert_mlsd("", ("perm", "size", "type"), [
            ("test.txt",
             dict(perm="r", type="file", size=str(ltu.SINGLE.files[0].length)))
        ])

        self.ftp.cwd(f"/v1/{ltu.SINGLE.info_hash}/test/i")
        self.assert_mlsd("", ("perm", "size", "type"), [
            ("0",
             dict(perm="r", type="file", size=str(ltu.SINGLE.files[0].length)))
        ])

    def test_CWD_invalid(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 Not a directory."):
            self.ftp.cwd(f"/v1/{ltu.SINGLE.info_hash}/test/i/0")

    def test_SIZE(self):
        # pyftpdlib does not allow SIZE in ascii mode to avoid newline
        # translation issues
        self.ftp.voidcmd("TYPE I")
        size = self.ftp.size(f"/v1/{ltu.SINGLE.info_hash}/test/i/0")
        self.assertEqual(size, ltu.SINGLE.files[0].length)


class TestReadOnly(BaseFTPTest):

    def test_STOU(self):
        # For some reason, pyftpdlib bypasses permissions to call mkstemp. tvaf
        # fails with a permissions error, but pyftpdlib treats it as a 450
        # "temporary error".
        with self.assertRaises(ftplib.all_errors):
            self.ftp.storbinary("STOU", io.BytesIO(b"data"))

    def test_STOR(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.storbinary("STOR file.txt", io.BytesIO(b"data"))

    def test_STOR_overwrite(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.storbinary(f"STOR /v1/{ltu.SINGLE.info_hash}/test/i/0",
                                io.BytesIO(b"data"))

    def test_APPE(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.storbinary(f"APPE /v1/{ltu.SINGLE.info_hash}/test/i/0",
                                io.BytesIO(b"data"))

    def test_DELE(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.delete(f"/v1/{ltu.SINGLE.info_hash}/test/i/0")

    def test_rename(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.rename(f"/v1/{ltu.SINGLE.info_hash}/test/i/0",
                            f"/v1/{ltu.SINGLE.info_hash}/test/i/123")

    def test_MKD(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.mkd("new")

    def test_RMD(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.rmd("v1")

    def test_MFMT(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.voidcmd(
                f"MFMT 19700101032545 /v1/{ltu.SINGLE.info_hash}/test/i/0")


class TestRETR(BaseFTPTest):

    def test_RETR(self):
        buf = io.BytesIO()
        self.ftp.retrbinary(f"RETR /v1/{ltu.SINGLE.info_hash}/test/i/0",
                            buf.write)
        self.assertEqual(buf.getvalue(), ltu.SINGLE.files[0].data)

    def test_RETR_dir(self):
        buf = io.BytesIO()
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.retrbinary(f"RETR /v1/{ltu.SINGLE.info_hash}/test/i",
                                buf.write)

    def test_RETR_with_REST(self):
        buf = io.BytesIO()
        self.ftp.retrbinary(f"RETR /v1/{ltu.SINGLE.info_hash}/test/i/0",
                            buf.write,
                            rest=1000)
        self.assertEqual(buf.getvalue(), ltu.SINGLE.files[0].data[1000:])


class TestAuth(BaseFTPTest):

    do_login = False

    def test_bad_auth(self):
        with self.assertRaisesRegex(ftplib.error_perm, "530 .*"):
            self.ftp.login(user="invalid", passwd="invalid")


class TestConfig(BaseFTPTest):

    def test_change_binding(self):
        self.config["ftp_bind_address"] = "127.0.0.1"
        self.ftpd.set_config(self.config)
        with self.assertRaises(EOFError):
            self.ftp.pwd()
        self.address = self.ftpd.socket.getsockname()
        self.connect()
        self.assertEqual(self.ftp.pwd(), "/")

    def test_disable_enable(self):
        self.config["ftp_enabled"] = False
        self.ftpd.set_config(self.config)

        with self.assertRaises(EOFError):
            self.ftp.pwd()

        self.assertIsNone(self.ftpd.socket)

        self.config["ftp_enabled"] = True
        self.ftpd.set_config(self.config)

        self.address = self.ftpd.socket.getsockname()
        self.connect()
        self.assertEqual(self.ftp.pwd(), "/")

    def test_no_changes(self):
        self.ftpd.set_config(self.config)
        self.assertEqual(self.ftp.pwd(), "/")

    def test_bad_change(self):
        self.config["ftp_port"] = -1
        with self.assertRaises(OverflowError):
            self.ftpd.set_config(self.config)

        # Try reconfigure with good port
        self.config["ftp_port"] = 0
        self.ftpd.set_config(self.config)
        self.address = self.ftpd.socket.getsockname()
        self.connect()
        self.assertEqual(self.ftp.pwd(), "/")

    def test_default_config(self):
        # Ensure we set some default values
        self.assertEqual(self.config["ftp_enabled"], True)
        self.assertEqual(self.config["ftp_bind_address"], "localhost")

    def test_stage_revert(self):
        self.connect()

        self.config["ftp_enabled"] = False
        with self.assertRaises(DummyException):
            with self.ftpd.stage_config(self.config):
                _raise_dummy()

        # Should still be connected
        self.assertEqual(self.ftp.pwd(), "/")

        self.config["ftp_bind_address"] = "127.0.0.1"
        with self.assertRaises(DummyException):
            with self.ftpd.stage_config(self.config):
                _raise_dummy()

        # Should still be connected
        self.assertEqual(self.ftp.pwd(), "/")
