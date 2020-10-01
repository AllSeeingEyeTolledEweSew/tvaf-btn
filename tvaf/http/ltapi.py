from typing import AbstractSet
from typing import Any
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional

import flask
import libtorrent as lt
import werkzeug.exceptions

import tvaf.http.serialization as ser_lib
from tvaf import ltpy
from tvaf import types

from . import util as http_util

_ALL_TORRENT_FIELDS = (ser_lib.TorrentStatusSerializer.FIELDS |
                       ser_lib.TorrentHandleSerializer.FIELDS |
                       ser_lib.TorrentInfoSerializer.FIELDS)


def get_torrent_fields() -> Optional[AbstractSet[str]]:
    fields_str = flask.request.args.get("fields", "")
    if not fields_str:
        return None
    fields = frozenset(fields_str.split(","))
    _all_fields = _ALL_TORRENT_FIELDS
    for field in fields:
        if field not in _all_fields:
            raise werkzeug.exceptions.BadRequest()
    return fields


class TorrentSerializer:

    def __init__(self, fields: AbstractSet[str] = None):
        self.handle_serializer: Optional[ser_lib.TorrentHandleSerializer] = None
        self.status_serializer: Optional[ser_lib.TorrentStatusSerializer] = None
        self.info_serializer: Optional[ser_lib.TorrentInfoSerializer] = None

        if fields is None:
            self.handle_serializer = ser_lib.TorrentHandleSerializer()
            self.status_serializer = ser_lib.TorrentStatusSerializer()
            self.info_serializer = ser_lib.TorrentInfoSerializer()
        else:
            handle_fields = fields & ser_lib.TorrentHandleSerializer.FIELDS
            if handle_fields:
                self.handle_serializer = ser_lib.TorrentHandleSerializer(
                    handle_fields)

            status_fields = fields & ser_lib.TorrentStatusSerializer.FIELDS
            if status_fields:
                self.status_serializer = ser_lib.TorrentStatusSerializer(
                    status_fields)

            info_fields = fields & ser_lib.TorrentInfoSerializer.FIELDS
            if info_fields:
                self.info_serializer = ser_lib.TorrentInfoSerializer(
                    info_fields)

    def serialize(self, handle: lt.torrent_handle) -> Mapping[str, Any]:
        result: Dict[str, Any] = {}

        if self.handle_serializer:
            result.update(self.handle_serializer.serialize(handle))

        if self.status_serializer:
            status = handle.status()
            result.update(self.status_serializer.serialize(status))

        if self.info_serializer:
            info = handle.torrent_file()
            result.update(self.info_serializer.serialize(info))

        return result


class V1Blueprint(http_util.Blueprint):

    def __init__(self, session: lt.session):
        super().__init__("v1", __name__)
        self.session = session

    def find_torrent(self, info_hash: types.InfoHash) -> lt.torrent_handle:
        try:
            info_hash_bytes = bytes.fromhex(info_hash)
        except ValueError as exc:
            raise werkzeug.exceptions.NotFound() from exc
        with ltpy.translate_exceptions():
            sha1_hash = lt.sha1_hash(info_hash_bytes)
            handle = self.session.find_torrent(sha1_hash)
            if not handle.is_valid():
                raise werkzeug.exceptions.NotFound()
        return handle

    @http_util.route("/torrents/<info_hash>")
    def get_torrent(self, info_hash: types.InfoHash):
        handle = self.find_torrent(info_hash)
        serializer = TorrentSerializer(get_torrent_fields())
        try:
            return serializer.serialize(handle)
        except ltpy.InvalidTorrentHandleError as exc:
            raise werkzeug.exceptions.NotFound() from exc

    @http_util.route("/torrents")
    def get_torrents(self):
        serializer = TorrentSerializer(get_torrent_fields())
        result: List[Mapping[str, Any]] = []
        for handle in self.session.get_torrents():
            try:
                result.append(serializer.serialize(handle))
            except ltpy.InvalidTorrentHandleError:
                pass
        return flask.jsonify(result)
