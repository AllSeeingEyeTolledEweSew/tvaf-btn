"""Data access functions for tvaf."""

import time
from typing import Optional
from typing import Union
from typing import SupportsInt
from typing import Callable
from typing import Iterable
from typing import List
from typing import Any
from typing import Dict
import dataclasses

import apsw
import intervaltree

from tvaf import const
from tvaf import db
import tvaf.exceptions as exc_lib
from tvaf import util
from tvaf.types import Request
from tvaf.types import RequestStatus
from tvaf.types import Audit
from tvaf.types import TorrentStatus
from tvaf.types import TorrentMeta
from tvaf.types import FileRef


def create_schema(conn: apsw.Connection) -> None:
    """Creates all tables and indexes in the database."""
    conn.cursor().execute("create table if not exists request ("
                          "request_id integer primary key autoincrement, "
                          "tracker text not null, "
                          "infohash text not null collate nocase, "
                          "start int not null, "
                          "stop int not null, "
                          "origin text not null, "
                          "random bool not null default 0, "
                          "readahead bool not null default 0, "
                          "priority int not null, "
                          "time int not null, "
                          "deactivated_at int)")
    conn.cursor().execute("create index if not exists request_on_infohash "
                          "on request (infohash)")

    conn.cursor().execute("create table if not exists torrent_meta ("
                          "infohash text primary key collate nocase, "
                          "generation int not null default 0, "
                          "managed bool not null default 0, "
                          "atime int not null default 0)")
    conn.cursor().execute("create table if not exists torrent_status ("
                          "infohash text primary key collate nocase, "
                          "tracker text not null collate nocase, "
                          "piece_bitmap blob not null, "
                          "piece_length int not null, "
                          "length int not null, "
                          "seeders int not null, "
                          "leechers int not null, "
                          "announce_message text)")
    conn.cursor().execute("create table if not exists file ("
                          "infohash text not null collate nocase, "
                          "file_index int not null, "
                          "path text not null, "
                          "start int not null, "
                          "stop int not null)")
    _create_file_indexes(conn)

    conn.cursor().execute("create table if not exists audit ("
                          "origin text not null, "
                          "tracker text not null collate nocase, "
                          "infohash text not null collate nocase, "
                          "generation int not null, "
                          "num_bytes int not null default 0, "
                          "atime int not null default 0)")
    conn.cursor().execute("create unique index if not exists "
                          "audit_on_tracker_infohash_origin_generation "
                          "on audit (tracker, infohash, origin, generation)")


def _drop_file_indexes(conn: apsw.Connection) -> None:
    """Drops the database indexes used by this service."""
    conn.cursor().execute("drop index if exists file_on_infohash_file_index")


def _create_file_indexes(conn: apsw.Connection) -> None:
    """Creates the database indexes used by this service."""
    conn.cursor().execute("create unique index if not exists "
                          "file_on_infohash_file_index "
                          "on file (infohash, file_index)")


def get_request_status(conn: apsw.Connection, req: Request) -> RequestStatus:
    """Get the status of the sequentially-available data for a Request.

    "The sequentially-available data" means the first contiguous chunk of
    available data aligned with the start of the request.

    The Request must have at least the start, stop and infohash fields set.
    All other fields are ignored.

    Torrent data is made available by writing it to the filesystem on the
    local machine. The returned RequestStatus tells the caller where to
    find that data.

    Note though that there is a race condition against torrents being
    deleted after the RequestStatus is returned. The caller should check
    against FileNotFoundError / ENOENT when reading the referenced files.

    Getting the status of a Request is independent of submitting it to tvaf
    via add().

    Args:
        conn: A database connection.
        req: The Request to poll.

    Returns:
        A RequestStatus representing where to find the data referenced in
            the given Request.

    Raises:
        exc_lib.BadRequest: If stop <= start, or start < 0.
    """
    req.validate()

    status = RequestStatus(progress=0, progress_percent=0, files=[])

    torrent = get_torrent_status(conn, req.infohash)
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


def get_requests(conn: apsw.Connection,
                 *,
                 request_id: Optional[int] = None,
                 infohash: Optional[str] = None,
                 include_deactivated: bool = False) -> Iterable[Request]:
    """Get requests in the database.

    This will search for Requests currently in the database.

    Args:
        conn: A database connection.
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
    cur = conn.cursor()
    cur.execute(query, bindings)
    requests = []
    for row in cur:
        row = dict(zip((n for n, t in cur.getdescription()), row))
        for field in ("random", "readahead"):
            row[field] = bool(row[field])
        requests.append(Request(**row))
    return requests


def get_meta(conn: apsw.Connection, infohash: str) -> Optional[TorrentMeta]:
    """Returns TorrentMeta for a given infohash, or None if not found."""
    cur = conn.cursor().execute("select * from torrent_meta where infohash = ?",
                                (infohash,))
    row = cur.fetchone()
    if not row:
        return None
    row = dict(zip((n for n, t in cur.getdescription()), row))
    for field in ("managed",):
        row[field] = bool(row[field])
    meta = TorrentMeta(**row)
    return meta


def get_torrent_status(conn: apsw.Connection,
                       infohash: str) -> Optional[TorrentStatus]:
    """Returns TorrentStatus for a given infohash, or None if not found."""
    with conn:
        cur = conn.cursor().execute(
            "select * from torrent_status where infohash = ?", (infohash,))
        row = cur.fetchone()
        if not row:
            return None
        row = dict(zip((n for n, t in cur.getdescription()), row))
        status = TorrentStatus(**row)
        status.files = []
        cur = conn.cursor().execute(
            "select * from file where infohash = ? "
            "order by file_index", (infohash,))
        for row in cur:
            row = dict(zip((n for n, t in cur.getdescription()), row))
            row.pop("infohash")
            status.files.append(FileRef(**row))
    return status


def get_audits(conn: apsw.Connection,
               *,
               group_by: Iterable[str] = (),
               **where: Union[str, int]) -> Iterable[Audit]:
    """Get aggregate audit records.

    This function directly constructs a sql query using the arguments. For
    example, get(group_by=["origin"], tracker="foo") will construct a query
    like "SELECT SUM(num_bytes), MAX(atime) FROM audit WHERE tracker =
    "foo" GROUP BY origin".

    Args:
        conn: A database connection.
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
    select = ["coalesce(sum(num_bytes), 0) as num_bytes", "max(atime) as atime"]
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
    cur = conn.cursor().execute(query, bindings)
    for row in cur:
        row = dict(zip((n for n, t in cur.getdescription()), row))
        audits.append(Audit(**row))
    return audits


def add_request(conn: apsw.Connection, req: Request) -> Request:
    """Adds a request to tvaf.

    The tracker, infohash, origin, start and stop fields must be set on
    the Request.

    If the priority field isn't set, the default of const.DEFAULT_PRIORITY
    will be used.

    If the Request is already fully fulfilled, it will not be added to the
    tvaf's database, and will be returned with the id field unset.

    Otherwise, the Request will be added to the database. Tvaf will attempt
    to download the referenced data, and will make the data available later
    via get_status().

    Returns:
        The input Request, modified in-place as described above.

    Args:
        conn: A database connection.
        req: A Request to add.

    Raises:
        exc_lib.BadRequest: If the required fields are not set, or if the
            Request does not satisfy 0 <= start < stop.
    """
    req.validate()

    if not req.priority:
        req.priority = const.DEFAULT_PRIORITY
    if not req.origin:
        raise exc_lib.BadRequest("origin must be set")
    if not req.tracker:
        raise exc_lib.BadRequest("tracker must be set")
    if not req.infohash:
        raise exc_lib.BadRequest("infohash must be set")

    req.time = int(time.time())
    req.deactivated_at = None

    with db.begin(conn):
        mark_torrent_active(conn, req.infohash, atime=req.time)

        if get_request_status(conn, req).progress_percent == 1.0:
            return req

        row = dataclasses.asdict(req)
        if "id" in row:
            del row["id"]
        for k in ("random", "readahead"):
            row[k] = bool(row[k])
        keys = sorted(row.keys())
        columns = ",".join(keys)
        params = ",".join(":" + k for k in keys)
        conn.cursor().execute(
            f"insert into request ({columns}) values ({params})", row)
        req.request_id = conn.last_insert_rowid()

    return req


def deactivate_request(conn: apsw.Connection, request_id: int) -> bool:
    """Deactivate a Request in the database.

    A deactivated Request isn't immediately deleted from the database, but
    is just set to deactivated. Tvaf will no longer try to download the
    data for the Request. The Request will be kept in the database for some
    time, in order to generate correct Audit records.

    Args:
        conn: A database connection.
        request_id: The id of the request to delete.

    Returns:
        True if the Request was deactivated, and had not yet been
            deactivated.
    """
    deactivated_at = int(time.time())
    conn.cursor().execute(
        "update request set deactivated_at = ? "
        "where request_id = ? and deactivated_at is null",
        (deactivated_at, request_id))
    return bool(conn.changes())


def _insert_meta_locked(conn: apsw.Connection, *infohashes: str) -> None:
    """INSERT OR IGNORE into torrent_meta for the given infohashes."""
    conn.cursor().executemany(
        "insert or ignore into torrent_meta (infohash) values (?)",
        [(i,) for i in infohashes])


def mark_torrent_active(conn: apsw.Connection,
                        infohash: str,
                        atime: Optional[SupportsInt] = None) -> None:
    """Mark the given infohash as active.

    The atime attribute on the corresponding TorrentMeta will be set to
    atime. If atime is not supplied, the current time will be used.

    Args:
        conn: A database connection.
        infohash: The infohash of the torrent to mark active.
        atime: The given time to use as the active time.
    """
    if atime is None:
        atime = time.time()
    atime = int(atime)
    with conn:
        _insert_meta_locked(conn, infohash)
        conn.cursor().execute(
            "update torrent_meta set atime = ? where infohash = ?",
            (atime, infohash))


def manage_torrent(conn: apsw.Connection, infohash: str) -> None:
    """Mark the given infohash as managed by tvaf.

    The managed attribute on the corresponding TorrentMeta will be set to
    True.

    Args:
        conn: A database connection.
        infohash: the infohash of the torrent to mark as managed.
    """
    with conn:
        _insert_meta_locked(conn, infohash)
        conn.cursor().execute(
            "update torrent_meta set managed = 1 where infohash = ?",
            (infohash,))


def apply_audits(conn: apsw.Connection, *audits: Audit) -> None:
    """Apply a new audit record to the database.

    Each Audit record must have all key fields (origin, tracker, infohash,
    generation) set, and all data fields (num_bytes and atime) set.

    For each, the num_bytes will be added to any existing data. If the new
    atime is greater than the existing atime, it will be updated as well.

    Args:
        conn: A database connection.
        audits: A list of audit records to apply.
    """
    conn.cursor().executemany(
        "insert or ignore into audit "
        "(origin, tracker, infohash, generation) values "
        "(?, ?, ?, ?)",
        [(a.origin, a.tracker, a.infohash, a.generation) for a in audits])
    conn.cursor().executemany(
        "update audit set num_bytes = num_bytes + ?, "
        "atime = max(atime, ?) "
        "where origin = ? and tracker = ? and infohash = ? and "
        "generation = ?",
        [(a.num_bytes, a.atime, a.origin, a.tracker, a.infohash, a.generation)
         for a in audits])


def calculate_audits(
        old_status: Optional[TorrentStatus], new_status: TorrentStatus,
        get_requests_: Callable[[], Iterable[Request]]) -> Iterable[Audit]:
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
        get_requests_: A callback to retrieve the outstanding requests for this
            torrent. It must be sure to include deactivated requests.

    Returns:
        A list of new Audit records that reflect this change. The infohash,
            tracker and origin will all be set.
    """
    origin_to_audit: Dict[str, Audit] = {}
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
            requests = get_requests_()
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


def _calculate_one_torrent_locked(conn: apsw.Connection,
                                  new_status: TorrentStatus) -> Iterable[Audit]:
    """Calculate Audit records for a new TorrentStatus.

    Given a new TorrentStatus, this function compares it to the
    TorrentStatus in the database as well as outstanding Requests, and
    calculates the Audit records that are generated by updating to the new
    TorrentStatus.

    This function should be called while the thread holds a write lock on
    the database.

    Args:
        conn: A database connection.
        new_status: The new, updated TorrentStatus.

    Returns:
        A list of Audit records generated by the change.
    """
    # Only record auditing for trackers we know about
    if not new_status.tracker:
        return []

    old_status = get_torrent_status(conn, new_status.infohash)

    def get_requests_() -> Iterable[Request]:
        return get_requests(conn,
                            infohash=new_status.infohash,
                            include_deactivated=True)

    # Calculate the updated audit records
    audits = calculate_audits(old_status, new_status, get_requests_)

    # Assign audit records to the current generation
    meta = get_meta(conn, new_status.infohash)
    # We should've already INSERT OR IGNORE'd the row by now
    assert meta is not None
    for audit in audits:
        audit.generation = meta.generation

    return audits


def _resolve_added_locked(conn: apsw.Connection,
                          torrents: Iterable[TorrentStatus]) -> None:
    """Ensure torrent metadata is updated for new torrents.

    Precondition: the new infohashes have been added to the temporary table
    temp.present_infohashes in the database.

    Postcondition: The appropriate rows in the torrent_meta table will be
    in the database, and the generation column in torrent_meta will be
    appropriately updated.

    Args:
        conn: A database connection.
        torrents: A list of new tvaf.types.TorrentStatus just retrieved
            from the torrent client.
    """
    infohashes = [t.infohash for t in torrents]
    _insert_meta_locked(conn, *infohashes)
    # Bump the generation of each new torrent
    conn.cursor().execute(
        "update torrent_meta set generation = generation + 1 "
        "where infohash in ("
        "select temp.present_infohashes.infohash "
        "from temp.present_infohashes "
        "left outer join torrent_status "
        "on temp.present_infohashes.infohash = torrent_status.infohash "
        "where torrent_status.infohash is null)")


def _update_state_locked(conn: apsw.Connection,
                         torrents: Iterable[TorrentStatus]) -> None:
    """Update the torrent_status and file tables.

    Args:
        conn: A database connection.
        torrents: A list of new tvaf.types.TorrentStatus just retrieved
            from the torrent client.
    """
    conn.cursor().execute("delete from torrent_status")
    conn.cursor().execute("delete from file")

    if not torrents:
        return

    _drop_file_indexes(conn)

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
    conn.cursor().executemany(
        f"insert into torrent_status ({columns}) values ({params})",
        torrent_datas)

    if file_datas:
        keys = sorted(file_datas[0].keys())
        columns = ",".join(keys)
        params = ",".join(":" + k for k in keys)
        conn.cursor().executemany(
            f"insert into file ({columns}) values ({params})", file_datas)

    _create_file_indexes(conn)


def _resolve_audits_locked(conn: apsw.Connection,
                           new_statuses: Iterable[TorrentStatus]) -> None:
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
    audits: List[Audit] = []
    for new_status in new_statuses:
        audits.extend(_calculate_one_torrent_locked(conn, new_status))
    apply_audits(conn, *audits)


def update_torrent_status(conn: apsw.Connection,
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
        conn: A database connection.
        torrents: The list of TorrentStatus representing all currently
            active torrents.
        skip_audit: If True, the Audit records will not be updated. Only
            useful for testing.
    """
    with conn:
        conn.cursor().execute("create temporary table present_infohashes "
                              "(infohash text primary key collate nocase)")
        try:
            conn.cursor().executemany(
                "insert into temp.present_infohashes "
                "(infohash) values (?)", [(t.infohash,) for t in torrents])
            _resolve_added_locked(conn, torrents)
            if not skip_audit:
                _resolve_audits_locked(conn, torrents)
            _update_state_locked(conn, torrents)
        finally:
            conn.cursor().execute("drop table temp.present_infohashes")
