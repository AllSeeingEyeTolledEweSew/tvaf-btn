# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Exception types for tvaf core functionality."""
from __future__ import annotations

import dataclasses
import sys
import traceback
from typing import Optional

import dataclasses_json
import libtorrent


class Error(Exception):

    def __init__(self, message: str, code: int, details: Optional[str] = None):
        super(Error, self).__init__(message, code)
        self.message = message
        self.code = code
        self.details = details


@dataclasses_json.dataclass_json
@dataclasses.dataclass(frozen=True)
class ErrorValue:

    code: int = 500
    message: str = ""
    details: Optional[str] = None

    @classmethod
    def from_exc_info(cls) -> ErrorValue:
        _, exc, tb = sys.exc_info()
        assert exc is not None
        details = "".join(traceback.format_tb(tb))
        if isinstance(exc, Error):
            if exc.details:
                details = exc.details
            return cls(code=exc.code, message=exc.message, details=details)
        return cls(code=500, message=str(exc), details=details)

    @classmethod
    def from_error_code(cls, ec: libtorrent.error_code) -> Optional[ErrorValue]:
        if not ec.value():
            return None
        if ec.category() == libtorrent.http_category():
            code = ec.value()
        else:
            # Map more codes here
            code = 500
        details = f"{ec.category().name()} {ec.value()}: {ec.message()}"
        return cls(code=code, message=ec.message(), details=details)

    @classmethod
    def from_alert(cls, alert: libtorrent.alert) -> Optional[ErrorValue]:
        error = getattr(alert, "error", None)
        if not error:
            return None
        return cls.from_error_code(error)

    def raise_exception(self):
        raise Error(self.message, self.code, details=self.details)

    def replace(self, **changes) -> ErrorValue:
        return dataclasses.replace(self, **changes)
