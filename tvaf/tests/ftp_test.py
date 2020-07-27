from tvaf import ftp
import io
from tvaf import config as config_lib
import logging
import ftplib
import libtorrent as lt
from tvaf import auth
from . import tdummy
from tvaf import types
from tvaf import library
import unittest

class DummyException(Exception): pass

SINGLE = tdummy.Torrent.single_file(name=b"test.txt", length=16384 * 9 + 1000)
MULTI = tdummy.Torrent(files=[
    dict(length=10000, path=b"multi/file.tar.gz"),
    dict(length=100, path=b"multi/info.nfo"),
])

class BaseFTPTest(unittest.TestCase):

    do_login = True

    def setUp(self):
        self.torrents = {t.infohash: t for t in (SINGLE,MULTI)}

        def opener(tslice:types.TorrentSlice,
                get_torrent:library.GetTorrent):
            data = self.torrents[tslice.info_hash].data[tslice.start:tslice.stop]
            raw = io.BytesIO(data)
            # bug in pyftpdlib: tries to access fileobj.name for debug logging
            raw.name = "<bytes>"
            # opener can normally return a RawIOBase, but we'll mimic
            # IOService returning BufferedTorrentIO here.
            return io.BufferedReader(raw)

        def get_access(info_hash):
            t = self.torrents[info_hash]
            return library.Access(seeders=100, get_torrent=lambda:
                    lt.bencode(t.dict))

        self.hints = {
            (SINGLE.infohash, 0): library.Hints(mime_type="text/plain",
                mtime=12345),
        }

        self.libs = library.LibraryService(opener=opener)
        self.libs.get_layout_info_dict_funcs["test"] = lambda info_hash: self.torrents[info_hash].info
        self.libs.get_access_funcs["test"] = get_access
        self.libs.get_hints_funcs["test"] = lambda ih, idx: self.hints[(ih, idx)]

        self.auth_service = auth.AuthService()
        # We would normally do an empty config, but we set ftp_port=0 to avoid
        # collisions with anything else on the system
        self.config = config_lib.Config(ftp_port=0)
        self.ftpd = ftp.FTPD(root=self.libs.root,
                auth_service=self.auth_service, config=self.config)
        self.address = self.ftpd.server.socket.getsockname()
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
        self.ftpd.abort()
        self.ftpd.wait()


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
        self.ftp.cwd(f"/v1/{SINGLE.infohash}/test/f")
        lines = []
        self.ftp.retrlines("LIST", callback=lines.append)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith(" test.txt -> ../i/0"))

    def test_root(self):
        self.assertEqual(self.ftp.pwd(), "/")

        self.assert_mlsd("", ("perm", "type"), [("browse", dict(perm="el", type="dir")),
            ("v1", dict(perm="el", type="dir"))])

    def test_torrent_dir(self):
        self.ftp.cwd(f"/v1/{SINGLE.infohash}/test/f")
        self.assert_mlsd("", ("perm", "size", "type"), [("test.txt", dict(perm="r",
            type="file", size=str(SINGLE.files[0].length)))])

        self.ftp.cwd(f"/v1/{SINGLE.infohash}/test/i")
        self.assert_mlsd("", ("perm", "size", "type"), [("0", dict(perm="r",
            type="file", size=str(SINGLE.files[0].length)))])

    def test_CWD_invalid(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 Not a directory."):
            self.ftp.cwd(f"/v1/{SINGLE.infohash}/test/i/0")

    def test_SIZE(self):
        # pyftpdlib does not allow SIZE in ascii mode to avoid newline
        # translation issues
        self.ftp.voidcmd("TYPE I")
        size = self.ftp.size(f"/v1/{SINGLE.infohash}/test/i/0")
        self.assertEqual(size, SINGLE.files[0].length)

    def test_MDTM(self):
        resp = self.ftp.sendcmd(f"MDTM /v1/{SINGLE.infohash}/test/i/0")
        self.assertEqual(resp, "213 19700101032545")

        # Check files which default to current mtime
        resp = self.ftp.sendcmd(f"MDTM /v1/{MULTI.infohash}/test/i/0")
        self.assertEqual(resp.split()[0], "213")


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
            self.ftp.storbinary(f"STOR /v1/{SINGLE.infohash}/test/i/0",
                    io.BytesIO(b"data"))

    def test_APPE(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.storbinary(f"APPE /v1/{SINGLE.infohash}/test/i/0",
                    io.BytesIO(b"data"))

    def test_DELE(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.delete(f"/v1/{SINGLE.infohash}/test/i/0")

    def test_rename(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.rename(f"/v1/{SINGLE.infohash}/test/i/0",
                    f"/v1/{SINGLE.infohash}/test/i/123")

    def test_MKD(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.mkd("new")

    def test_RMD(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.rmd("v1")

    def test_MFMT(self):
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.voidcmd(f"MFMT 19700101032545 /v1/{SINGLE.infohash}/test/i/0")


class TestRETR(BaseFTPTest):

    def test_RETR(self):
        buf = io.BytesIO()
        self.ftp.retrbinary(f"RETR /v1/{SINGLE.infohash}/test/i/0", buf.write)
        self.assertEqual(buf.getvalue(), SINGLE.files[0].data)

    def test_RETR_dir(self):
        buf = io.BytesIO()
        with self.assertRaisesRegex(ftplib.error_perm, "550 .*"):
            self.ftp.retrbinary(f"RETR /v1/{SINGLE.infohash}/test/i", buf.write)

    def test_RETR_with_REST(self):
        buf = io.BytesIO()
        self.ftp.retrbinary(f"RETR /v1/{SINGLE.infohash}/test/i/0", buf.write,
                rest=1000)
        self.assertEqual(buf.getvalue(), SINGLE.files[0].data[1000:])


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
        self.address = self.ftpd.server.socket.getsockname()
        self.connect()
        self.assertEqual(self.ftp.pwd(), "/")

    def test_disable_enable(self):
        self.config["ftp_enabled"] = False
        self.ftpd.set_config(self.config)

        with self.assertRaises(EOFError):
            self.ftp.pwd()

        self.assertIsNone(self.ftpd.server)

        self.config["ftp_enabled"] = True
        self.ftpd.set_config(self.config)

        self.address = self.ftpd.server.socket.getsockname()
        self.connect()
        self.assertEqual(self.ftp.pwd(), "/")

    def test_no_changes(self):
        self.ftpd.set_config(self.config)
        self.assertEqual(self.ftp.pwd(), "/")

    def test_bad_change(self):
        self.config["ftp_port"] = -1
        with self.assertRaises(config_lib.InvalidConfigError):
            self.ftpd.set_config(self.config)

        # Try reconfigure with good port
        self.config["ftp_port"] = 0
        self.ftpd.set_config(self.config)
        self.address = self.ftpd.server.socket.getsockname()
        self.connect()
        self.assertEqual(self.ftp.pwd(), "/")

    def test_default_config(self):
        # Ensure we set some default values
        self.assertEqual(self.config["ftp_enabled"], True)
        self.assertEqual(self.config["ftp_bind_address"], "localhost")
