import pathlib
import os
import contextlib
import tempfile
import json
import unittest
import ipaddress
from tvaf import config as config_lib

import libtorrent as lt

NONEXISTENT_PATH = pathlib.Path().joinpath("does", "not", "exist")

class BaseTest(unittest.TestCase):

    def check_sanity(self, config):
        self.assertIsNotNone(config.config_dir)
        self.assertIsNotNone(config.download_dir)

        self.assertGreaterEqual(config.sftp_bind_address.version, 4)
        self.assertGreaterEqual(config.http_bind_address.version, 4)

        for net in config.sftp_ip_whitelist:
            self.assertGreaterEqual(net.version, 4)
            self.assertGreaterEqual(net.prefixlen, 0)
        for net in config.http_ip_whitelist:
            self.assertGreaterEqual(net.version, 4)
            self.assertGreaterEqual(net.prefixlen, 0)

        self.assertGreater(
            len(config.get_libtorrent_settings_base()), 0)
        self.assertGreater(
            len(config.get_effective_libtorrent_settings()), 0)

    @contextlib.contextmanager
    def create(self, contents=None):
        tempdir = tempfile.TemporaryDirectory()
        config_dir = pathlib.Path(tempdir.name)
        try:
            if contents is not None:
                path = config_dir.joinpath(config_lib.FILENAME)
                with path.open(mode="w") as fp:
                    if isinstance(contents, dict):
                        json.dump(contents, fp)
                    else:
                        fp.write(contents)
            yield config_dir
        finally:
            tempdir.cleanup()

    def assert_golden(self, data, suffix=".golden.txt"):
        path = pathlib.Path(__file__).parent.joinpath("golden", self.id()).with_suffix(suffix)
        if os.getenv("GOLDEN_MELD"):
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_text(data)
        else:
            self.assertMultiLineEqual(data, path.read_text())

    def assert_golden_json(self, data, suffix=".golden.json"):
        self.assert_golden(json.dumps(data, indent=4, sort_keys=True),
                suffix=suffix)

    def assert_golden_config(self, config, suffix=".golden.json"):
        data = config.to_json()
        # Hack to stabilize the golden data
        download_dir = pathlib.PurePath(data["download_dir"])
        download_dir = download_dir.relative_to(config.config_dir.resolve(strict=False))
        data["download_dir"] = str(download_dir)
        self.assert_golden_json(data, suffix=suffix)


class TestDefaults(BaseTest):

    def test_defaults_from_empty(self):
        config = config_lib.Config.load(NONEXISTENT_PATH)
        self.check_sanity(config)
        self.assert_golden_config(config)

    def test_defaults_merge(self):
        with self.create(dict(http_port=1234)) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.check_sanity(config)
            self.assertEqual(config.http_port, 1234)
            self.assertNotEqual(config.sftp_port, 0)


class TestLoad(BaseTest):

    def test_load_malformed(self):
        with self.create("malformed json data") as config_dir:
            with self.assertRaises(json.JSONDecodeError):
                config = config_lib.Config.load(config_dir)

    def test_load_after_save(self):
        with self.create() as config_dir:
            config_orig = config_lib.Config.load(config_dir)
            config_orig.save()
            config_reloaded = config_lib.Config.load(config_dir)
            self.assertEqual(config_orig, config_reloaded)

    def test_parse_download_dir(self):
        with self.create(dict(download_dir="my-downloads")) as config_dir:
            config = config_lib.Config.load(config_dir)
            path = pathlib.Path().joinpath("my-downloads").resolve(strict=False)
            self.assertEqual(config.download_dir, path)

    def test_parse_http_bind_address(self):
        with self.create(dict(http_bind_address="2001:db8::1")) as config_dir:
            config = config_lib.Config.load(config_dir)
            addr = ipaddress.IPv6Address("2001:db8::1")
            self.assertEqual(config.http_bind_address, addr)

        with self.create(dict(http_bind_address="192.168.1.1")) as config_dir:
            config = config_lib.Config.load(config_dir)
            addr = ipaddress.IPv4Address("192.168.1.1")
            self.assertEqual(config.http_bind_address, addr)

    def test_parse_http_enabled(self):
        with self.create(dict(http_enabled=False)) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertFalse(config.http_enabled)

        with self.create(dict(http_enabled="false")) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertTrue(config.http_enabled)

        with self.create(dict(http_enabled=None)) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertFalse(config.http_enabled)

    def test_parse_http_ip_whitelist(self):
        with self.create(dict(http_ip_whitelist=["192.168.1.1"])) as config_dir:
            config = config_lib.Config.load(config_dir)
            nets = [ipaddress.IPv4Network("192.168.1.1/32")]
            self.assertEqual(config.http_ip_whitelist, nets)

        nets = ["2001:db8::/32", "10.0.0.0/8"]
        with self.create(dict(http_ip_whitelist=nets)) as config_dir:
            config = config_lib.Config.load(config_dir)
            nets = [ipaddress.IPv6Network("2001:db8::/32"),
                    ipaddress.IPv4Network("10.0.0.0/8")]
            self.assertEqual(config.http_ip_whitelist, nets)

    def test_parse_http_port(self):
        with self.create(dict(http_port=1234)) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertEqual(config.http_port, 1234)

        with self.create(dict(http_port="1234")) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertEqual(config.http_port, 1234)

    def test_parse_sftp_bind_address(self):
        with self.create(dict(sftp_bind_address="2001:db8::1")) as config_dir:
            config = config_lib.Config.load(config_dir)
            addr = ipaddress.IPv6Address("2001:db8::1")
            self.assertEqual(config.sftp_bind_address, addr)

        with self.create(dict(sftp_bind_address="192.168.1.1")) as config_dir:
            config = config_lib.Config.load(config_dir)
            addr = ipaddress.IPv4Address("192.168.1.1")
            self.assertEqual(config.sftp_bind_address, addr)

    def test_parse_sftp_enabled(self):
        with self.create(dict(sftp_enabled=False)) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertFalse(config.sftp_enabled)

        with self.create(dict(sftp_enabled="false")) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertTrue(config.sftp_enabled)

        with self.create(dict(sftp_enabled=None)) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertFalse(config.sftp_enabled)

    def test_parse_sftp_ip_whitelist(self):
        with self.create(dict(sftp_ip_whitelist=["192.168.1.1"])) as config_dir:
            config = config_lib.Config.load(config_dir)
            nets = [ipaddress.IPv4Network("192.168.1.1/32")]
            self.assertEqual(config.sftp_ip_whitelist, nets)

        nets = ["2001:db8::/32", "10.0.0.0/8"]
        with self.create(dict(sftp_ip_whitelist=nets)) as config_dir:
            config = config_lib.Config.load(config_dir)
            nets = [ipaddress.IPv6Network("2001:db8::/32"),
                    ipaddress.IPv4Network("10.0.0.0/8")]
            self.assertEqual(config.sftp_ip_whitelist, nets)

    def test_parse_sftp_port(self):
        with self.create(dict(sftp_port=1234)) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertEqual(config.sftp_port, 1234)

        with self.create(dict(sftp_port="1234")) as config_dir:
            config = config_lib.Config.load(config_dir)
            self.assertEqual(config.sftp_port, 1234)


class TestLibtorrentSettings(BaseTest):

    def test_normalize_invalid_base_on_save(self):
        contents = dict(libtorrent_settings_base="something_invalid")
        with self.create(contents) as config_dir:
            config = config_lib.Config.load(config_dir)
            settings = config.get_effective_libtorrent_settings()
            expected_settings = lt.default_settings()
            expected_settings.update(config_lib.SettingsPack.get_overrides())
            self.assertEqual(settings, expected_settings)
            config.save()
            config = config_lib.Config.load(config_dir)
            self.assertEqual(config.libtorrent_settings_base, "default_settings")

    def test_valid_nonstandard_base(self):
        contents = dict(libtorrent_settings_base="high_performance_seed")
        with self.create(contents) as config_dir:
            config = config_lib.Config.load(config_dir)
            settings = config.get_effective_libtorrent_settings()
            expected_settings = lt.high_performance_seed()
            expected_settings.update(config_lib.SettingsPack.get_overrides())
            self.assertEqual(settings, expected_settings)
            config.save()
            config = config_lib.Config.load(config_dir)
            self.assertEqual(config.libtorrent_settings_base, "high_performance_seed")

    def test_blacklist(self):
        contents = dict(libtorrent_settings=dict(user_agent="nonstandard"))
        with self.create(contents) as config_dir:
            config = config_lib.Config.load(config_dir)
            settings = config.get_effective_libtorrent_settings()
            self.assertEqual(settings["user_agent"], lt.default_settings()["user_agent"])

    def test_overrides(self):
        contents = dict(libtorrent_settings=dict(enable_dht=True))
        with self.create(contents) as config_dir:
            config = config_lib.Config.load(config_dir)
            settings = config.get_effective_libtorrent_settings()
            self.assertEqual(settings["enable_dht"], False)
