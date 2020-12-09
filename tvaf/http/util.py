# Copyright (c) 2020 AllSeeingEyeTolledEweSew
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
from typing import Union

import flask

_AppLike = Union[flask.Flask, flask.Blueprint]


def route(rule: str, **options: Any) -> Callable[[Callable], Callable]:
    def decorator(func: Callable) -> Callable:
        name = func.__name__
        endpoint: str = options.pop("endpoint", name)

        def undecorate(target: Any, applike: _AppLike) -> None:
            applike.add_url_rule(
                rule, endpoint, getattr(target, name), **options
            )

        func._undecorate = undecorate  # type: ignore
        return func

    return decorator


class Blueprint:
    def __init__(self, name: str, import_name: str, **kwargs) -> None:
        self.blueprint = flask.Blueprint(name, import_name, **kwargs)

        for attr_name in dir(self):
            target = getattr(self, attr_name)
            undecorate = getattr(target, "_undecorate", None)
            if undecorate is None:
                continue
            undecorate(self, self.blueprint)
