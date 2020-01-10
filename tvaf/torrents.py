# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Torrent-level functions for tvaf."""

from __future__ import annotations

import dataclasses
import time
from typing import Optional
from typing import SupportsInt
from typing import Iterable

import apsw

import tvaf.app as app_lib
from tvaf.types import FileRef
from tvaf.types import TorrentStatus
from tvaf.types import TorrentMeta


class TorrentsService:
    """Provides torrent-level functions for the tvaf app.

    Attributes:
        app: The tvaf.app.App instance this service belongs to.
    """

    def __init__(self, app: app_lib.App) -> None:
        self.app = app

    @property
    def db(self) -> apsw.Connection:
        """Returns our thread-local database connection."""
        return self.app.db.get()

    def create_schema(self) -> None:
        """Creates torrent-level tables in the database."""
        self.db.cursor().execute("create table if not exists torrent_meta ("
                                 "infohash text primary key collate nocase, "
                                 "generation int not null default 0, "
                                 "managed bool not null default 0, "
                                 "atime int not null default 0)")
        self.db.cursor().execute("create table if not exists torrent_status ("
                                 "infohash text primary key collate nocase, "
                                 "tracker text not null collate nocase, "
                                 "piece_bitmap blob not null, "
                                 "piece_length int not null, "
                                 "length int not null, "
                                 "seeders int not null, "
                                 "leechers int not null, "
                                 "announce_message text)")
        self.db.cursor().execute("create table if not exists file ("
                                 "infohash text not null collate nocase, "
                                 "file_index int not null, "
                                 "path text not null, "
                                 "start int not null, "
                                 "stop int not null)")
        self._create_file_indexes()

    def _drop_file_indexes(self) -> None:
        """Drops the database indexes used by this service."""
        self.db.cursor().execute(
            "drop index if exists file_on_infohash_file_index")

    def _create_file_indexes(self) -> None:
        """Creates the database indexes used by this service."""
        self.db.cursor().execute("create unique index if not exists "
                                 "file_on_infohash_file_index "
                                 "on file (infohash, file_index)")

    def _resolve_added_locked(self, torrents: Iterable[TorrentStatus]) -> None:
        """Ensure torrent metadata is updated for new torrents.

        Precondition: the new infohashes have been added to the temporary table
        temp.present_infohashes in the database.

        Postcondition: The appropriate rows in the torrent_meta table will be
        in the database, and the generation column in torrent_meta will be
        appropriately updated.

        Args:
            torrents: A list of new tvaf.types.TorrentStatus just retrieved
                from the torrent client.
        """
        self._insert_meta_locked(*[t.infohash for t in torrents])
        # Bump the generation of each new torrent
        self.db.cursor().execute(
            "update torrent_meta set generation = generation + 1 "
            "where infohash in ("
            "select temp.present_infohashes.infohash "
            "from temp.present_infohashes "
            "left outer join torrent_status "
            "on temp.present_infohashes.infohash = torrent_status.infohash "
            "where torrent_status.infohash is null)")

    def _update_state_locked(self, torrents: Iterable[TorrentStatus]) -> None:
        """Update the torrent_status and file tables.

        Args:
            torrents: A list of new tvaf.types.TorrentStatus just retrieved
                from the torrent client.
        """
        self.db.cursor().execute("delete from torrent_status")
        self.db.cursor().execute("delete from file")

        if not torrents:
            return

        self._drop_file_indexes()

        torrent_datas = []
        file_datas = []
        for torrent in torrents:
            torrent_data = dataclasses.asdict(torrent)
            torrent_datas.append(torrent_data)
            for file_data in torrent_data.pop("files"):
                file_data["infohash"] = torrent.infohash
                file_datas.append(file_data)

        keys = sorted(torrent_datas[0].keys())
        columns = ",".join(keys)
        params = ",".join(":" + k for k in keys)
        self.db.cursor().executemany(
            f"insert into torrent_status ({columns}) values ({params})",
            torrent_datas)

        if file_datas:
            keys = sorted(file_datas[0].keys())
            columns = ",".join(keys)
            params = ",".join(":" + k for k in keys)
            self.db.cursor().executemany(
                f"insert into file ({columns}) values ({params})", file_datas)

        self._create_file_indexes()

    def _insert_meta_locked(self, *infohashes: str) -> None:
        """INSERT OR IGNORE into torrent_meta for the given infohashes."""
        self.db.cursor().executemany(
            "insert or ignore into torrent_meta (infohash) values (?)",
            [(i,) for i in infohashes])

    def mark_active(self,
                    infohash: str,
                    atime: Optional[SupportsInt] = None) -> None:
        """Mark the given infohash as active.

        The atime attribute on the corresponding TorrentMeta will be set to
        atime. If atime is not supplied, the current time will be used.

        Args:
            infohash: The infohash of the torrent to mark active.
            atime: The given time to use as the active time.
        """
        if atime is None:
            atime = time.time()
        atime = int(atime)
        with self.db:
            self._insert_meta_locked(infohash)
            self.db.cursor().execute(
                "update torrent_meta set atime = ? where infohash = ?",
                (atime, infohash))

    def manage(self, infohash: str) -> None:
        """Mark the given infohash as managed by tvaf.

        The managed attribute on the corresponding TorrentMeta will be set to
        True.

        Args:
            infohash: the infohash of the torrent to mark as managed.
        """
        with self.db:
            self._insert_meta_locked(infohash)
            self.db.cursor().execute(
                "update torrent_meta set managed = 1 where infohash = ?",
                (infohash,))

    def get_meta(self, infohash: str) -> Optional[TorrentMeta]:
        """Get TorrentMeta for the given infohash, or None if not found."""
        cur = self.db.cursor().execute(
            "select * from torrent_meta where infohash = ?", (infohash,))
        row = cur.fetchone()
        if not row:
            return None
        row = dict(zip((n for n, t in cur.getdescription()), row))
        for field in ("managed",):
            row[field] = bool(row[field])
        meta = TorrentMeta(**row)
        return meta

    def get_status(self, infohash: str) -> Optional[TorrentStatus]:
        """Get TorrentStatus for the given infohash, or None if not found."""
        with self.db:
            cur = self.db.cursor().execute(
                "select * from torrent_status where infohash = ?", (infohash,))
            row = cur.fetchone()
            if not row:
                return None
            row = dict(zip((n for n, t in cur.getdescription()), row))
            status = TorrentStatus(**row)
            status.files = []
            cur = self.db.cursor().execute(
                "select * from file where infohash = ? "
                "order by file_index", (infohash,))
            for row in cur:
                row = dict(zip((n for n, t in cur.getdescription()), row))
                row.pop("infohash")
                status.files.append(FileRef(**row))
        return status

    def update(self,
               torrents: Iterable[TorrentStatus],
               skip_audit: bool = False) -> None:
        """Update the database to reflect new TorrentStatus values.

        The TorrentStatus available will be updated to exactly reflect the
        torrents list given. A torrent not present in the torrents list will be
        considered deleted.

        If a torrent wasn't in the database prior to calling update, but is
        present in the torrents list, its TorrentMeta.generation field will be
        incremented.

        Additionally, the available Audit records will be updated, unless
        the caller supplies skip_audit=True. If a torrent was in the database
        prior to calling update, this function will compare the old
        piece_bitmap to the new one, and any new pieces will be considered
        newly-downloaded for updating the Audit records. Otherwise, all
        existing pieces will be considered new.

        Args:
            torrents: The list of TorrentStatus representing all currently
                active torrents.
            skip_audit: If True, the Audit records will not be updated. Only
                useful for testing.
        """
        with self.db:
            self.db.cursor().execute(
                "create temporary table present_infohashes "
                "(infohash text primary key collate nocase)")
            try:
                self.db.cursor().executemany(
                    "insert into temp.present_infohashes "
                    "(infohash) values (?)", [(t.infohash,) for t in torrents])
                self._resolve_added_locked(torrents)
                if not skip_audit:
                    self.app.audit.resolve_locked(torrents)
                self._update_state_locked(torrents)
            finally:
                self.db.cursor().execute("drop table temp.present_infohashes")
