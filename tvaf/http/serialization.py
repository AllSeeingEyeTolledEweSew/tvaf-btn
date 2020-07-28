import base64
from typing import Any
from typing import Collection
from typing import Dict
from typing import List
from typing import Mapping
from typing import Sequence

import libtorrent as lt


def serialize_error_code(ec: lt.error_code) -> Mapping[str, Any]:
    return dict(category=ec.category().name(),
                value=ec.value(),
                message=ec.message())


def serialize_bit_list(bit_list: Sequence[bool]) -> str:
    bitfield_bytes = bytearray()
    byte = 0
    length = len(bit_list)
    for i, value in enumerate(bit_list):
        if value:
            byte |= 1 << (i & 7)
        if i & 7 == 7 or i == length - 1:
            bitfield_bytes.append(byte)
            byte = 0
    return base64.b64encode(bitfield_bytes).decode()


_FLAG_FIELDS = {
    "flag_seed_mode": lt.torrent_flags.seed_mode,
    "flag_upload_mode": lt.torrent_flags.upload_mode,
    "flag_share_mode": lt.torrent_flags.share_mode,
    "flag_apply_ip_filter": lt.torrent_flags.apply_ip_filter,
    "flag_paused": lt.torrent_flags.paused,
    "flag_auto_managed": lt.torrent_flags.auto_managed,
    "flag_duplicate_is_error": lt.torrent_flags.duplicate_is_error,
    "flag_update_subscribe": lt.torrent_flags.update_subscribe,
    "flag_super_seeding": lt.torrent_flags.super_seeding,
    "flag_sequential_download": lt.torrent_flags.sequential_download,
    "flag_stop_when_ready": lt.torrent_flags.stop_when_ready,
    "flag_override_trackers": lt.torrent_flags.override_trackers,
    "flag_override_web_seeds": lt.torrent_flags.override_web_seeds,
    "flag_disable_dht": lt.torrent_flags.disable_dht,
    "flag_disable_lsd": lt.torrent_flags.disable_lsd,
    "flag_disable_pex": lt.torrent_flags.disable_pex,
}


class TorrentStatusSerializer:

    _SIMPLE_FIELDS = frozenset(
        ("name", "save_path", "error_file", "progress", "has_metadata",
         "progress_ppm", "current_tracker", "total_download", "total_upload",
         "total_payload_download", "total_payload_upload", "total_failed_bytes",
         "total_redundant_bytes", "download_rate", "upload_rate",
         "download_payload_rate", "upload_payload_rate", "num_seeds",
         "num_peers", "num_complete", "num_incomplete", "list_seeds",
         "list_peers", "connect_candidates", "num_pieces", "total_done",
         "total_wanted_done", "total_wanted", "distributed_full_copies",
         "distributed_fraction", "distributed_copies", "block_size",
         "num_uploads", "num_connections", "uploads_limit", "connections_limit",
         "up_bandwidth_queue", "all_time_upload", "all_time_download",
         "seed_rank", "has_incoming", "added_time", "completed_time",
         "last_seen_complete", "queue_position", "need_save_resume",
         "moving_storage", "announcing_to_trackers", "announcing_to_lsd",
         "announcing_to_dht", "flags"))
    _FIELD_SERIALIZERS = {
        "pieces": serialize_bit_list,
        "verified_pieces": serialize_bit_list,
        "errc": serialize_error_code,
    }

    FIELDS = (_SIMPLE_FIELDS | frozenset(_FIELD_SERIALIZERS.keys()) |
              frozenset(_FLAG_FIELDS.keys()) | frozenset(
                  ("info_hashes", "state", "storage_mode")))

    def __init__(self, fields: Collection[str] = None):
        if fields is None:
            fields = self.FIELDS
        self.fields = fields

    def serialize(self, status: lt.torrent_status) -> Mapping[str, Any]:
        simple_fields = self._SIMPLE_FIELDS
        field_serializers = self._FIELD_SERIALIZERS
        flag_fields = _FLAG_FIELDS

        result: Dict[str, Any] = {}

        for field in self.fields:
            if field in simple_fields:
                result[field] = getattr(status, field)
            elif field in field_serializers:
                result[field] = field_serializers[field](getattr(status, field))
            elif field == "info_hashes":
                result[field] = dict(v1=str(status.info_hash))
            elif field == "state":
                result[field] = status.state.name
            elif field == "storage_mode":
                result[field] = status.storage_mode.name
            elif field in flag_fields:
                result[field] = bool(status.flags & flag_fields[field])
            # TODO: last_upload, last_download, active_duration,
            # finished_duration, seeding_duration

        return result


def _serialize_file_list(
        storage: lt.file_storage) -> Sequence[Mapping[str, Any]]:
    result: List[Dict[str, Any]] = []

    for i in range(storage.num_files()):
        file_entry = dict(index=i,
                          offset=storage.file_offset(i),
                          path=storage.file_path(i),
                          size=storage.file_size(i))
        # TODO: symlink() seems to crash
        # TODO: mtime() not mapped on python bindings
        info_hash = storage.hash(i)
        if not info_hash.is_all_zeros():
            file_entry["info_hashes"] = dict(v1=str(info_hash))
        flags = storage.file_flags(i)
        attr = ""
        storage_cls = lt.file_storage
        if flags & storage_cls.flag_pad_file:
            attr += "p"
        if flags & storage_cls.flag_hidden:
            attr += "h"
        if flags & storage_cls.flag_executable:
            attr += "x"
        if flags & storage_cls.flag_symlink:
            attr += "l"
        file_entry["attr"] = attr

        result.append(file_entry)

    return result


class TorrentInfoSerializer:
    # Unused fields: trackers, web_seeds, nodes

    _SIMPLE_CALLABLE_FIELDS = frozenset(
        ("collections", "piece_length", "num_pieces", "total_size", "priv",
         "is_i2p", "name", "creation_date", "creator", "comment"))

    FIELDS = _SIMPLE_CALLABLE_FIELDS | frozenset(
        ("files", "orig_files", "merkle_tree", "similar_torrents", "metadata",
         "hash_for_piece", "info_hashes"))

    def __init__(self, fields: Collection[str] = None):
        if fields is None:
            fields = self.FIELDS
        self.fields = fields

    def serialize(self, info: lt.torrent_info) -> Mapping[str, Any]:
        simple_callable_fields = self._SIMPLE_CALLABLE_FIELDS

        result: Dict[str, Any] = {}

        for field in self.fields:
            if field in simple_callable_fields:
                result[field] = getattr(info, field)()
            elif field == "info_hashes":
                result[field] = dict(v1=str(info.info_hash()))
            elif field in ("files", "orig_files"):
                result[field] = _serialize_file_list(getattr(info, field)())
            elif field in ("merkle_tree", "similar_torrents"):
                result[field] = [str(ih) for ih in getattr(info, field)()]
            elif field == "metadata":
                result[field] = base64.b64encode(info.metadata()).decode()
            elif field == "hash_for_piece":
                result[field] = [
                    info.hash_for_piece(i).hex()
                    for i in range(info.num_pieces())
                ]
            # TODO: ssl_cert returns string instead of bytes

        return result


class TorrentHandleSerializer:

    _SIMPLE_CALLABLE_FIELDS = frozenset(
        ("file_progress", "trackers", "url_seeds", "http_seeds", "flags",
         "need_save_resume_data", "queue_position", "piece_availability",
         "piece_priorities", "file_priorities", "download_limit",
         "upload_limit", "max_uploads", "max_connections"))

    FIELDS = _SIMPLE_CALLABLE_FIELDS | frozenset(
        _FLAG_FIELDS.keys()) | frozenset(("info_hashes",))

    def __init__(self, fields: Collection[str] = None):
        if fields is None:
            fields = self.FIELDS
        self.fields = fields

    def serialize(self, handle: lt.torrent_handle) -> Mapping[str, Any]:
        result: Dict[str, Any] = {}
        simple_callable_fields = self._SIMPLE_CALLABLE_FIELDS
        flag_fields = _FLAG_FIELDS

        # TODO: most (all?) fields block on access, maybe cache them

        # TODO: download_queue not bound in python
        # TODO: piece_deadlines not exposed at all
        # TODO: open_file_state::last_use binding broken
        # TODO: open_file_state::open_mode binding broken

        for field in self.fields:
            if field in simple_callable_fields:
                result[field] = getattr(handle, field)()
            elif field == "info_hashes":
                result[field] = dict(v1=str(handle.info_hash()))
            elif field in flag_fields:
                result[field] = bool(handle.flags() & flag_fields[field])

        return result


_TORRENT_FIELD_TO_QUERY_FLAG = {
    "distributed_copies": lt.torrent_handle.query_distributed_copies,
    "distributed_full_copies": lt.torrent_handle.query_distributed_copies,
    "distributed_fraction": lt.torrent_handle.query_distributed_copies,
    "last_seen_complete": lt.torrent_handle.query_last_seen_complete,
    "pieces": lt.torrent_handle.query_pieces,
    "verified_pieces": lt.torrent_handle.query_verified_pieces,
    #"name": lt.torrent_handle.query_name,
    #"save_path": lt.torrent_handle.query_save_path,
}

#for _field in TorrentInfoSerializer.FIELDS:
#    _TORRENT_FIELD_TO_QUERY_FLAG[_field] = lt.torrent_handle.query_torrent_file
