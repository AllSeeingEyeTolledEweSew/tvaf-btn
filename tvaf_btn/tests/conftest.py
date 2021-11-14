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

import functools
import hashlib
import http.server
import os
import pathlib
import random
import sqlite3
import threading
from typing import Any
from typing import AsyncIterator
from typing import Callable
from typing import cast
from typing import ContextManager
from typing import Dict
from typing import Iterator
from typing import NamedTuple
from typing import Sequence
from typing import Tuple
import uuid

import asgi_lifespan
from btn_cache import api_types
from btn_cache import metadata_db
from btn_cache import storage as btn_storage
import httpx
import libtorrent as lt
import pytest
from tvaf import app as app_lib
from tvaf import config as config_lib
from tvaf import lifecycle as lifecycle_lib
from tvaf import services

import tvaf_btn


@pytest.fixture()
def chdir_tmp_path(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    old = pathlib.Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(old)


@pytest.fixture()
def lifecycle() -> Iterator:
    yield
    lifecycle_lib.clear()


def get_isolated_settings() -> Dict[str, Any]:
    return {
        "enable_dht": False,
        "enable_lsd": False,
        "enable_natpmp": False,
        "enable_upnp": False,
        "listen_interfaces": "127.0.0.1:0",
        "alert_mask": 0,
        "dht_bootstrap_nodes": "",
    }


@pytest.fixture(autouse=True)
async def lifespan(
    chdir_tmp_path: pathlib.Path, lifecycle: Any
) -> AsyncIterator[asgi_lifespan.LifespanManager]:
    config = config_lib.Config(
        public_enable=False,
    )
    config.update({f"session_{k}": v for k, v in get_isolated_settings().items()})
    await config.write_to_disk(services.CONFIG_PATH)
    async with asgi_lifespan.LifespanManager(
        app_lib.APP, startup_timeout=None, shutdown_timeout=None
    ) as manager:
        yield manager


@pytest.fixture()
async def client(lifespan: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        app=app_lib.APP, base_url="http://test", follow_redirects=True
    ) as client:
        yield client


# Ensure we always use requests_mock for isolation
@pytest.fixture(autouse=True)
def auto_requests_mock(requests_mock: Any) -> None:
    pass


@pytest.fixture()
def user_id() -> int:
    return random.randrange(1_000_000)


@pytest.fixture()
def auth() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def authkey() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def passkey() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def api_key() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def btn_config(
    user_id: int, auth: str, authkey: str, passkey: str, api_key: str
) -> Dict[str, Any]:
    return {
        "btn_user_id": user_id,
        "btn_auth": auth,
        "btn_authkey": authkey,
        "btn_passkey": passkey,
        "btn_api_key": api_key,
    }


@pytest.fixture(params=[True, False], ids=["configured", "notconfigured"])
async def configured(lifespan: Any, btn_config: Dict[str, Any], request: Any) -> bool:
    if request.param:
        config = await services.get_config()
        config.update(btn_config)
        await services.set_config(config)
    return bool(request.param)


@pytest.fixture()
def size() -> int:
    return random.randrange(1, 1_000_000)


@pytest.fixture()
def piece_length() -> int:
    return 16384


@pytest.fixture()
def data(size: int) -> bytes:
    return bytes(random.getrandbits(8) for _ in range(size))


@pytest.fixture()
def pieces(data: bytes, piece_length: int) -> Sequence[bytes]:
    return [data[i : i + piece_length] for i in range(0, len(data), piece_length)]


@pytest.fixture()
def info(size: int, pieces: Sequence[bytes]) -> Dict[bytes, Any]:
    piece_hashes = b"".join(hashlib.sha1(piece).digest() for piece in pieces)
    return {
        b"name": b"s01e01.mkv",
        b"piece length": 16384,
        b"pieces": piece_hashes,
        b"length": size,
    }


@pytest.fixture()
def info_hashes(info: Dict[bytes, Any]) -> lt.info_hash_t:
    return lt.info_hash_t(lt.sha1_hash(hashlib.sha1(lt.bencode(info)).digest()))


@pytest.fixture()
def torrent_entry_id() -> int:
    return random.randrange(1, 1_000_000)


@pytest.fixture()
def torrent_entry(
    info_hashes: lt.info_hash_t, torrent_entry_id: int, size: int
) -> api_types.TorrentEntry:
    return api_types.TorrentEntry(
        Category="Episode",
        Codec="H.264",
        Container="MKV",
        DownloadURL="https://example.com/unused",
        GroupID="234",
        GroupName="S01E01",
        ImdbID="1234567",
        InfoHash=info_hashes.get_best().to_bytes().hex().upper(),
        Leechers="1",
        Origin="P2P",
        ReleaseName="example.s01e01.coolkids",
        Resolution="1080p",
        Seeders="10",
        Series="Example",
        SeriesBanner="https://example.com/banner.jpg",
        SeriesID="345",
        SeriesPoster="https://example.com/poster.jpg",
        Size=str(size),
        Snatched="100",
        Source="HDTV",
        Time="123456789",
        TorrentID=str(torrent_entry_id),
        TvdbID="456",
        TvrageID="567",
        YoutubeTrailer="https://www.youtube.com/v/abcdefghijk",
    )


@pytest.fixture()
def storage(chdir_tmp_path: pathlib.Path, lifecycle: Any) -> btn_storage.Storage:
    # Enforces fixture dependencies
    return tvaf_btn.get_storage()


@pytest.fixture()
def write_metadata_db(
    storage: btn_storage.Storage,
) -> Callable[[], ContextManager[Tuple[sqlite3.Connection, int]]]:
    # Enforces fixture dependencies
    return tvaf_btn.write_metadata_db


class CacheStatus(NamedTuple):
    id: str
    torrent_entry_exists: bool
    file_info_exists: bool


CACHE_MATRIX = [
    CacheStatus(
        id="noentry-nofileinfo", torrent_entry_exists=False, file_info_exists=False
    ),
    CacheStatus(
        id="entry-nofileinfo", torrent_entry_exists=True, file_info_exists=False
    ),
    CacheStatus(id="entry-fileinfo", torrent_entry_exists=True, file_info_exists=True),
]


@pytest.fixture(params=CACHE_MATRIX, ids=[entry.id for entry in CACHE_MATRIX])
def cache_status(
    request: Any,
    torrent_entry: api_types.TorrentEntry,
    torrent_entry_id: int,
    write_metadata_db: Callable[[], ContextManager[Tuple[sqlite3.Connection, int]]],
    info: Dict[bytes, Any],
) -> CacheStatus:
    status = cast(CacheStatus, request.param)

    if status.torrent_entry_exists:
        entry_update = metadata_db.TorrentEntriesUpdate(torrent_entry)
        with write_metadata_db() as (conn, _):
            entry_update.apply(conn)

    if status.file_info_exists:
        info_update = metadata_db.ParsedTorrentInfoUpdate(info, torrent_entry_id)
        with write_metadata_db() as (conn, _):
            info_update.apply(conn)

    return status


@pytest.fixture()
def torrent_entry_exists(
    cache_status: CacheStatus,
) -> bool:
    return cache_status.torrent_entry_exists


@pytest.fixture()
def file_info_exists(cache_status: CacheStatus) -> bool:
    return cache_status.file_info_exists


class WebSeedRequestHandler(http.server.BaseHTTPRequestHandler):
    def __init__(self, data: bytes, *args: Any, **kwargs: Any) -> None:
        self._data = data
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("content-length", str(len(self._data)))
        self.end_headers()
        self.wfile.write(self._data)


@pytest.fixture()
def webseed(data: bytes) -> Iterator[str]:
    handler = functools.partial(WebSeedRequestHandler, data)
    with http.server.HTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        addr, port = server.server_address
        yield f"http://{addr}:{port}/"
        server.shutdown()


@pytest.fixture()
def torrent_dict(info: Dict[bytes, Any], webseed: str) -> Dict[bytes, Any]:
    return {b"info": info, b"url-list": webseed.encode("ascii")}


@pytest.fixture()
def torrent_file(torrent_dict: Dict[bytes, Any]) -> bytes:
    return lt.bencode(torrent_dict)


@pytest.fixture()
def expect_fetch(
    torrent_file: bytes,
    torrent_entry_id: int,
    requests_mock: Any,
    passkey: str,
) -> Callable[[], None]:
    def expect() -> None:
        requests_mock.get(
            "https://broadcasthe.net/torrents.php?action=download&"
            f"id={torrent_entry_id}&torrent_pass={passkey}",
            content=torrent_file,
        )

    return expect
