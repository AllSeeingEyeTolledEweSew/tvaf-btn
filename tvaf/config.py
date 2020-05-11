# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
from __future__ import annotations

from typing import Callable
import dataclasses

import dataclasses_json


@dataclasses_json.dataclass_json
@dataclasses.dataclass(frozen=True)
class Config:

    save_path: str = ""
    btn_save_path: str = ""

    def replace(self, **changes) -> Config:
        return dataclasses.replace(self, **changes)


GetConfig = Callable[[], Config]
