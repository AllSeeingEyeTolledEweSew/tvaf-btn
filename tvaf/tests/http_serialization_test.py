import tempfile

import libtorrent as lt

from tvaf.http import serialization

from . import lib
from . import tdummy


class TorrentInfoSerializerTest(lib.TestCase):
    def test_serialize_default_fields(self):
        torrent_info = tdummy.DEFAULT_STABLE.torrent_info()
        serializer = serialization.TorrentInfoSerializer()
        result = serializer.serialize(torrent_info)
        self.assert_golden_json(result)

    def test_serialize_stable_fields(self):
        torrent_info = tdummy.DEFAULT.torrent_info()
        fields = serialization.TorrentInfoSerializer.FIELDS - set(
            ("info_hash", "hash_for_piece", "metadata", "merkle_tree")
        )
        serializer = serialization.TorrentInfoSerializer(fields)
        result = serializer.serialize(torrent_info)
        self.assert_golden_json(result)


class TorrentStatusSerializer(lib.TestCase):
    def setUp(self):
        self.session = lib.create_isolated_session_service().session
        self.tempdir = tempfile.TemporaryDirectory()
        self.atp = lt.add_torrent_params()
        self.atp.save_path = self.tempdir.name

    def tearDown(self):
        self.tempdir.cleanup()

    def test_serialize_default_fields(self):
        self.atp.ti = tdummy.DEFAULT_STABLE.torrent_info()
        handle = self.session.add_torrent(self.atp)
        serializer = serialization.TorrentStatusSerializer()
        result = serializer.serialize(handle.status())
        self.assertGreater(result.pop("added_time"), 0)
        self.assertEqual(result.pop("save_path"), self.tempdir.name)
        self.assert_golden_json(result)

    def test_serialize_stable_fields(self):
        self.atp.ti = tdummy.DEFAULT.torrent_info()
        handle = self.session.add_torrent(self.atp)
        fields = serialization.TorrentStatusSerializer.FIELDS - set(
            ("info_hash", "added_time", "save_path")
        )
        serializer = serialization.TorrentStatusSerializer(fields)
        result = serializer.serialize(handle.status())
        self.assert_golden_json(result)


class TorrentHandleSerializer(lib.TestCase):
    def setUp(self):
        self.session = lib.create_isolated_session_service().session
        self.tempdir = tempfile.TemporaryDirectory()
        self.atp = lt.add_torrent_params()
        self.atp.save_path = self.tempdir.name

    def tearDown(self):
        self.tempdir.cleanup()

    def test_serialize_default_fields(self):
        self.atp.ti = tdummy.DEFAULT_STABLE.torrent_info()
        self.atp.ti.add_tracker(
            "http://does_not_exist/", 0, lt.tracker_source.source_client
        )
        handle = self.session.add_torrent(self.atp)
        serializer = serialization.TorrentHandleSerializer()
        result = serializer.serialize(handle)
        self.assert_golden_json(result)

    def test_serialize_stable_fields(self):
        self.atp.ti = tdummy.DEFAULT.torrent_info()
        self.atp.ti.add_tracker(
            "http://does_not_exist/", 0, lt.tracker_source.source_client
        )
        handle = self.session.add_torrent(self.atp)
        fields = serialization.TorrentHandleSerializer.FIELDS - set(
            ("info_hash",)
        )
        serializer = serialization.TorrentHandleSerializer(fields)
        result = serializer.serialize(handle)
        self.assert_golden_json(result)
