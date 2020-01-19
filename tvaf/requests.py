# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Request-level functions for tvaf."""

from __future__ import annotations

import dataclasses
import time
from typing import Optional
from typing import Iterable
from typing import List
from typing import Any

import apsw

import tvaf.app as app_lib
import tvaf.const as const
import tvaf.exceptions as exc_lib
import tvaf.util as util
from tvaf.types import FileRef
from tvaf.types import Request
from tvaf.types import RequestStatus


class RequestsService:
    """Request-level functions for the tvaf app.

    RequestsService is the main point of contact to access torrent data from
    tvaf. Requests can be submitted via add(), and tvaf will try to download
    the data.

    You can poll for available data using get_status(). A Request doesn't need
    to be submitted via add() before you poll its status.

    Attributes:
        app: Our tvaf app instance.
    """

    EXPIRE_TIME = 3600

    def __init__(self, app: app_lib.App) -> None:
        self.app = app

    @property
    def db(self) -> apsw.Connection:
        """Returns our thread-local database connection."""
        return self.app.db.get()

    def create_schema(self) -> None:
        """Creates all tables and indexes in the database."""
        self.db.cursor().execute(
            "create table if not exists request ("
            "request_id integer primary key autoincrement, "
            "tracker text not null, "
            "torrent_id text not null, "
            "infohash text not null collate nocase, "
            "start int not null, "
            "stop int not null, "
            "origin text not null, "
            "random bool not null default 0, "
            "readahead bool not null default 0, "
            "priority int not null, "
            "time int not null, "
            "deactivated_at int)")
        self.db.cursor().execute(
            "create index if not exists request_on_infohash "
            "on request (infohash)")

    def _deactivate_fulfilled_locked(self) -> None:
        deactivate_requests = []
        cur = self.db.cursor().execute(
            "select torrent.piece_length, torrent.piece_bitmap, request.id, "
            "request.start, request.stop "
            "from torrent "
            "inner join request on request.infohash = torrent.infohash "
            "where (not request.deactivated_at) and torrent.present")
        for row in cur:
            piece_length, piece_bitmap, request_id, start, stop = row
            fulfilled = all(
                util.iter_piece_is_set(piece_bitmap, piece_length, start, stop))
            if fulfilled:
                deactivate_requests.append(request_id)
        if deactivate_requests:
            now = int(time.time())
            self.db.cursor().execute(
                "update request set active = 0, deactivated = ? where id = ?",
                [(now, id) for id in deactivate_requests])

    def _delete_expired_requests_locked(self) -> None:
        expire = int(time.time()) - self.EXPIRE_TIME
        self.db.cursor().execute(
            "delete from request "
            "where deactivated_at is not null and deactivated_at < ?",
            (expire,))

    def get_status(self, req: Request) -> RequestStatus:
        """Get the status of the sequentially-available data for a Request.

        "The sequentially-available data" means the first contiguous chunk of
        available data aligned with the start of the request.

        The Request must have at least the start and stop fields set. Either
        infohash or both tracker and torrent_id should be set. All other fields
        are ignored.

        Torrent data is made available by writing it to the filesystem on the
        local machine. The returned RequestStatus tells the caller where to
        find that data.

        Note though that there is a race condition against torrents being
        deleted after the RequestStatus is returned. The caller should check
        against FileNotFoundError / ENOENT when reading the referenced files.

        Getting the status of a Request is independent of submitting it to tvaf
        via add().

        Args:
            req: The Request to poll.

        Returns:
            A RequestStatus representing where to find the data referenced in
                the given Request.

        Raises:
            exc_lib.TrackerNotFound: If the request was specified by
                tracker, but the tracker is unknown to tvaf.
            exc_lib.TorrentEntryNotFound: If the request refers to a
                TorrentEntry unknown to tvaf.
            exc_lib.BadRequest: If stop <= start, or start < 0, or either
                start or stop are beyond the length of the TorrentEntry
                referenced by this request.
        """
        self._validate(req)

        status = RequestStatus(progress=0, progress_percent=0, files=[])

        torrent = self.app.torrents.get_status(req.infohash)
        if not torrent:
            return status

        # We only care about the first contiguous available chunk of data.
        for piece, start, stop in util.enum_piecewise_ranges(
                torrent.piece_length, req.start, req.stop):
            is_set = util.bitmap_is_set(torrent.piece_bitmap, piece)
            if is_set and start == req.start + status.progress:
                status.progress += stop - start
            else:
                break

        status.progress_percent = status.progress / (req.stop - req.start)

        # Figure out the appropriate FileRefs that match the first contiguous
        # available chunk of data.
        offset_to_file = 0
        files = []
        for fileref in torrent.files:
            if offset_to_file >= status.progress:
                break

            start = req.start - offset_to_file
            if start < fileref.start:
                start = fileref.start
            if start < fileref.stop:
                stop = status.progress
                if stop > fileref.stop:
                    stop = fileref.stop
                files.append(
                    FileRef(file_index=fileref.file_index,
                            path=fileref.path,
                            start=start,
                            stop=stop))
            offset_to_file += fileref.stop - fileref.start

        status.files = files

        return status

    def _validate(self, req: Request) -> None:
        """Validate a request.

        This function ensures that either infohash, or both tracker and
        torrent_id, are set on the Request. If tracker/torrent_id are used, the
        infohash will be overwritten.

        If the Request doesn't refer to a known TorrentEntry, a BadRequest (or
        subclass) will be raised.

        This also validates that 0 <= start < stop <= the length of the
        torrent.

        Args:
            req: A Request to validate.

        Raises:
            exc_lib.TorrentEntryNotFound: If the Request refers to a
                TorrentEntry unknown to tvaf.
            exc_lib.TrackerNotfound: If the Request refers to a tracker unknown
                to tvaf.
            exc_lib.BadRequest: If TorrentEntry-referencing fields are not
                supplied, or if the Request does not satisfy 0 <= start < stop
                <= the length of the TorrentEntry.
        """
        if req.tracker and req.torrent_id:
            torrent_entry = self.app.trackers.get(
                req.tracker).get_torrent_entry(req.torrent_id)
            req.infohash = torrent_entry.infohash
        elif req.infohash:
            torrent_entry = self.app.trackers.get_torrent_entry(
                infohash=req.infohash)
        else:
            raise exc_lib.BadRequest(
                "either infohash or tracker and torrent_id must be supplied")

        if req.start >= torrent_entry.length:
            raise exc_lib.BadRequest("start >= torrent length")
        if req.stop > torrent_entry.length:
            raise exc_lib.BadRequest("stop > torrent length")

        if req.start < 0:
            raise exc_lib.BadRequest("start < 0")
        if req.stop <= req.start:
            raise exc_lib.BadRequest("stop <= start")

    def add(self, req: Request) -> Request:
        """Adds a request to tvaf.

        The tracker, torrent_id, origin, start and stop fields must be set on
        the Request.

        If the priority field isn't set, the default of const.DEFAULT_PRIORITY
        will be used.

        This function will look up the referenced TorrentEntry, and will
        overwrite the infohash field.

        If the Request doesn't refer to a known TorrentEntry, a
        exc_lib.TrackerNotFound or exc_lib.TorrentEntryNotFound will be raised.

        If the Request is already fully fulfilled, it will not be added to the
        tvaf's database, and will be returned with the id field unset.

        Otherwise, the Request will be added to the database. Tvaf will attempt
        to download the referenced data, and will make the data available later
        via get_status().

        Returns:
            The input Request, modified in-place as described above.

        Args:
            req: A Request to add.

        Raises:
            exc_lib.TorrentEntryNotFound: If the Request refers to a
                TorrentEntry unknown to tvaf.
            exc_lib.TrackerNotfound: If the Request refers to a tracker unknown
                to tvaf.
            exc_lib.BadRequest: If torrent_id and tracker are not set, or if
                origin is not set, or if the Request does not satisfy 0 <=
                start < stop <= the length of the TorrentEntry.
        """
        self._validate(req)

        if not req.priority:
            req.priority = const.DEFAULT_PRIORITY
        if not req.origin:
            raise exc_lib.BadRequest("origin must be set")
        if not (req.tracker and req.torrent_id):
            raise exc_lib.BadRequest("tracker and torrent_id must be set")

        req.time = int(time.time())
        req.deactivated_at = None

        with self.app.db.begin():
            self.app.torrents.mark_active(req.infohash, atime=req.time)

            if self.get_status(req).progress_percent == 1.0:
                return req

            row = dataclasses.asdict(req)
            if "id" in row:
                del row["id"]
            for k in ("random", "readahead"):
                row[k] = bool(row[k])
            keys = sorted(row.keys())
            columns = ",".join(keys)
            params = ",".join(":" + k for k in keys)
            self.db.cursor().execute(
                f"insert into request ({columns}) values ({params})", row)
            req.request_id = self.db.last_insert_rowid()

        return req

    def get(self,
            request_id: Optional[int] = None,
            infohash: Optional[str] = None,
            include_deactivated: bool = False) -> Iterable[Request]:
        """Get requests in the database.

        This will search for Requests currently in the database.

        Args:
            request_id: If supplied, search requests by id.
            infohash: If supplied, search requests by infohash.
            include_deactivated: Include deactivated requests in the search
                results.

        Returns:
            A list of requests.
        """
        clauses = []
        bindings: List[Any] = []
        if infohash is not None:
            clauses.append("infohash = ?")
            bindings.append(infohash)
        if request_id is not None:
            clauses.append("request_id = ?")
            bindings.append(request_id)
        if not include_deactivated:
            clauses.append("deactivated_at is null")
        query = "select * from request"
        if clauses:
            query += " where " + " and ".join(clauses)
        cur = self.db.cursor()
        cur.execute(query, bindings)
        requests = []
        for row in cur:
            row = dict(zip((n for n, t in cur.getdescription()), row))
            for field in ("random", "readahead"):
                row[field] = bool(row[field])
            requests.append(Request(**row))
        return requests

    def deactivate(self, request_id: int) -> bool:
        """Deactivate a Request in the database.

        A deactivated Request isn't immediately deleted from the database, but
        is just set to deactivated. Tvaf will no longer try to download the
        data for the Request. The Request will be kept in the database for some
        time, in order to generate correct Audit records.

        Args:
            request_id: The id of the request to delete.

        Returns:
            True if the Request was deactivated, and had not yet been
                deactivated.
        """
        deactivated_at = int(time.time())
        self.db.cursor().execute(
            "update request set deactivated_at = ? "
            "where request_id = ? and deactivated_at is null",
            (deactivated_at, request_id))
        return bool(self.db.changes())
