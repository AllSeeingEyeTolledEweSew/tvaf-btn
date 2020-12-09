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

import contextlib
import threading
from typing import cast
from typing import ContextManager
from typing import Optional


class Error(Exception):

    pass


class AuthenticationFailed(Error):
    pass


class _UserContext(contextlib.AbstractContextManager):
    def __init__(self, auth_service: "AuthService") -> None:
        self.auth_service = auth_service

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.auth_service.pop_user()


class AuthService:

    USER = "tvaf"
    PASSWORD = "U15OwvGt"

    def __init__(self) -> None:
        self._local = threading.local()

    def auth_password_plain(self, user: str, password: str) -> None:
        if (user, password) == (self.USER, self.PASSWORD):
            return
        raise AuthenticationFailed()

    def push_user(self, user: str) -> ContextManager[None]:
        assert self.get_user() is None
        ctx = _UserContext(self)
        self._local.user = user
        return ctx

    def get_user(self) -> Optional[str]:
        return cast(Optional[str], getattr(self._local, "user", None))

    def pop_user(self) -> None:
        assert self.get_user() is not None
        self._local.user = None
