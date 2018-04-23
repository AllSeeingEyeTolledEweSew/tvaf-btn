import hashlib
import logging
import os
import urlparse

import requests
from tvaf import plex as tvaf_plex


def log():
    """Gets a module-level logger."""
    return logging.getLogger(__name__)


def chunks(l, n):
    for i in xrange(0, len(l), n):
        yield l[i:i + n]


class Changes(object):

    @classmethod
    def from_exclusive_items(cls, items):
        guid_to_items = {}
        tracker_torrent_id_to_items = {}
        for item in items:
            guid = item.metadata_item.guid
            if guid not in guid_to_items:
                guid_to_items[guid] = []
            guid_to_items[guid].append(item)

            tracker = item.tracker
            torrent_id = item.parts[0].torrent_id
            key = (tracker, torrent_id)
            if key not in tracker_torrent_id_to_items:
                tracker_torrent_id_to_items[key] = []
            tracker_torrent_id_to_items[key].append(item)

        return cls(
            guid_to_items=guid_to_items,
            tracker_torrent_id_to_items=tracker_torrent_id_to_items)

    def __init__(self, guid_to_items=None, tracker_torrent_id_to_items=None):
        self.guid_to_items = guid_to_items or {}
        self.tracker_torrent_id_to_items = tracker_torrent_id_to_items or {}


class Syncer(object):

    def __init__(self, library_section, plex_host=None, yatfs_path=None):
        self.library_section = library_section
        self.db = library_section.db
        self.plex_host = plex_host
        self.yatfs_path = yatfs_path.encode()

        self._any_deleted = False
        self._refresh_metadata = set()
        self._session = requests.Session()

    def finalize(self):
        if self._any_deleted:
            self.http_put(
                "/library/sections/%d/emptyTrash" % self.library_section.id)
            self.any_deleted = False
        for id, type, guid in self._refresh_metadata:
            self.http_get("/:/metadata/notify/changeItemState", params=dict(
                librarySectionID=self.library_section.id, metadataItemID=id,
                metadataType=type, state=3, metadataState="queued"))
            self.http_get("/system/agents/update", params=dict(
                mediaType=type, force=1, guid=guid, id=id))
        self._refresh_metadata.clear()

    def http_call(self, method, path, **kwargs):
        uri = urlparse.urlunparse(
            ("http", self.plex_host, path, None, None, None))
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"]["X-Plex-Token"] = tvaf_plex.get_token(
            self.db.plex_path)
        return method(uri, **kwargs)

    def http_get(self, path, **kwargs):
        return self.http_call(self._session.get, path, **kwargs)

    def http_put(self, path, **kwargs):
        return self.http_call(self._session.put, path, **kwargs)

    def refresh_metadata_later(self, id, item):
        self._refresh_metadata.add((id, item.type, item.guid))

    def sync_metadata_item(self, item):
        if item is None:
            return None
        with self.db.conn:
            r = self.db.conn.cursor().execute(
                "select id from metadata_items where deleted_at is null and "
                "library_section_id = ? and guid = ?",
                (self.library_section.id, item.guid)).fetchone()
            if r:
                id, = r
            else:
                self.db.conn.cursor().execute(
                    "insert into metadata_items "
                    "(library_section_id, guid, title) values (?, ?, ?)",
                    (self.library_section.id, item.guid, item.default_title))
                id = self.db.conn.last_insert_rowid()
                if item.parent is None:
                    self.refresh_metadata_later(id, item)
                log().debug("added metadata item %d for %s", id, item.guid)
            params = [
                ("metadata_type", item.type),
                ("guid", item.guid),
                ("parent_id", self.sync_metadata_item(item.parent)),
                ("title", item.title),
                ("\"index\"", item.index),
                ("originally_available_at", item.originally_available_at),
            ]
            params = [(n, v) for n, v in params if v is not None]
            if params:
                self.db.conn.cursor().execute(
                    "update metadata_items set %s where id = ?" %
                    ", ".join("%s = ?" % n for n, v in params),
                    [v for n, v in params] + [id])
            return id

    def sync_media_item(self, item):
        with self.db.conn:
            id = None
            r = self.db.conn.cursor().execute(
                "select media_items.id from tvaf_metadata "
                "inner join media_items "
                "on media_items.id = tvaf_metadata.id "
                "where "
                "media_items.deleted_at is null and "
                "media_items.library_section_id = ? and "
                "tvaf_metadata.tracker = ? and "
                "tvaf_metadata.torrent_id = ? and "
                "tvaf_metadata.first_file_index = ? and "
                "tvaf_metadata.offset is  ?",
                (self.library_section.id, item.tracker,
                    item.parts[0].torrent_id, item.parts[0].file_index,
                    item.offset)).fetchone()
            if r:
                id, = r
                # Plex doesn't support soft-delete of an individual media part.
                # If any parts need to be changed, we need to soft-delete the
                # whole item and create a new one.
                expected_paths = [
                    self.path_for_media_part(p) for p in item.parts]
                rows = self.db.conn.cursor().execute(
                    "select cast(file as blob) from media_parts where "
                    "media_item_id = ? and deleted_at is null "
                    "order by \"index\"", (id,)).fetchall()
                paths = [p for p, in rows]
                if paths != expected_paths:
                    log().debug("%s != %s", paths, expected_paths)
                    self.delete_media_items(id)
                    id = None
            if id is None:
                self.db.conn.cursor().execute(
                    "insert into media_items (library_section_id) values (?)",
                    (self.library_section.id,))
                id = self.db.conn.last_insert_rowid()
                self.db.conn.cursor().execute(
                    "insert or replace into tvaf_metadata "
                    "(id, tracker, torrent_id, first_file_index, offset) "
                    "values (?, ?, ?, ?, ?)",
                    (id, item.tracker, item.parts[0].torrent_id,
                        item.parts[0].file_index, item.offset))
                log().debug(
                    "added media item %d for %s:%s:%s:%s", id, item.tracker,
                    item.parts[0].torrent_id, item.parts[0].file_index,
                    item.offset)
            self.db.conn.cursor().execute(
                "update media_items set metadata_item_id = ?, "
                "display_offset = ? where id = ?",
                (self.sync_metadata_item(item.metadata_item), item.offset, id))
            for part in item.parts:
                self.sync_media_part(id, part)
            return id

    def sync_torrent_exclusive(self, tracker, torrent_id, *items):
        with self.db.conn:
            media_item_ids = [self.sync_media_item(i) for i in items]
            rows = self.db.conn.cursor().execute(
                "select media_items.id from tvaf_metadata "
                "inner join media_items on "
                "tvaf_metadata.id = media_items.id "
                "where media_items.library_section_id = ? and "
                "tvaf_metadata.tracker = ? and "
                "tvaf_metadata.torrent_id = ?",
                (self.library_section.id, tracker, torrent_id)).fetchall()
            all_media_item_ids = [id for id, in rows]
            media_item_ids_to_delete = list(
                set(all_media_item_ids) - set(media_item_ids))
            self.delete_media_items(*media_item_ids_to_delete)

    def sync_guid_exclusive(self, guid, *items):
        with self.db.conn:
            media_item_ids = [self.sync_media_item(i) for i in items]
            rows = self.db.conn.cursor().execute(
                "select media_items.id from metadata_items "
                "inner join media_items on "
                "media_items.metadata_item_id = metadata_items.id "
                "where metadata_items.guid = ? "
                "and metadata_items.library_section_id = ?",
                (guid, self.library_section.id)).fetchall()
            all_media_item_ids = [id for id, in rows]
            media_item_ids_to_delete = list(
                set(all_media_item_ids) - set(media_item_ids))
            self.delete_media_items(*media_item_ids_to_delete)

    def delete_media_items(self, *ids):
        if not ids:
            return
        log().debug("deleting media items: %s", ids)
        with self.db.conn:
            self.db.conn.cursor().executemany(
                "update media_items "
                "set deleted_at = datetime('now', 'localtime') where id = ?",
                [(id,) for id in ids])
            self.db.conn.cursor().executemany(
                "delete from tvaf_metadata where id = ?",
                [(id,) for id in ids])
        self._any_deleted = True

    def path_for_media_part(self, part):
        return os.path.join(
            self.yatfs_path, part.tracker.encode(), b"torrent", b"by-id",
            b"%d" % part.torrent_id, b"data", b"by-path", part.path)

    def sync_media_part(self, media_item_id, part):
        path = self.path_for_media_part(part)
        with self.db.conn:
            r = self.db.conn.cursor().execute(
                "select id from media_parts where deleted_at is null and "
                "media_item_id = ? and "
                "cast(file as blob) = ?", (media_item_id, path)).fetchone()
            if r:
                id, = r
            else:
                hash = hashlib.sha1(("%s:%s:%s" % (
                    part.tracker, part.torrent_id,
                    part.file_index)).encode()).hexdigest()
                open_subtitle_hash = hash[:16]
                self.db.conn.cursor().execute(
                    "insert into media_parts ("
                    "media_item_id, file, hash, open_subtitle_hash, size, "
                    "created_at, updated_at) "
                    "values (?, ?, ?, ?, ?, datetime('now', 'localtime'), "
                    "datetime(?, 'unixepoch', 'localtime'))",
                    (media_item_id, path, hash, open_subtitle_hash,
                        part.length, part.time))
                id = self.db.conn.last_insert_rowid()
                log().debug("added media part %d for %s", id, path)
            self.db.conn.cursor().execute(
                "update media_parts set \"index\" = ? where id = ?",
                (part.index, id))
            return id

    def sync_changes(self, changes):
        for guid, items in changes.guid_to_items.items():
            self.sync_guid_exclusive(guid, *items)
        for (tracker_name, torrent_id), items in (
                changes.tracker_torrent_id_to_items.items()):
            self.sync_torrent_exclusive(tracker_name, torrent_id, *items)
