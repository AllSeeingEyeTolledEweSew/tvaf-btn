from __future__ import annotations

import contextlib
import threading
from typing import ContextManager
from typing import Optional
from typing import cast


class Error(Exception):

    pass


class AuthenticationFailed(Error):
    pass


class _UserContext(contextlib.AbstractContextManager):

    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        self.auth_service.pop_user()


class AuthService:

    USER = "tvaf"
    PASSWORD = "U15OwvGt"

    def __init__(self):
        self._local = threading.local()

    def auth_password_plain(self, user: str, password: str):
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

    def pop_user(self):
        assert self.get_user() is not None
        self._local.user = None
