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
import logging
import pathlib
import sqlite3
from typing import Any
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable
from typing import cast
from typing import Dict
from typing import Iterator
from typing import Optional
from typing import Tuple

from btn_cache import metadata_db
from btn_cache import site as btn_site
from btn_cache import storage as btn_storage
import dbver
import libtorrent as lt
import requests
from tvaf import concurrency
from tvaf import config as config_lib
from tvaf import lifecycle
from tvaf import services
from tvaf import swarm as tvaf_swarm
from tvaf import torrent_info
from tvaf.swarm import ConfigureSwarm

_LOG = logging.getLogger(__name__)


@lifecycle.singleton()
def get_storage() -> btn_storage.Storage:
    return btn_storage.Storage(pathlib.Path("btn"))


def get_auth_from(config: config_lib.Config) -> btn_site.UserAuth:
    return btn_site.UserAuth(
        user_id=config.get_int("btn_user_id"),
        auth=config.get_str("btn_auth"),
        authkey=config.get_str("btn_authkey"),
        passkey=config.get_str("btn_passkey"),
        api_key=config.get_str("btn_api_key"),
    )


@lifecycle.asingleton()
@services.startup_plugin("50_btn")
async def get_auth() -> btn_site.UserAuth:
    return get_auth_from(await services.get_config())


@lifecycle.asingleton()
async def get_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "tvaf-btn"})
    return session


@lifecycle.asingleton()
async def get_access() -> btn_site.UserAccess:
    return btn_site.UserAccess(
        auth=await get_auth(), session=await get_requests_session()
    )


@services.stage_config_plugin("50_btn")
@contextlib.asynccontextmanager
async def stage_config(config: config_lib.Config) -> AsyncIterator[None]:
    get_auth_from(config)
    yield
    get_auth.cache_clear()
    get_access.cache_clear()


METADATA_DB_VERSION_SUPPORTED = 1_000_000


def get_metadata_db_conn() -> sqlite3.Connection:
    path = get_storage().metadata_db_path
    path.parent.mkdir(exist_ok=True, parents=True)
    return sqlite3.Connection(path, isolation_level=None)


metadata_db_pool = dbver.null_pool(get_metadata_db_conn)


@contextlib.contextmanager
def read_metadata_db() -> Iterator[Tuple[sqlite3.Connection, int]]:
    with dbver.begin_pool(metadata_db_pool, dbver.LockMode.DEFERRED) as conn:
        version = metadata_db.get_version(conn)
        dbver.semver_check_breaking(version, METADATA_DB_VERSION_SUPPORTED)
        yield (conn, version)


@contextlib.contextmanager
def write_metadata_db() -> Iterator[Tuple[sqlite3.Connection, int]]:
    # TODO: should we set WAL? where?
    with dbver.begin_pool(metadata_db_pool, dbver.LockMode.IMMEDIATE) as conn:
        version = metadata_db.upgrade(conn)
        dbver.semver_check_breaking(version, METADATA_DB_VERSION_SUPPORTED)
        yield (conn, version)


async def get_fetcher(
    torrent_entry_id: int,
) -> Optional[Callable[[], Awaitable[bytes]]]:
    access = await get_access()
    # TODO: should btn_cache do this validation?
    if access._auth.passkey is None:
        return None

    async def fetch() -> bytes:
        # TODO: change to aiohttp
        resp = await concurrency.to_thread(access.get_torrent, torrent_entry_id)
        resp.raise_for_status()
        return await concurrency.to_thread(getattr, resp, "content")

    return fetch


async def fetch_and_store(info_hashes: lt.info_hash_t) -> None:
    torrent_entry_id = await concurrency.to_thread(get_torrent_entry_id, info_hashes)
    fetch = await get_fetcher(torrent_entry_id)
    if fetch is None:
        return
    bencoded = await fetch()
    bdecoded = cast(Dict[bytes, Any], lt.bdecode(bencoded))
    # TODO: top-level publish
    await concurrency.to_thread(
        receive_bdecoded_info, torrent_entry_id, bdecoded[b"info"]
    )


def get_file_bounds_from_cache_sync(
    info_hashes: lt.info_hash_t, file_index: int
) -> Tuple[int, int]:
    with read_metadata_db() as (conn, version):
        if version == 0:
            raise KeyError(info_hashes)
        hexdigest = info_hashes.get_best().to_bytes().hex()
        cur = conn.cursor().execute(
            "select file_info.id from torrent_entry inner join file_info "
            "on torrent_entry.id = file_info.id "
            "where torrent_entry.info_hash = ?",
            (hexdigest,),
        )
        if cur.fetchone() is None:
            _LOG.debug("get_file_bounds_from_cache: no cached file_info")
            raise KeyError(info_hashes)
        cur = conn.cursor().execute(
            "select file_info.start, file_info.stop from torrent_entry "
            "inner join file_info on torrent_entry.id = file_info.id "
            "where torrent_entry.info_hash = ? and file_index = ?",
            (hexdigest, file_index),
        )
        row = cur.fetchone()
    if row is None:
        _LOG.debug("get_file_bounds_from_cache: not found")
        raise IndexError()
    return cast(Tuple[int, int], row)


@torrent_info.get_file_bounds_from_cache_plugin("30_btn")
async def get_file_bounds_from_cache(
    info_hashes: lt.info_hash_t, file_index: int
) -> Tuple[int, int]:
    return await concurrency.to_thread(
        get_file_bounds_from_cache_sync, info_hashes, file_index
    )


@torrent_info.get_file_bounds_from_cache_plugin("90_btn_fetch")
async def fetch_and_get_file_bounds_from_cache(
    info_hashes: lt.info_hash_t, file_index: int
) -> Tuple[int, int]:
    await fetch_and_store(info_hashes)
    return await get_file_bounds_from_cache(info_hashes, file_index)


def get_torrent_entry_id(info_hashes: lt.info_hash_t) -> int:
    digest = info_hashes.get_best().to_bytes()
    with read_metadata_db() as (conn, version):
        if version == 0:
            _LOG.debug("get_torrent_entry_id: empty db")
            raise KeyError(info_hashes)
        cur = conn.cursor().execute(
            "select id from torrent_entry where info_hash = ? and not deleted "
            "order by id desc",
            (digest.hex(),),
        )
        row = cur.fetchone()
    if row is None:
        _LOG.debug("get_torrent_entry_id: not found")
        raise KeyError(info_hashes)
    (torrent_entry_id,) = cast(Tuple[int], row)
    return torrent_entry_id


@tvaf_swarm.access_swarm_plugin("btn")
async def access_swarm(info_hashes: lt.info_hash_t) -> ConfigureSwarm:
    torrent_entry_id = await concurrency.to_thread(get_torrent_entry_id, info_hashes)
    fetch = await get_fetcher(torrent_entry_id)
    if fetch is None:
        raise KeyError(info_hashes)

    async def configure_swarm(atp: lt.add_torrent_params) -> None:
        assert fetch is not None  # helps mypy
        bencoded = await fetch()
        bdecoded = cast(Dict[bytes, Any], lt.bdecode(bencoded))
        atp.ti = lt.torrent_info(bdecoded)
        # TODO: top-level publish
        await concurrency.to_thread(
            receive_bdecoded_info, torrent_entry_id, bdecoded[b"info"]
        )

    return configure_swarm


def receive_bdecoded_info(torrent_entry_id: int, info: Dict[bytes, Any]) -> None:
    # We expect the common case to fail to find any ids to update, so we don't
    # bother preparing the update outside the lock
    with write_metadata_db() as (conn, _):
        cur = conn.cursor().execute(
            "SELECT id FROM file_info WHERE id = ?", (torrent_entry_id,)
        )
        row = cur.fetchone()
        if row is not None:
            return
        update = metadata_db.ParsedTorrentInfoUpdate(
            info, torrent_entry_id=torrent_entry_id
        )
        update.apply(conn)


@torrent_info.is_private_plugin("50_btn")
async def is_private(info_hashes: lt.info_hash_t) -> bool:
    await concurrency.to_thread(get_torrent_entry_id, info_hashes)
    return True
