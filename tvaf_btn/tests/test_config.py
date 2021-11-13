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
from typing import Dict

import pytest
from tvaf import services

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_configure(btn_config: Dict[str, Any]) -> None:
    config = await services.get_config()
    config.update(btn_config)
    await services.set_config(config)


async def test_unconfigure(btn_config: Dict[str, Any]) -> None:
    config = await services.get_config()
    for key in btn_config.keys():
        config.pop(key, None)
    await services.set_config(config)


# TODO: test validation, if we use any
