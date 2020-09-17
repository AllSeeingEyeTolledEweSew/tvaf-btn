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
            applike.add_url_rule(rule, endpoint, getattr(target, name),
                                 **options)

        setattr(func, "_undecorate", undecorate)
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
