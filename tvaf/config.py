# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
from __future__ import annotations

import abc
import contextlib
import json
import pathlib
from typing import Any
from typing import Callable
from typing import ContextManager
from typing import MutableMapping
from typing import Optional
from typing import Type
from typing import TypeVar

# Design notes:

# Config is stored as json. This is so external programs can easily manipulate
# the config if necessary.

# Config is a dict of json-compatible python primitives. I tried using a
# dataclass to map it, but as of 3.8, translating between dataclasses and json
# is still quite cumbersome. We either need ad-hoc code in several different
# places, or complex metaclass code. All type conversion also needs to be
# centralized, which impacts modularity.

# Config updates are "staged" such that e.g. when the FTP port is changed, we:
#  - bind a socket to the new port
#  - attempt any other config changes
#  - if other changes fail, close the new socket
#  - if other changes succeed, start the ftp server on the new port and close
#    the old server.
# This makes certain changes impossible, such as changing the ftp binding from
# 0.0.0.0:21 to 127.0.0.1:21, as the old server breaks the new binding. However
# I notice that nginx has the same limitation, so it's probably good enough.

# In Python we prefer to work with "disposable" objects which are configured
# only once, and re-created as necessary. However, tvaf's top-level App code
# doesn't know the right life cycle for its various components (for example,
# should the App re-create the FTP server for a particular config change?).
# So we design our components to be long-lived objects which can be
# re-configured over their lifetimes.

FILENAME = "config.json"


class Error(Exception):

    pass


class InvalidConfigError(Error):

    pass


_T = TypeVar("_T")


class Config(dict, MutableMapping[str, Any]):

    @classmethod
    def from_config_dir(cls, config_dir: pathlib.Path):
        with config_dir.joinpath(FILENAME).open() as fp:
            try:
                data = json.load(fp)
            except json.JSONDecodeError as exc:
                raise InvalidConfigError(str(exc)) from exc
        return cls(data)

    def write_config_dir(self, config_dir: pathlib.Path):
        with config_dir.joinpath(FILENAME).open(mode="w") as fp:
            json.dump(self, fp, sort_keys=True, indent=4)

    def _get(self, key: str, type_: Type[_T], type_name: str) -> Optional[_T]:
        value = self.get(key)
        if key in self and not isinstance(value, type_):
            raise InvalidConfigError(f"\"{key}\": {value!r} is not {type_name}")
        return value

    def _require(self, key: str, type_: Type[_T], type_name: str) -> _T:
        value = self._get(key, type_, type_name)
        if value is None:
            raise InvalidConfigError(f"\"{key}\": missing")
        return value

    def get_int(self, key: str) -> Optional[int]:
        return self._get(key, int, "int")

    def get_str(self, key: str) -> Optional[str]:
        return self._get(key, str, "str")

    def get_bool(self, key: str) -> Optional[bool]:
        return self._get(key, bool, "bool")

    def require_int(self, key: str) -> int:
        return self._require(key, int, "int")

    def require_str(self, key: str) -> str:
        return self._require(key, str, "str")

    def require_bool(self, key: str) -> bool:
        return self._require(key, bool, "bool")


class HasConfig(abc.ABC):

    @abc.abstractmethod
    def stage_config(self, config: Config) -> ContextManager[None]:
        return contextlib.nullcontext()

    def set_config(self, config: Config) -> None:
        with self.stage_config(config):
            pass


def set_config(config: Config, *stages: Callable[[Config], ContextManager]):
    with contextlib.ExitStack() as stack:
        for stage in stages:
            stack.enter_context(stage(config))
