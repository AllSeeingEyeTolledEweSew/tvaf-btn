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


from typing import Callable

import httpx
import libtorrent as lt
import pytest

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_404(client: httpx.AsyncClient) -> None:
    r = await client.get("/data/btih/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/i/0")
    assert r.status_code == 404


async def test_get(
    info_hashes: lt.info_hash_t,
    client: httpx.AsyncClient,
    data: bytes,
    expect_fetch: Callable[[], None],
    configured: bool,
    torrent_entry_exists: bool,
) -> None:
    if configured and torrent_entry_exists:
        expect_fetch()
    r = await client.get(f"/data/btih/{info_hashes.get_best()}/i/0")
    if configured and torrent_entry_exists:
        assert r.status_code == 200
        assert r.content == data
    else:
        assert r.status_code == 404
