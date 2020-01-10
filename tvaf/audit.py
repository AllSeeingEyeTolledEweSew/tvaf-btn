# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Request-auditing functions for tvaf."""

from __future__ import annotations

import time
from typing import Optional
from typing import Callable
from typing import Iterable
from typing import Union

import apsw
import intervaltree

import tvaf.app as app_lib
import tvaf.const as const
import tvaf.util as util
from tvaf.types import Audit
from tvaf.types import Request
from tvaf.types import TorrentStatus


def calculate_audits(
        old_status: Optional[TorrentStatus], new_status: TorrentStatus,
        get_requests: Callable[[], Iterable[Request]]) -> Iterable[Request]:
    """Calculate the audit records for a given change in torrent status.

    This function compares the piece_bitmap in the old and new TorrentStatus.
    For any pieces found to be newly-downloaded, it inspects the outstanding
    requests for the torrent, and picks a request to "blame" for the new piece.

    Since the common case is there are no new pieces downloaded, requests are
    supplied as a callback rather than requiring the caller to always retrieve
    them.

    Args:
        old_status: The prior TorrentStatus, or None.
        new_status: The new TorrentStatus.
        get_requests: A callback to retrieve the outstanding requests for this
            torrent. It must be sure to include deactivated requests.

    Returns:
        A list of new Audit records that reflect this change. The infohash,
            tracker and origin will all be set.
    """
    origin_to_audit = {}
    request_tree = None

    for piece, start, stop in util.enum_piecewise_ranges(
            new_status.piece_length, 0, new_status.length):
        # We care only about newly-downloaded pieces
        if not util.bitmap_is_set(new_status.piece_bitmap, piece):
            continue
        if old_status and util.bitmap_is_set(old_status.piece_bitmap, piece):
            continue

        # We just downloaded piece p. Now pick a request to blame for this
        # newly-downloaded piece, and add the size of this new piece to the
        # audit log for the user that initiated it.

        if request_tree is None:
            # Only query the requests if we have any new pieces.
            request_tree = intervaltree.IntervalTree()
            requests = get_requests()
            for req in requests:
                start_piece, stop_piece = util.range_to_pieces(
                    new_status.piece_length, req.start, req.stop)
                request_tree.addi(start_piece, stop_piece, req)

        reqs = [i.data for i in request_tree.at(piece)]

        # If we match multiple requests, the active, highest-priority and
        # newest one wins
        def key(req):
            return bool(req.deactivated_at), -req.priority, -req.time

        reqs = sorted(reqs, key=key)
        if reqs:
            blame = reqs[0]
            origin = blame.origin
            atime = blame.time
        else:
            # We know we downloaded a piece, but don't have any active requests
            # for it.
            origin = const.ORIGIN_UNKNOWN
            atime = int(time.time())

        if origin not in origin_to_audit:
            origin_to_audit[origin] = Audit(origin=origin,
                                            num_bytes=0,
                                            atime=0,
                                            infohash=new_status.infohash,
                                            tracker=new_status.tracker)

        audit = origin_to_audit[origin]

        audit.num_bytes += stop - start
        audit.atime = max(audit.atime, atime)

    return list(origin_to_audit.values())


class AuditService:
    """Audit functions for the tvaf app.

    Attributes:
        app: Our tvaf app instance.
    """

    def __init__(self, app: app_lib.App) -> None:
        self.app = app

    @property
    def db(self) -> apsw.Connection:
        """Returns our thread-local database connection."""
        return self.app.db.get()

    def create_schema(self) -> None:
        """Creates all tables and indexes in the database."""
        self.db.cursor().execute("create table if not exists audit ("
                                 "origin text not null, "
                                 "tracker text not null collate nocase, "
                                 "infohash text not null collate nocase, "
                                 "generation int not null, "
                                 "num_bytes int not null default 0, "
                                 "atime int not null default 0)")
        self.db.cursor().execute(
            "create unique index if not exists "
            "audit_on_tracker_infohash_origin_generation "
            "on audit (tracker, infohash, origin, generation)")

    def apply(self, *audits: Audit) -> None:
        """Apply a new audit record to the database.

        Each Audit record must have all key fields (origin, tracker, infohash,
        generation) set, and all data fields (num_bytes and atime) set.

        For each, the num_bytes will be added to any existing data. If the new
        atime is greater than the existing atime, it will be updated as well.

        Args:
            audits: A list of audit records to apply.
        """
        self.db.cursor().executemany(
            "insert or ignore into audit "
            "(origin, tracker, infohash, generation) values "
            "(?, ?, ?, ?)",
            [(a.origin, a.tracker, a.infohash, a.generation) for a in audits])
        self.db.cursor().executemany(
            "update audit set num_bytes = num_bytes + ?, "
            "atime = max(atime, ?) "
            "where origin = ? and tracker = ? and infohash = ? and "
            "generation = ?", [(a.num_bytes, a.atime, a.origin, a.tracker,
                                a.infohash, a.generation) for a in audits])

    def get(self, group_by: Iterable[str] = (),
            **where: Union[str, int]) -> Iterable[Audit]:
        """Get aggregate audit records.

        This function directly constructs a sql query using the arguments. For
        example, get(group_by=["origin"], tracker="foo") will construct a query
        like "SELECT SUM(num_bytes), MAX(atime) FROM audit WHERE tracker =
        "foo" GROUP BY origin".

        Args:
            group_by: A list of Audit key fields: origin, tracker, infohash,
                generation.
            where: A list of filters for key fields. origin, infohash and
                tracker are filtered as strings, and generation may be filtered
                as an int.

        Returns:
            A list of audit records.
        """
        group_by = [
            c for c in group_by
            if c in ("origin", "tracker", "infohash", "generation")
        ]
        select = [
            "coalesce(sum(num_bytes), 0) as num_bytes", "max(atime) as atime"
        ]
        select.extend(group_by)
        where_parts = []
        bindings = {}
        for key, value in where.items():
            if key not in ("origin", "tracker", "infohash", "generation"):
                continue
            if value is not None:
                select.append(key)
                where_parts.append(f"{key} = :{key}")
                bindings[key] = value
        select_clause = ",".join(select)
        query = f"select {select_clause} from audit"
        if where:
            query += " where " + " and ".join(where_parts)
        if group_by:
            query += " group by " + ",".join(group_by)
        audits = []
        cur = self.db.cursor().execute(query, bindings)
        for row in cur:
            row = dict(zip((n for n, t in cur.getdescription()), row))
            audits.append(Audit(**row))
        return audits

    def _calculate_one_torrent_locked(
            self, new_status: TorrentStatus) -> Iterable[Audit]:
        """Calculate Audit records for a new TorrentStatus.

        Given a new TorrentStatus, this function compares it to the
        TorrentStatus in the database as well as outstanding Requests, and
        calculates the Audit records that are generated by updating to the new
        TorrentStatus.

        This function should be called while the thread holds a write lock on
        the database.

        Args:
            new_status: The new, updated TorrentStatus.

        Returns:
            A list of Audit records generated by the change.
        """
        # Only record auditing for trackers we know about
        if not new_status.tracker:
            return []

        old_status = self.app.torrents.get_status(new_status.infohash)

        def get_requests() -> Iterable[Request]:
            return self.app.requests.get(infohash=new_status.infohash,
                                         include_deactivated=True)

        # Calculate the updated audit records
        audits = calculate_audits(old_status, new_status, get_requests)

        # Assign audit records to the current generation
        meta = self.app.torrents.get_meta(new_status.infohash)
        for audit in audits:
            audit.generation = meta.generation

        return audits

    def _calculate_locked(
            self, new_statuses: Iterable[TorrentStatus]) -> Iterable[Audit]:
        """Calculate Audit records for a list of new TorrentStatuses.

        Given a list of new TorrentStatuses, this function compares them to the
        TorrentStatuses in the database as well as outstanding Requests, and
        calculates the Audit records that are generated by updating to the new
        status.

        This function should be called while the thread holds a write lock on
        the database.

        Args:
            new_statuses: A list of new, updated TorrentStatuses.

        Returns:
            A list of Audit records generated by the change.
        """
        audits = []
        for new_status in new_statuses:
            audits.extend(self._calculate_one_torrent_locked(new_status))
        return audits

    def resolve_locked(self, new_statuses: Iterable[TorrentStatus]) -> None:
        """Update Audit records in the database given new TorrentStatuses.

        Given a list of new TorrentStatuses, this function compares them to the
        TorrentStatuses in the database as well as outstanding Requests. It
        will update the database to reflect the Audit data changes produced by
        this new data.

        This function should be called while the thread holds a write lock on
        the database.

        This should only be used by TorrentService.update.

        Args:
            new_statuses: A list of new, updated TorrentStatuses.
        """
        self.apply(*self._calculate_locked(new_statuses))
