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

import unittest
import urllib.parse

import requests

from tvaf import http as http_lib
from tvaf import session as session_lib

from . import lib


class HTTPDTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = lib.create_isolated_config()
        self.session = session_lib.SessionService(config=self.config).session
        self.httpd = http_lib.HTTPD(session=self.session, config=self.config)
        assert self.httpd.socket is not None
        self.host = "%s:%d" % self.httpd.socket.getsockname()
        self.httpd.start()

    def tearDown(self) -> None:
        self.httpd.terminate()
        self.httpd.join()

    def get(self, path: str) -> requests.Response:
        url = urllib.parse.urlunparse(
            ("http", self.host, path, None, None, None)
        )
        return requests.get(url)

    def test_get(self):
        resp = self.get("/lt/v1/torrents")
        resp.raise_for_status()
        self.assertEqual(resp.json(), [])

    def test_disable_enable(self):
        self.config["http_enabled"] = False
        self.httpd.set_config(self.config)

        with self.assertRaises(requests.ConnectionError):
            self.get("/lt/v1/torrents")

        self.config["http_enabled"] = True
        self.httpd.set_config(self.config)
        self.host = "%s:%d" % self.httpd.socket.getsockname()

        resp = self.get("/lt/v1/torrents")
        resp.raise_for_status()
        self.assertEqual(resp.json(), [])

    def test_change_binding(self):
        self.config["http_bind_address"] = "127.0.0.1"
        self.httpd.set_config(self.config)
        self.host = "%s:%d" % self.httpd.socket.getsockname()

        resp = self.get("/lt/v1/torrents")
        resp.raise_for_status()
        self.assertEqual(resp.json(), [])
