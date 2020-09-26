import contextlib
import errno
import functools
import io
import logging
import os
import socket as socket_lib
import threading
import time
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple
from typing import cast

import pyftpdlib
import pyftpdlib.authorizers
import pyftpdlib.filesystems
import pyftpdlib.handlers
import pyftpdlib.servers

import tvaf.config as config_lib
from tvaf import auth
from tvaf import fs
from tvaf import task as task_lib

_LOG = logging.getLogger(__name__)


def _partialclass(cls, *args, **kwds):

    class Wrapped(cls):
        __init__ = functools.partialmethod(cls.__init__, *args, **kwds)

    return Wrapped


class _FS(pyftpdlib.filesystems.AbstractedFS):

    # pylint: disable=too-many-public-methods

    def __init__(self, *args, root: fs.Dir, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cur_dir = root

    def validpath(self, path: str) -> bool:
        # This is used to check whether a path traverses symlinks to escape a
        # home directory.
        return True

    def ftp2fs(self, ftppath: str) -> str:
        return cast(str, self.ftpnorm(ftppath))

    def fs2ftp(self, fspath: str) -> str:
        return fspath

    def mkstemp(
            self,
            suffix="",
            prefix="",
            dir=None,  # pylint: disable=redefined-builtin
            mode="wb") -> None:
        raise fs.mkoserror(errno.EROFS)

    def mkdir(self, path: str) -> None:
        raise fs.mkoserror(errno.EROFS)

    def rmdir(self, path: str) -> None:
        raise fs.mkoserror(errno.EROFS)

    def rename(self, src: str, dst: str) -> None:
        raise fs.mkoserror(errno.EROFS)

    def chmod(self, path: str, mode: str) -> None:
        raise fs.mkoserror(errno.EROFS)

    def utime(self, path: str, timeval) -> None:
        raise fs.mkoserror(errno.EROFS)

    def get_user_by_uid(self, uid: int) -> str:
        return "root"

    def get_group_by_gid(self, gid: int) -> str:
        return "root"

    def _traverse(self, path: str) -> fs.Node:
        return self.cur_dir.traverse(path)

    def _ltraverse(self, path: str) -> fs.Node:
        return self.cur_dir.traverse(path, follow_symlinks=False)

    def _traverse_to_dir(self, path: str) -> fs.Dir:
        dir_ = cast(fs.Dir, self._traverse(path))
        if not dir_.is_dir():
            raise fs.mkoserror(errno.ENOTDIR)
        return dir_

    def _traverse_to_link(self, path: str) -> fs.Symlink:
        symlink = cast(fs.Symlink, self._ltraverse(path))
        if not symlink.is_link():
            raise fs.mkoserror(errno.EINVAL)
        return symlink

    def chdir(self, path: str) -> None:
        self.cur_dir = self._traverse_to_dir(path)
        self.cwd = str(self.cur_dir.abspath())

    def open(self, filename: str, mode: str) -> io.BufferedIOBase:
        file_ = cast(fs.File, self._traverse(filename))
        if file_.is_dir():
            raise fs.mkoserror(errno.EISDIR)
        fp = file_.open(mode)
        return fp

    def listdir(self, path: str) -> List[str]:
        dir_ = self._traverse_to_dir(path)
        return [d.name for d in dir_.readdir()]

    def listdirinfo(self, path: str) -> List[str]:
        # Doesn't seem to be used. However, the base class implements it and we
        # don't want to allow access to the filesystem.
        return self.listdir(path)

    def stat(self, path: str) -> os.stat_result:
        return self._traverse(path).stat().os()

    def lstat(self, path: str) -> os.stat_result:
        return self._ltraverse(path).stat().os()

    def readlink(self, path: str) -> str:
        return str(self._traverse_to_link(path).readlink())

    def isfile(self, path: str) -> bool:
        try:
            return self._traverse(path).is_file()
        except OSError:
            return False

    def islink(self, path: str) -> bool:
        try:
            return self._ltraverse(path).is_link()
        except OSError:
            return False

    def lexists(self, path: str) -> bool:
        try:
            self._ltraverse(path)
        except OSError:
            return False
        return True

    def isdir(self, path: str) -> bool:
        try:
            return self._traverse(path).is_dir()
        except OSError:
            return False

    def getsize(self, path: str) -> int:
        return self._traverse(path).stat().size

    def getmtime(self, path: str) -> int:
        mtime = self._traverse(path).stat().mtime
        if mtime is not None:
            return mtime
        return int(time.time())

    def realpath(self, path: str) -> str:
        return str(self.cur_dir.realpath(path))


class _Authorizer(pyftpdlib.authorizers.DummyAuthorizer):

    def __init__(self, *, auth_service: auth.AuthService) -> None:
        # pylint: disable=super-init-not-called
        self.auth_service = auth_service

    def add_user(self,
                 username: str,
                 password: str,
                 homedir: str,
                 perm: str = "elr",
                 msg_login: str = "Login successful.",
                 msg_quit: str = "Goodbye.") -> None:
        raise NotImplementedError

    def add_anonymous(self, homedir: str, **kwargs) -> None:
        raise NotImplementedError

    def remove_user(self, username: str) -> None:
        raise NotImplementedError

    def override_perm(self,
                      username: str,
                      directory: str,
                      perm: str,
                      recursive=False) -> None:
        raise NotImplementedError

    def has_user(self, username: str) -> bool:
        raise NotImplementedError

    def get_msg_login(self, username: str) -> str:
        return "Login successful."

    def get_msg_quit(self, username: str) -> str:
        return "Goodbye."

    def get_home_dir(self, username: str) -> str:
        return "/"

    def has_perm(self, username: str, perm: str, path: str = None) -> bool:
        return perm in self.read_perms

    def get_perms(self, username: str) -> str:
        return cast(str, self.read_perms)

    def validate_authentication(self, username: str, password: str,
                                handler) -> None:
        try:
            self.auth_service.auth_password_plain(username, password)
        except auth.AuthenticationFailed as exc:
            raise pyftpdlib.authorizers.AuthenticationFailed(exc)

    def impersonate_user(self, username: str, password: str) -> None:
        self.auth_service.push_user(username)

    def terminate_impersonation(self, username: str) -> None:
        self.auth_service.pop_user()


class _FTPHandler(pyftpdlib.handlers.FTPHandler):

    # pyftpd just tests for existence of fileno, but BytesIO and
    # BufferedTorrentIO expose fileno that raises io.UnsupportedOperation.
    use_sendfile = False

    def __init__(self, *args, root: fs.Dir, auth_service: auth.AuthService,
                 **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.authorizer = _Authorizer(auth_service=auth_service)
        self.abstracted_fs = _partialclass(_FS, root=root)


class FTPD(task_lib.Task, config_lib.HasConfig):

    def __init__(self, *, config: config_lib.Config, root: fs.Dir,
                 auth_service: auth.AuthService) -> None:
        super().__init__(title="FTPD", thread_name="ftpd")
        self._auth_service = auth_service
        self._root = root

        # TODO: fixup typing here
        self._lock: threading.Condition = \
                threading.Condition(threading.RLock())  # type: ignore
        self._server: Optional[pyftpdlib.servers.FTPServer] = None
        self._address: Optional[Tuple] = None

        self.set_config(config)

    @property
    def socket(self):
        with self._lock:
            if self._server is None:
                return None
            return self._server.socket

    @contextlib.contextmanager
    def stage_config(self, config: config_lib.Config) -> Iterator[None]:
        config.setdefault("ftp_enabled", True)
        config.setdefault("ftp_bind_address", "localhost")
        config.setdefault("ftp_port", 8821)

        address: Optional[Tuple] = None
        socket: Optional[socket_lib.socket] = None

        # Only parse address and port if enabled
        if config.require_bool("ftp_enabled"):
            address = (config.require_str("ftp_bind_address"),
                       config.require_int("ftp_port"))

        with self._lock:
            if address != self._address and address is not None:
                socket = socket_lib.create_server(address)

            yield

            if self._terminated.is_set():
                return
            if address == self._address:
                return

            self._address = address
            self._terminate()

            if socket is None:
                return

            handler = _partialclass(_FTPHandler,
                                    root=self._root,
                                    auth_service=self._auth_service)
            self._server = pyftpdlib.servers.ThreadedFTPServer(socket, handler)

    def _terminate(self):
        with self._lock:
            if self._server is not None:
                self._server.close_all()
                self._server = None
            self._lock.notify_all()

    def _run(self):
        while not self._terminated.is_set():
            with self._lock:
                if self._server is None:
                    self._lock.wait()
                server = self._server
            if server:
                if _LOG.isEnabledFor(logging.INFO):
                    host, port = server.socket.getsockname()
                    _LOG.info("ftp server listening on %s:%s", host, port)
                server.serve_forever()
                _LOG.info("ftp server shut down")
