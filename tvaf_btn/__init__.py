# Copyright (c) 2021 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

"""BTN support for TVAF."""


import contextlib
import functools
import logging
import pathlib
import sqlite3
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple
from typing import TypeVar
from typing import Union

from btn_cache import metadata_db
import btn_cache.storage
import dbver
import libtorrent as lt
import multihash
import requests
from tvaf import config as config_lib
from tvaf import lifecycle
from tvaf import plugins
from tvaf import services
from tvaf.types import ConfigureATP

_LOG = logging.getLogger(__name__)


@lifecycle.singleton()
def get_storage() -> btn_cache.storage.Storage:
    return btn_cache.storage.Storage(pathlib.Path("btn"))


def get_auth_from_config(config: config_lib.Config) -> btn_cache.site.UserAuth:
    return btn_cache.site.UserAuth(
        user_id=config.get_int("btn_user_id"),
        auth=config.get_str("btn_auth"),
        authkey=config.get_str("btn_authkey"),
        passkey=config.get_str("btn_passkey"),
        api_key=config.get_str("btn_api_key"),
    )


@lifecycle.singleton()
def get_auth() -> btn_cache.site.UserAuth:
    return get_auth_from_config(services.get_config())


@lifecycle.singleton()
def get_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "tvaf-btn"})
    return session


@lifecycle.singleton()
def get_access() -> btn_cache.site.UserAccess:
    return btn_cache.site.UserAccess(
        auth=get_auth(), session=get_requests_session()
    )


@contextlib.contextmanager
def stage_config(config: config_lib.Config) -> Iterator[None]:
    get_auth_from_config(config)
    yield
    get_auth.cache_clear()
    get_access.cache_clear()


METADATA_DB_VERSION_SUPPORTED = 1000000


def get_metadata_db_conn() -> sqlite3.Connection:
    path = get_storage().metadata_db_path
    path.parent.mkdir(exist_ok=True, parents=True)
    return sqlite3.Connection(path, isolation_level=None)


metadata_db_pool = dbver.null_pool(get_metadata_db_conn)


@contextlib.contextmanager
def read_metadata_db() -> Iterator[Tuple[sqlite3.Connection, int]]:
    with dbver.begin_pool(metadata_db_pool, dbver.LockMode.DEFERRED) as conn:
        version = btn_cache.metadata_db.get_version(conn)
        dbver.semver_check_breaking(version, METADATA_DB_VERSION_SUPPORTED)
        yield (conn, version)


@contextlib.contextmanager
def write_metadata_db() -> Iterator[Tuple[sqlite3.Connection, int]]:
    with dbver.begin_pool(metadata_db_pool, dbver.LockMode.IMMEDIATE) as conn:
        version = metadata_db.upgrade(conn)
        dbver.semver_check_breaking(version, METADATA_DB_VERSION_SUPPORTED)
        yield (conn, version)


@contextlib.contextmanager
def _read_metadata_for_torrent_info(
    btmh: multihash.Multihash, check_file_info=True
) -> Iterator[sqlite3.Connection]:
    if btmh.func != multihash.Func.sha1:
        _LOG.debug("read metadata: not sha1")
        raise plugins.Pass()
    with read_metadata_db() as (conn, version):
        if version == 0:
            _LOG.debug("read metadata: empty db")
            raise plugins.Pass()
        if check_file_info:
            cur = conn.cursor().execute(
                "select file_info.id from torrent_entry inner join file_info "
                "on torrent_entry.id = file_info.id "
                "where torrent_entry.info_hash = ?",
                (btmh.digest.hex(),),
            )
            if cur.fetchone() is None:
                _LOG.debug("read metadata: no cached file_info")
                raise plugins.Pass()
        yield conn


_C = TypeVar("_C", bound=Callable[..., Any])


def _with_fetch(func: _C) -> _C:
    @functools.wraps(func)
    def wrapped(btmh: multihash.Multihash, *args: Any, **kwargs: Any) -> Any:
        try:
            torrent_id = get_torrent_id(btmh)
        except KeyError:
            _LOG.debug("read metadata with fetch: no matching torrent_entry")
            raise plugins.Pass()
        torrent = _fetch_bdecoded_torrent(torrent_id)
        info = torrent[b"info"]
        # TODO: top-level publish
        receive_bdecoded_info(btmh, info)
        return func(btmh, *args, **kwargs)

    return cast(_C, wrapped)


def get_file_bounds(
    btmh: multihash.Multihash, file_index: int
) -> Tuple[int, int]:
    with _read_metadata_for_torrent_info(btmh) as conn:
        cur = conn.cursor().execute(
            "select file_info.start, file_info.stop from torrent_entry "
            "inner join file_info on torrent_entry.id = file_info.id "
            "where torrent_entry.info_hash = ? and file_index = ?",
            (btmh.digest.hex(), file_index),
        )
        row = cur.fetchone()
    if row is None:
        _LOG.debug("get_file_bounds: not found")
        raise IndexError()
    return cast(Tuple[int, int], row)


get_file_bounds_with_fetch = _with_fetch(get_file_bounds)


def get_file_path(
    btmh: multihash.Multihash, file_index: int
) -> Union[List[str], List[bytes]]:
    with _read_metadata_for_torrent_info(btmh) as conn:
        cur = conn.cursor().execute(
            "select file_info.path, file_info.encoding from torrent_entry "
            "inner join file_info on torrent_entry.id = file_info.id "
            "where torrent_entry.info_hash = ? and file_index = ?",
            (btmh.digest.hex(), file_index),
        )
        row = cur.fetchone()
    if row is None:
        _LOG.debug("get_file_path: not found")
        raise IndexError()
    path_bencoded, encoding = cast(Tuple[bytes, Optional[str]], row)
    path = cast(List[bytes], lt.bdecode(path_bencoded))
    if encoding:
        try:
            return [name.decode(encoding) for name in path]
        except (LookupError, ValueError) as exc:
            _LOG.debug("get_file_path: bad encoding for %s: %s", path, exc)
            # LookupError raised for unknown encodings
    return path


get_file_path_with_fetch = _with_fetch(get_file_path)


def get_num_files(btmh: multihash.Multihash) -> int:
    with _read_metadata_for_torrent_info(btmh, check_file_info=False) as conn:
        cur = conn.cursor().execute(
            "select count(*) as c from torrent_entry inner join file_info "
            "on file_info.id = torrent_entry.id "
            "where torrent_entry.info_hash = ? "
            "group by torrent_entry.id having c > 0",
            (btmh.digest.hex(),),
        )
        row = cur.fetchone()
    if row is None:
        _LOG.debug("get_num_files: no cached file_info")
        raise plugins.Pass()
    (num_files,) = cast(Tuple[int], row)
    return num_files


get_num_files_with_fetch = _with_fetch(get_num_files)


def get_torrent_id(btmh: multihash.Multihash) -> int:
    if btmh.func != multihash.Func.sha1:
        _LOG.debug("get_torrent_id: not sha1")
        raise KeyError(btmh)
    with read_metadata_db() as (conn, version):
        if version == 0:
            _LOG.debug("get_torrent_id: empty db")
            raise KeyError(btmh)
        cur = conn.cursor().execute(
            "select id from torrent_entry where info_hash = ? and not deleted "
            "order by id desc",
            (btmh.digest.hex(),),
        )
        row = cur.fetchone()
    if row is None:
        _LOG.debug("get_torrent_id: not found")
        raise KeyError(btmh)
    (torrent_id,) = cast(Tuple[int], row)
    return torrent_id


def _fetch_bdecoded_torrent(torrent_id: int) -> Dict[bytes, Any]:
    resp = get_access().get_torrent(torrent_id)
    resp.raise_for_status()
    bencoded = resp.content
    return cast(Dict[bytes, Any], lt.bdecode(bencoded))


def configure_atp(torrent_id: int, atp: lt.add_torrent_params) -> None:
    bdecoded = _fetch_bdecoded_torrent(torrent_id)
    ti = lt.torrent_info(bdecoded)
    # TODO: top-level publish
    sha1_hash = ti.info_hash()
    if not sha1_hash.is_all_zeros():
        receive_bdecoded_info(
            multihash.Multihash(multihash.Func.sha1, sha1_hash.to_bytes()),
            bdecoded[b"info"],
        )
    atp.ti = ti


def get_configure_atp(
    btmh: multihash.Multihash,
) -> ConfigureATP:
    try:
        torrent_id = get_torrent_id(btmh)
    except KeyError:
        _LOG.debug("get_configure_atp: not found")
        raise plugins.Pass()
    return functools.partial(configure_atp, torrent_id)


def receive_bdecoded_info(
    btmh: multihash.Multihash, info: Dict[bytes, Any]
) -> None:
    if btmh.func != multihash.Func.sha1:
        return
    # We expect the common case to fail to find any ids to update, so we don't
    # bother preparing the update outside the lock
    with write_metadata_db() as (conn, _):
        cur = conn.cursor().execute(
            "select torrent_entry.id from torrent_entry left outer join "
            "file_info on file_info.id = torrent_entry.id "
            "where torrent_entry.info_hash = ? and file_info.id is null "
            "order by torrent_entry.deleted desc, torrent_entry.id desc",
            (btmh.digest.hex(),),
        )
        row = cur.fetchone()
        if row is None:
            return
        (torrent_id,) = cast(Tuple[int], row)
        metadata_db.ParsedTorrentInfoUpdate(
            info, torrent_entry_id=torrent_id
        ).apply(conn)
