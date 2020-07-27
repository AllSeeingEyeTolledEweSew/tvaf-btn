# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
from __future__ import annotations

import json
import pathlib
from typing import Callable
import dataclasses
import ipaddress
import pathlib
from typing import List
from typing import Any
from typing import Dict
from typing import MutableMapping
from typing import TypeVar
from typing import Union
from typing import Mapping
from typing import Optional
from typing import Type


# Design notes:

# Config is stored as json. This is so external programs can easily manipulate
# the config if necessary.

# Config is a dict of json-compatible python primitives. I tried using a
# dataclass to map it, but as of 3.8, translating between dataclasses and json
# is still quite cumbersome. We either need ad-hoc code in several different
# places, or complex metaclass code. All type conversion also needs to be
# centralized, which impacts modularity.

# I considered "staging" config updates, such that e.g. when the FTP port is
# changed, we would:
#  - bind a socket to the new port
#  - attempt any other config changes
#  - if other changes fail, close the new socket
#  - if other changes succeed, start the ftp server on the new port and close
#    the old server.
# Pros: minimizes operational interruption.
# Cons: this breaks on changes such as changing the ftp binding from 0.0.0.0:21
#       to 127.0.0.1:21, as the old server blocks the new binding.

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
    def from_config_dir(cls, config_dir:pathlib.Path):
        with config_dir.joinpath(FILENAME).open() as fp:
            try:
                data = json.load(fp)
            except json.JSONDecodeError as exc:
                raise InvalidConfigError(str(exc)) from exc
        return cls(data)

    def write_config_dir(self, config_dir:pathlib.Path):
        with config_dir.joinpath(FILENAME).open(mode="w") as fp:
            json.dump(self, fp, sort_keys=True, indent=4)

    def _get(self, key:str, type_:Type[_T], type_name:str) -> Optional[_T]:
        value = self.get(key)
        if key in self and not isinstance(value, type_):
            raise InvalidConfigError(f"\"{key}\": {value!r} is not {type_name}")
        return value

    def _require(self, key:str, type_:Type[_T], type_name:str) -> _T:
        value = self._get(key, type_, type_name)
        if value is None:
            raise InvalidConfigError(f"\"{key}\": missing")
        return value

    def get_int(self, key:str) -> Optional[int]:
        return self._get(key, int, "int")

    def get_str(self, key:str) -> Optional[str]:
        return self._get(key, str, "str")

    def get_bool(self, key:str) -> Optional[bool]:
        return self._get(key, bool, "bool")

    def require_int(self, key:str) -> int:
        return self._require(key, int, "int")

    def require_str(self, key:str) -> str:
        return self._require(key, str, "str")

    def require_bool(self, key:str) -> bool:
        return self._require(key, bool, "bool")


class HasConfig:

    def set_config(self, config:Config):
        pass
