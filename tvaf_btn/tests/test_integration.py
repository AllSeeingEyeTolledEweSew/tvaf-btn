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


from typing import Any
from typing import Callable
from typing import cast
from typing import NamedTuple

import httpx
import libtorrent as lt
import pytest


class CacheSetup(NamedTuple):
    id: str
    torrent_entry: bool
    file_info: bool


CACHE_MATRIX = [
    CacheSetup(id="noentry-nofileinfo", torrent_entry=False, file_info=False),
    CacheSetup(id="entry-nofileinfo", torrent_entry=True, file_info=False),
    CacheSetup(id="entry-fileinfo", torrent_entry=True, file_info=True),
]


@pytest.fixture(
    autouse=True, params=CACHE_MATRIX, ids=[entry.id for entry in CACHE_MATRIX]
)
def cache_setup(
    request: Any,
    add_torrent_entry: Callable[[], None],
    add_file_info: Callable[[], None],
) -> CacheSetup:
    setup = cast(CacheSetup, request.param)

    if setup.torrent_entry:
        add_torrent_entry()

    if setup.file_info:
        add_file_info()

    return setup


# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_404(configured: bool, client: httpx.AsyncClient) -> None:
    r = await client.get("/data/btih/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/i/0")
    assert r.status_code == 404


async def test_get(
    info_hashes: lt.info_hash_t,
    client: httpx.AsyncClient,
    data: bytes,
    expect_fetch: Callable[[], None],
    configured: bool,
    cache_setup: CacheSetup,
) -> None:
    if configured and cache_setup.torrent_entry:
        expect_fetch()
    r = await client.get(f"/data/btih/{info_hashes.get_best()}/i/0")
    if configured and cache_setup.torrent_entry:
        assert r.status_code == 200
        assert r.content == data
    else:
        assert r.status_code == 404
