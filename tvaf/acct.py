# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
# pylint: skip-file


def create_schema(conn: apsw.Connection) -> None:
    """Creates all tables and indexes in the database."""
    conn.cursor().execute("create table if not exists torrent_meta ("
                          "infohash text primary key collate nocase, "
                          "generation int not null default 0, "
                          "managed bool not null default 0, "
                          "atime int not null default 0)")

    conn.cursor().execute("create table if not exists acct ("
                          "origin text not null, "
                          "tracker text not null collate nocase, "
                          "infohash text not null collate nocase, "
                          "generation int not null, "
                          "num_bytes int not null default 0, "
                          "atime int not null default 0)")
    conn.cursor().execute("create unique index if not exists "
                          "acct_on_tracker_infohash_origin_generation "
                          "on acct (tracker, infohash, origin, generation)")


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


def get_acct(conn: apsw.Connection,
             *,
             group_by: Iterable[str] = (),
             **where: Union[str, int]) -> Iterable[Acct]:
    """Get aggregate Acct records.

    This function directly constructs a sql query using the arguments. For
    example, get(group_by=["origin"], tracker="foo") will construct a query
    like "SELECT SUM(num_bytes), MAX(atime) FROM audit WHERE tracker =
    "foo" GROUP BY origin".

    Args:
        conn: A database connection.
        group_by: A list of Acct key fields: origin, tracker, infohash,
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
        audits.append(Acct(**row))
    return audits
