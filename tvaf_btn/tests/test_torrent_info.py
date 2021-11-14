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
from typing import Type

import libtorrent as lt
import pytest
from tvaf import torrent_info


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


async def test_map_file_bad_torrent(configured: bool) -> None:
    # We should always get KeyError with an unknown torrent
    with pytest.raises(KeyError):
        await torrent_info.map_file(lt.info_hash_t(lt.sha1_hash(b"a" * 20)), 0)


async def test_map_file_bad_file(
    info_hashes: lt.info_hash_t,
    configured: bool,
    cache_setup: CacheSetup,
    expect_fetch: Callable[[], None],
) -> None:
    # If we query a non-existing file on a torrent that exists, we should get
    # IndexError if we're able to know about the torrent, otherwise we should get
    # KeyError
    expected_error: Type[Exception] = KeyError
    if cache_setup.torrent_entry:
        if configured or cache_setup.file_info:
            expected_error = IndexError
        # We should only fetch the torrent if we know it exists but don't have the
        # file info
        if configured and not cache_setup.file_info:
            expect_fetch()
    with pytest.raises(expected_error):
        await torrent_info.map_file(info_hashes, 1)


async def test_map_file(
    configured: bool,
    cache_setup: CacheSetup,
    size: int,
    info_hashes: lt.info_hash_t,
    expect_fetch: Callable[[], None],
) -> None:
    if not (cache_setup.torrent_entry and (configured or cache_setup.file_info)):
        with pytest.raises(KeyError):
            await torrent_info.map_file(info_hashes, 0)
    else:
        # We should only fetch the torrent if we know it exists but don't have the
        # file info
        if configured and not cache_setup.file_info:
            expect_fetch()
        bounds = await torrent_info.map_file(info_hashes, 0)
        assert bounds == (0, size)


async def test_is_private_good(
    configured: bool,
    info_hashes: lt.info_hash_t,
    cache_setup: CacheSetup,
) -> None:
    if not cache_setup.torrent_entry:
        with pytest.raises(KeyError):
            await torrent_info.is_private(info_hashes)
    else:
        assert await torrent_info.is_private(info_hashes)


async def test_is_private_bad(configured: bool) -> None:
    with pytest.raises(KeyError):
        await torrent_info.is_private(lt.info_hash_t(lt.sha1_hash(b"a" * 20)))
