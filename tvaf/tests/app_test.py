# Copyright (c) 2020 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

import os
import pathlib
import tempfile
import unittest
import urllib.parse

import libtorrent as lt
import requests

from tvaf import app as app_lib
from tvaf import config as config_lib
from tvaf import resume as resume_lib

from . import lib
from . import tdummy


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tempdir.name)

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        self.tempdir.cleanup()

    def test_load_isolated(self) -> None:
        config = lib.create_isolated_config()
        config.write_to_disk()
        app_lib.App()

    def test_corrupt(self) -> None:
        config_lib.PATH.write_text("not json")
        with self.assertRaises(config_lib.InvalidConfigError):
            app_lib.App()

    # TODO: how do we test writing default config while staying isolated?


class ResumeDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tempdir.name)
        self.config = lib.create_isolated_config()
        self.config.write_to_disk()
        resume_lib.RESUME_DATA_PATH.mkdir(parents=True, exist_ok=True)
        self.app = app_lib.App()
        self.download_dir = pathlib.Path("download")

    def tearDown(self) -> None:
        self.app.terminate()
        self.app.join()
        os.chdir(self.cwd)
        self.tempdir.cleanup()

    def get(self, path: str) -> requests.Response:
        sock = self.app.http_socket
        assert sock is not None
        host = "%s:%d" % sock.getsockname()
        url = urllib.parse.urlunparse(("http", host, path, None, None, None))
        return requests.get(url)

    def test_none(self) -> None:
        self.app.start()
        resp = self.get("/lt/v1/torrents")
        resp.raise_for_status()
        self.assertEqual(resp.json(), [])

    def write(
        self, atp: lt.add_torrent_params, ti: lt.torrent_info = None
    ) -> None:
        info_hash = str(atp.info_hash)
        base = resume_lib.RESUME_DATA_PATH.joinpath(info_hash)
        base.with_suffix(".resume").write_bytes(lt.write_resume_data_buf(atp))
        if ti is not None:
            base.with_suffix(".torrent").write_bytes(
                lt.bencode({b"info": lt.bdecode(ti.metadata())})
            )

    def test_existing(self) -> None:
        atp = tdummy.DEFAULT.atp()
        atp.save_path = str(self.download_dir)
        self.write(atp, tdummy.DEFAULT.torrent_info())

        self.app.start()
        resp = self.get("/lt/v1/torrents")
        resp.raise_for_status()
        torrents = resp.json()
        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0]["info_hash"]["v1"], str(atp.info_hash))
