# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for the tvaf.transmission module."""
import unittest

import requests_mock
from tvaf.transmission import APIError
from tvaf.transmission import Client
from tvaf.transmission import File
from tvaf.transmission import HTTPError
from tvaf.transmission import Status
from tvaf.transmission import Torrent
from tvaf.transmission import TrackerState
from tvaf.transmission import TrackerStats


class TestClient(unittest.TestCase):
    """Tests for tvaf.transmission.Client."""

    maxDiff = None

    def test_conflict(self):

        def has_no_session_id(req):
            return "X-Transmission-Session-Id" not in req.headers

        client = Client()
        with requests_mock.Mocker() as mock:
            mock.post("http://localhost:9091/transmission/rpc",
                      additional_matcher=has_no_session_id,
                      headers={"X-Transmission-Session-Id": "blah-blah"},
                      status_code=409,
                      text="this is not json!")
            mock.post(
                "http://localhost:9091/transmission/rpc",
                request_headers={"X-Transmission-Session-Id": "blah-blah"},
                json=dict(result="success", arguments=dict(torrents=[])))

            result = client.torrent_get()

        self.assertEqual(len(result.torrents), 0)

    def test_http_error(self):
        client = Client()
        with requests_mock.Mocker() as mock:
            mock.post("http://localhost:9091/transmission/rpc",
                      status_code=401,
                      reason="Not authorized",
                      text="this is not json")
            with self.assertRaises(HTTPError):
                client.torrent_get()

    def test_api_error(self):
        client = Client()
        with requests_mock.Mocker() as mock:
            mock.post("http://localhost:9091/transmission/rpc",
                      json=dict(result="an error occurred"))
            with self.assertRaises(APIError):
                client.torrent_get()

    def test_torrent_get_one(self):
        client = Client()
        torrent_dict = {
            "totalSize":
                1048576,
            "hashString":
                "da39a3ee5e6b4b0d3255bfef95601890afd80709",
            "pieceSize":
                65536,
            "pieces":
                "/88=",
            "downloadDir":
                "/path/to/data",
            "status":
                0,
            "block-in-cache":
                "EQAAAAAAAAA=",
            "max-requests-per-block": [1, 1, 1, 1, 1],
            "piece-get":
                "//8=",
            "piece-priorities": [5, 4, 3, 2, 1],
            "pieceCount":
                64,
            "files": [{
                "name": "movie.mkv",
                "length": 1038576
            }, {
                "name": "movie.en.srt",
                "length": 10000
            }],
            "trackerStats": [{
                "announce": "http://example.com",
                "announceState": 1,
                "hasAnnounced": True,
                "hasScraped": True,
                "lastAnnounceResult": "hello world",
                "lastAnnounceSucceeded": True,
                "lastAnnounceTimedOut": False,
                "lastScrapeResult": "hello friend",
                "lastScrapeSucceeded": True,
                "lastScrapeTimedOut": False,
                "leecherCount": 5,
                "scrapeState": 1,
                "seederCount": 420,
            }],
        }
        with requests_mock.Mocker() as mock:
            mock.post("http://localhost:9091/transmission/rpc",
                      json=dict(result="success",
                                arguments=dict(torrents=[torrent_dict])))
            result = client.torrent_get(
                torrent_ids="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                fields=("hashString", "et-al"),
                timeout=123.0)

        self.assertEqual(mock.call_count, 1)
        call_json = mock.last_request.json()
        self.assertEqual(
            call_json,
            dict(method="torrent-get",
                 arguments=dict(ids="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                                fields=["hashString", "et-al"])))

        self.assertEqual(len(result.torrents), 1)
        torrent = Torrent(
            totalSize=1048576,
            hashString="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            pieceSize=65536,
            pieces=b"\xff\xcf",
            downloadDir="/path/to/data",
            status=int(Status.STOPPED),
            block_in_cache=b"\x11\x00\x00\x00\x00\x00\x00\x00",
            max_requests_per_block=[1, 1, 1, 1, 1],
            piece_get=b"\xff\xff",
            piece_priorities=[5, 4, 3, 2, 1],
            pieceCount=64,
            files=[
                File(name="movie.mkv", length=1038576),
                File(name="movie.en.srt", length=10000),
            ],
            trackerStats=[
                TrackerStats(
                    announce="http://example.com",
                    announceState=int(TrackerState.WAITING),
                    hasAnnounced=True,
                    hasScraped=True,
                    lastAnnounceResult="hello world",
                    lastAnnounceSucceeded=True,
                    lastAnnounceTimedOut=False,
                    lastScrapeResult="hello friend",
                    lastScrapeSucceeded=True,
                    lastScrapeTimedOut=False,
                    leecherCount=5,
                    scrapeState=int(TrackerState.WAITING),
                    seederCount=420,
                )
            ],
        )
        self.assertEqual(result.torrents[0], torrent)

    def test_torrent_get_all(self):
        client = Client()
        with requests_mock.Mocker() as mock:
            mock.post("http://localhost:9091/transmission/rpc",
                      json=dict(result="success", arguments=dict(torrents=[])))

            client.torrent_get(fields=["hashString"])

        self.assertEqual(
            mock.last_request.json(),
            dict(method="torrent-get", arguments=dict(fields=["hashString"])))
