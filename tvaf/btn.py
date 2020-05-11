# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""BTN support for TVAF."""

import errno
import os
import stat as stat_lib
from typing import Any
from typing import Iterator

import apsw
import btn as btn_lib

from tvaf import fs
from tvaf.config import Config
from tvaf.exceptions import Error


def get_api(config: Config) -> btn_lib.API:
    return btn_lib.API(cache_path=config.btn_save_path)


def fetch(config: Config, infohash: str) -> bytes:
    api = get_api(config)
    r = api.db.cursor().execute(
        "select id from torrent_entry where infohash = ?",
        (infohash,)).fetchone()
    if not r:
        raise Error(f"{infohash} not found on btn", 404)
    torrent_id = r[0]
    torrent_entry = api.getTorrentEntryByIdCached(torrent_id)
    try:
        return torrent_entry.get_raw_torrent()
    except btn_lib.HTTPError as e:
        raise Error(e.message, e.code, details=e.details)


def _mkoserror(code: int, *args: Any):
    """Returns OSError with a proper error message."""
    return OSError(code, os.strerror(code), *args)


def _slash_variations(name: str) -> Iterator[str]:
    """Yields name variations to reverse slash-mangling.

    On BTN, many series and group names have "/" characters. When naming a
    directory after a series, We replace the "/" with "_", so "Nip/Tuck"
    becomes "Nip_Tuck".

    When looking up a series by a mangled name, we need to figure out what name
    we originally meant.

    This function yields every combination of replacing a "_" with a "/", so a
    lookup function can try all possible variations.

    Since this approach is exponential, we'll only try to replace 5 "_"
    characters. In practice, I have only seen up to 4 "_" or "/" characters in
    a group or series name on BTN.

    Args:
        name: A name to unmangle.

    Yields:
        Variations of name, with "_" characters replaced by "/".
    """
    indexes = []
    for index, char in enumerate(name):
        if char == "_":
            indexes.append(index)
    count = min(2**len(indexes), 32)
    for bitmap in range(count):
        value = name
        for bit, index in enumerate(indexes):
            if bitmap & (1 << bit):
                value = value[:index] + "/" + value[index + 1:]
        yield value


class RootDir(fs.StaticDir):
    """The root directory of the BTN VFS.

    Contains:
        browse/<series>/<group>/path/to/files.

    Attributes:
        db: A connection to the btn metadata database.
    """

    def __init__(self, db: apsw.Connection):
        super().__init__()
        self.mkchild("browse", BrowseDir(db))


class BrowseDir(fs.Dir):
    """The /browse directory of the BTN VFS.

    Attributes:
        db: A connection to the btn metadata database.
    """

    def __init__(self, db: apsw.Connection):
        super().__init__()
        self.db = db

    def readdir(self, offset: int = 0) -> Iterator[fs.Dirent]:
        if offset == 0:
            offset = -1
        cur = self.db.cursor().execute(
            "select id, name from series where id > ? and not deleted "
            "order by id", (offset,))
        for series_id, name in cur:
            if not name:
                continue
            name = name.replace("/", "_")
            yield fs.Dirent(name=name,
                            next_offset=series_id,
                            stat=fs.Dir().stat())

    def lookup(self, name: str) -> fs.Node:
        for candidate in _slash_variations(name):
            row = self.db.cursor().execute(
                "select id from series where name = ? and not deleted",
                (candidate,)).fetchone()
            if row:
                series_id = row[0]
                return SeriesBrowseDir(self.db, series_id)
        raise _mkoserror(errno.ENOENT, name)


class SeriesBrowseDir(fs.Dir):
    """Represents browse/<series>.

    Attributes:
        db: A connection to the btn metadata database.
        series_id: The unique id of the series.
    """

    def __init__(self, db: apsw.Connection, series_id: int) -> None:
        super().__init__()
        self.db = db
        self.series_id = series_id

    def readdir(self, offset: int = 0) -> Iterator[fs.Dirent]:
        if offset == 0:
            offset = -1
        cur = self.db.cursor().execute(
            "select id, name from torrent_entry_group "
            "where id > ? and series_id = ? and not deleted order by id",
            (offset, self.series_id))
        for group_id, name in cur:
            if not name:
                continue
            name = name.replace("/", "_")
            yield fs.Dirent(name=name,
                            next_offset=group_id,
                            stat=fs.Dir().stat())

    def lookup(self, name: str) -> fs.Node:
        for candidate in _slash_variations(name):
            row = self.db.cursor().execute(
                "select id from torrent_entry_group "
                "where name = ? and series_id = ? and not deleted",
                (candidate, self.series_id)).fetchone()
            if row:
                group_id = row[0]
                return GroupBrowseSubdir(self.db, group_id, "")
        raise _mkoserror(errno.ENOENT, name)


class GroupBrowseSubdir(fs.Dir):
    """Represents browse/<series>/<group>/<path>, where path may be empty.

    Attributes:
        db: A connection to the btn metadata database.
        group_id: The id of the group.
        prefix: The path prefix. May be empty.
    """

    def __init__(self, db: apsw.Connection, group_id: int, prefix: str):
        super().__init__()
        self.db = db
        self.group_id = group_id
        self.prefix = prefix

    def readdir(self, offset: int = 0) -> Iterator[fs.Dirent]:
        cur = self.db.cursor()
        if not self.prefix:
            strip = 0
            cur.execute(
                "select file_info.path, file_info.stop - file_info.start, "
                "torrent_entry.time "
                "from file_info "
                "inner join torrent_entry "
                "where file_info.id = torrent_entry.id and "
                "not torrent_entry.deleted and "
                "torrent_entry.group_id = ? "
                "order by file_info.path limit -1 offset ?",
                (self.group_id, offset))
        else:
            strip = len(self.prefix) + 1
            lo_bytes = (self.prefix + "/").encode("utf-8", "surrogateescape")
            hi_bytes = (self.prefix + "0").encode("utf-8", "surrogateescape")
            cur.execute(
                "select file_info.path, file_info.stop - file_info.start, "
                "torrent_entry.time "
                "from file_info "
                "inner join torrent_entry "
                "where file_info.id = torrent_entry.id and "
                "not torrent_entry.deleted and "
                "torrent_entry.group_id = ? "
                "and file_info.path > ? and file_info.path < ? "
                "order by file_info.path "
                "limit -1 offset ?",
                (self.group_id, lo_bytes, hi_bytes, offset))
        prev_name, prev_stat = None, None
        index = 0
        for index, (path, length, mtime) in enumerate(cur):
            path = path.decode("utf-8", "surrogateescape")
            tail = path[strip:].split("/")
            name = tail[0]
            if (name != prev_name and prev_name is not None and
                    prev_stat is not None):
                yield fs.Dirent(name=prev_name,
                                stat=stat,
                                next_offset=index + offset)
            if len(tail) == 1:
                stat = fs.Stat(size=length,
                               mtime=mtime,
                               filetype=stat_lib.S_IFREG)
            else:
                stat = fs.Dir().stat()
            prev_name = name
            prev_stat = stat
        if prev_name is not None and prev_stat is not None:
            yield fs.Dirent(name=prev_name,
                            stat=prev_stat,
                            next_offset=index + offset + 1)

    def lookup(self, name: str) -> fs.Node:
        if self.prefix:
            path = self.prefix + "/" + name
        else:
            path = name
        path_bytes = path.encode("utf-8", "surrogateescape")
        row = self.db.cursor().execute(
            "select torrent_entry.info_hash, file_info.start, file_info.stop, "
            "torrent_entry.time "
            "from file_info "
            "inner join torrent_entry "
            "where file_info.id = torrent_entry.id and "
            "not torrent_entry.deleted and "
            "torrent_entry.group_id = ? "
            "and file_info.path = ?", (
                self.group_id,
                path_bytes,
            )).fetchone()
        if row:
            infohash, start, stop, mtime = row
            return fs.TorrentFile(tracker="btn",
                                  infohash=infohash,
                                  start=start,
                                  stop=stop,
                                  mtime=mtime)
        lo_bytes = path_bytes + b"/"
        hi_bytes = path_bytes + b"0"
        row = self.db.cursor().execute(
            "select file_info.id from file_info inner join torrent_entry "
            "where file_info.id = torrent_entry.id and "
            "not torrent_entry.deleted and "
            "torrent_entry.group_id = ? "
            "and file_info.path > ? and file_info.path < ? limit 1",
            (self.group_id, lo_bytes, hi_bytes)).fetchone()
        if row:
            return GroupBrowseSubdir(self.db, self.group_id, path)
        raise _mkoserror(errno.ENOENT, name)
