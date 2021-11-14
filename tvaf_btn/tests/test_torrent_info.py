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
from typing import Type

import libtorrent as lt
import pytest
from tvaf import torrent_info

# All test coroutines will be treated as marked.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("cache_status")]


async def test_get_file_bounds_from_cache_bad_torrent(configured: bool) -> None:
    # We should always get KeyError with an unknown torrent
    with pytest.raises(KeyError):
        await torrent_info.get_file_bounds_from_cache(
            lt.info_hash_t(lt.sha1_hash(b"a" * 20)), 0
        )


async def test_get_file_bounds_from_cache_bad_file(
    info_hashes: lt.info_hash_t,
    configured: bool,
    file_info_exists: bool,
    torrent_entry_exists: bool,
    expect_fetch: Callable[[], None],
) -> None:
    # If we query a non-existing file on a torrent that exists, we should get
    # IndexError if we're able to know about the torrent, otherwise we should get
    # KeyError
    expected_error: Type[Exception] = KeyError
    if torrent_entry_exists:
        if configured or file_info_exists:
            expected_error = IndexError
        # We should only fetch the torrent if we know it exists but don't have the
        # file info
        if configured and not file_info_exists:
            expect_fetch()
    with pytest.raises(expected_error):
        await torrent_info.get_file_bounds_from_cache(info_hashes, 1)


async def test_get_file_bounds_from_cache_good(
    configured: bool,
    torrent_entry_exists: bool,
    file_info_exists: bool,
    size: int,
    info_hashes: lt.info_hash_t,
    expect_fetch: Callable[[], None],
) -> None:
    if not (torrent_entry_exists and (configured or file_info_exists)):
        with pytest.raises(KeyError):
            await torrent_info.get_file_bounds_from_cache(info_hashes, 0)
    else:
        # We should only fetch the torrent if we know it exists but don't have the
        # file info
        if configured and not file_info_exists:
            expect_fetch()
        bounds = await torrent_info.get_file_bounds_from_cache(info_hashes, 0)
        assert bounds == (0, size)


async def test_is_private_good(
    configured: bool, torrent_entry_exists: bool, info_hashes: lt.info_hash_t
) -> None:
    if not torrent_entry_exists:
        with pytest.raises(KeyError):
            await torrent_info.is_private(info_hashes)
    else:
        assert await torrent_info.is_private(info_hashes)


async def test_is_private_bad(configured: bool) -> None:
    with pytest.raises(KeyError):
        await torrent_info.is_private(lt.info_hash_t(lt.sha1_hash(b"a" * 20)))
