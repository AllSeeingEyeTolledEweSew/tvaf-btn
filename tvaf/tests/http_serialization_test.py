import os

import libtorrent as lt

from tvaf.http import serialization

from . import lib
from . import tdummy
from . import test_utils


class TorrentInfoSerializerTest(lib.TestCase):

    def test_serialize_default_fields(self):
        ti = tdummy.DEFAULT_STABLE.torrent_info()
        serializer = serialization.TorrentInfoSerializer()
        result = serializer.serialize(ti)
        self.assert_golden_json(result)

    def test_serialize_stable_fields(self):
        ti = tdummy.DEFAULT.torrent_info()
        fields = serialization.TorrentInfoSerializer.FIELDS - set(
            ("info_hashes", "hash_for_piece", "metadata", "merkle_tree"))
        serializer = serialization.TorrentInfoSerializer(fields)
        result = serializer.serialize(ti)
        self.assert_golden_json(result)


class TorrentStatusSerializer(lib.TestCase):

    def setUp(self):
        self.session = test_utils.create_isolated_session()
        self.atp = lt.add_torrent_params()

    def test_serialize_default_fields(self):
        self.atp.ti = tdummy.DEFAULT_STABLE.torrent_info()
        handle = self.session.add_torrent(self.atp)
        serializer = serialization.TorrentStatusSerializer()
        result = serializer.serialize(handle.status())
        self.assertGreater(result.pop("added_time"), 0)
        self.assertEqual(result.pop("save_path"), os.getcwd())
        self.assert_golden_json(result)

    def test_serialize_stable_fields(self):
        self.atp.ti = tdummy.DEFAULT.torrent_info()
        handle = self.session.add_torrent(self.atp)
        fields = serialization.TorrentStatusSerializer.FIELDS - set(
            ("info_hashes", "added_time", "save_path"))
        serializer = serialization.TorrentStatusSerializer(fields)
        result = serializer.serialize(handle.status())
        self.assert_golden_json(result)


class TorrentHandleSerializer(lib.TestCase):

    def setUp(self):
        self.session = test_utils.create_isolated_session()
        self.atp = lt.add_torrent_params()

    def test_serialize_default_fields(self):
        self.atp.ti = tdummy.DEFAULT_STABLE.torrent_info()
        self.atp.ti.add_tracker("http://does_not_exist/", 0,
                                lt.tracker_source.source_client)
        handle = self.session.add_torrent(self.atp)
        serializer = serialization.TorrentHandleSerializer()
        result = serializer.serialize(handle)
        self.assert_golden_json(result)

    def test_serialize_stable_fields(self):
        self.atp.ti = tdummy.DEFAULT.torrent_info()
        self.atp.ti.add_tracker("http://does_not_exist/", 0,
                                lt.tracker_source.source_client)
        handle = self.session.add_torrent(self.atp)
        fields = serialization.TorrentHandleSerializer.FIELDS - set(
            ("info_hashes",))
        serializer = serialization.TorrentHandleSerializer(fields)
        result = serializer.serialize(handle)
        self.assert_golden_json(result)
