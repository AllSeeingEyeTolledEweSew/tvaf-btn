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

import base64
import hashlib
import tempfile
import unittest

import flask
import libtorrent as lt

from tvaf.http import ltapi

from . import lib
from . import tdummy


class TestV1Base(unittest.TestCase):
    def setUp(self) -> None:
        self.session = lib.create_isolated_session_service().session
        self.app = flask.Flask(__name__)
        self.v1_blueprint = ltapi.V1Blueprint(self.session)
        self.app.register_blueprint(self.v1_blueprint.blueprint)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.client.__enter__()
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tempdir.cleanup()


class TestSingleTorrent(TestV1Base, lib.TestCase):
    def test_malformed_url(self) -> None:
        response = self.client.get("/torrents/wxyz")
        self.assertEqual(response.status_code, 404)

    def test_short_hex(self) -> None:
        response = self.client.get("/torrents/abcd1234")
        self.assertEqual(response.status_code, 404)

    def test_missing_torrent(self) -> None:
        response = self.client.get("/torrents/%s" % ("0" * 40))
        self.assertEqual(response.status_code, 404)

    def test_valid(self) -> None:
        torrent = tdummy.DEFAULT

        atp = torrent.atp()
        atp.save_path = self.tempdir.name
        self.session.add_torrent(atp)
        response = self.client.get("/torrents/%s" % torrent.info_hash)
        self.assertEqual(response.status_code, 200)
        data = response.json

        # Remove non-stable fields and check individually

        added_time = data.pop("added_time")
        self.assertGreater(added_time, 0)

        hashes = data.pop("hash_for_piece")
        self.assertEqual(
            hashes,
            [hashlib.sha1(piece).hexdigest() for piece in torrent.pieces],
        )

        info_hash = data.pop("info_hash")
        self.assertEqual(info_hash, {"v1": torrent.info_hash})

        metadata = data.pop("metadata")
        self.assertEqual(lt.bdecode(base64.b64decode(metadata)), torrent.info)

        data.pop("save_path")

        # State changes between checking_resume_data and downloading
        data.pop("state")

        # Check remaining data against golden
        self.assert_golden_json(data)

    def test_valid_stable(self) -> None:
        torrent = tdummy.DEFAULT_STABLE

        atp = torrent.atp()
        atp.save_path = self.tempdir.name
        self.session.add_torrent(atp)
        response = self.client.get("/torrents/%s" % torrent.info_hash)
        self.assertEqual(response.status_code, 200)
        data = response.json

        # Remove non-stable fields and check individually

        added_time = data.pop("added_time")
        self.assertGreater(added_time, 0)

        data.pop("save_path")

        # State changes between checking_resume_data and downloading
        data.pop("state")

        # Check remaining data against golden
        self.assert_golden_json(data)

    def test_query_fields(self) -> None:
        torrent = tdummy.DEFAULT

        atp = torrent.atp()
        atp.save_path = self.tempdir.name
        self.session.add_torrent(atp)
        response = self.client.get(
            "/torrents/%s?fields=pieces,info_hash" % torrent.info_hash
        )
        self.assertEqual(response.status_code, 200)
        data = response.json

        self.assertEqual(
            data, {"info_hash": {"v1": torrent.info_hash}, "pieces": "AAA="}
        )


class TestTorrents(TestV1Base, lib.TestCase):
    def test_empty(self) -> None:
        response = self.client.get("/torrents")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, [])

    def test_valid_stable(self) -> None:
        torrent = tdummy.DEFAULT_STABLE

        atp = torrent.atp()
        atp.save_path = self.tempdir.name
        self.session.add_torrent(atp)
        response = self.client.get("/torrents")
        self.assertEqual(response.status_code, 200)
        data = response.json

        self.assertEqual(len(data), 1)

        # Remove non-stable fields and check individually

        added_time = data[0].pop("added_time")
        self.assertGreater(added_time, 0)

        data[0].pop("save_path")

        # State changes between checking_resume_data and downloading
        data[0].pop("state")

        # check remaining data against golden
        self.assert_golden_json(data)

    def test_query_fields(self) -> None:
        torrent = tdummy.DEFAULT

        atp = torrent.atp()
        atp.save_path = self.tempdir.name
        self.session.add_torrent(atp)
        response = self.client.get("/torrents?fields=pieces,info_hash")
        self.assertEqual(response.status_code, 200)
        data = response.json

        self.assertEqual(
            data, [{"info_hash": {"v1": torrent.info_hash}, "pieces": "AAA="}]
        )
