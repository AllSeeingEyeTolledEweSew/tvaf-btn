"""
/v1/{info_hash}/{tracker}/f/{path} -> ../../../i/{index}
/v1/{info_hash}/{tracker}/i/{index}
/v1/{info_hash}/default -> btn  # later
/browse/{library}/{meaningful path} -> ../../../v1/{info_hash}

btn, ptp: given torrent info_hash, access torrent data
default: given torrent info_hash, and seeder counts, redirects to concrete
accessors
cross-tracker: given file hash, downloads from multiple concrete trackers
"""
from __future__ import annotations

import abc
import collections
import errno
import io
import logging
import pathlib
import stat as stat_lib
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import List
from typing import MutableMapping
from typing import Optional

import libtorrent as lt

from tvaf import fs
from tvaf import protocol
from tvaf import types

_LOG = logging.getLogger(__name__)

Path = pathlib.PurePosixPath

TorrentFileOpener = Callable[
    [types.InfoHash, int, int, types.ConfigureATP], io.IOBase
]


class Metadata(collections.UserDict, MutableMapping[str, Any]):

    pass


class TorrentFile(fs.File):
    def __init__(
        self,
        *,
        opener: TorrentFileOpener,
        info_hash: types.InfoHash,
        start: int,
        stop: int,
        configure_atp: types.ConfigureATP
    ) -> None:
        super().__init__(size=stop - start)
        self.opener = opener
        self.info_hash = info_hash
        self.start = start
        self.stop = stop
        self.configure_atp = configure_atp

    def open_raw(self, mode: str = "r") -> io.IOBase:
        if set(mode) & set("wxa+"):
            raise fs.mkoserror(errno.EPERM)
        return self.opener(
            self.info_hash, self.start, self.stop, self.configure_atp
        )


def _is_valid_path(path: List[str]) -> bool:
    for part in path:
        if "/" in part:
            return False
        if part in (".", ".."):
            return False
    return True


class _V1TorrentInNetwork(fs.StaticDir):
    def __init__(
        self,
        libs: LibraryService,
        info_hash: types.InfoHash,
        info: protocol.Info,
        network: Network,
    ) -> None:
        super().__init__()

        self._by_path = fs.StaticDir()
        self.mkchild("f", self._by_path)
        self._by_index = fs.StaticDir()
        self.mkchild("i", self._by_index)

        for spec in info.iter_files():
            self._add_torrent_file(libs, info_hash, spec, network)

    def _add_torrent_file(
        self,
        libs: LibraryService,
        info_hash: types.InfoHash,
        spec: protocol.FileSpec,
        network: Network,
    ):
        if spec.is_pad:
            return
        if spec.is_symlink:
            # TODO
            return

        torrent_file = TorrentFile(
            opener=libs.opener,
            info_hash=info_hash,
            start=spec.start,
            stop=spec.stop,
            configure_atp=network.configure_atp,
        )
        self._by_index.mkchild(str(spec.index), torrent_file)

        if not _is_valid_path(spec.full_path):
            return

        parent = self._try_mkdirs(spec.full_path[:-1])
        if not parent:
            return
        parent.mkchild(spec.full_path[-1], fs.Symlink(target=torrent_file))

    def _try_mkdirs(self, dirnames: List[str]) -> Optional[fs.StaticDir]:
        parent = self._by_path
        for name in dirnames:
            child = parent.children.get(name)
            if not child:
                child = fs.StaticDir()
                parent.mkchild(name, child)
            elif not isinstance(child, fs.StaticDir):
                return None
            parent = child
        return parent


class _V1Torrent(fs.Dir):
    def __init__(
        self,
        libs: LibraryService,
        info_hash: types.InfoHash,
        info: protocol.Info,
    ):
        super().__init__()
        self.libs = libs
        self.info_hash = info_hash
        self.info = info

    def get_node(self, name: str) -> Optional[fs.Node]:
        network = self.libs.libraries.networks.get(name)
        if network is None:
            return None
        if not network.can_access(self.info_hash):
            return None

        return _V1TorrentInNetwork(
            self.libs, self.info_hash, self.info, network
        )

    def readdir(self) -> Iterator[fs.Dirent]:
        for name, network in list(self.libs.libraries.networks.items()):
            if network.can_access(self.info_hash):
                yield fs.Dirent(
                    name=name, stat=fs.Stat(filetype=stat_lib.S_IFDIR)
                )


class _V1(fs.Dir):
    def __init__(self, libs: LibraryService):
        super().__init__(perms=0o444)
        self.libs = libs

    def get_node(self, name: str) -> Optional[fs.Node]:
        info_hash = types.InfoHash(name)
        try:
            info_dict = self.libs.libraries.get_pseudo_info(
                info_hash, exact_paths=True
            )
        except Error:
            return None
        return _V1Torrent(self.libs, info_hash, protocol.Info(info_dict))

    def readdir(self) -> Iterator[fs.Dirent]:
        raise fs.mkoserror(errno.ENOSYS)


class _Browse(fs.DictDir):
    def __init__(self, libs: LibraryService):
        super().__init__()
        self.libs = libs

    def get_dict(self):
        return self.libs.browse_nodes


class _Root(fs.StaticDir):
    def __init__(self, libs: LibraryService):
        super().__init__()
        self.mkchild("v1", _V1(libs))
        self.mkchild("browse", _Browse(libs))


class Error(Exception):
    pass


class UnknownTorrentError(Error):
    pass


class PseudoInfoLibrary(abc.ABC):
    @abc.abstractmethod
    def get(
        self, info_hash: types.InfoHash, exact_paths=False
    ) -> protocol.BDict:
        raise UnknownTorrentError(info_hash)


class MetadataLibrary(abc.ABC):
    @abc.abstractmethod
    def get(
        self, info_hash: types.InfoHash, file_index: int, *names: str
    ) -> Metadata:
        return Metadata()


class ScrapeResponse:

    seeders: int
    leechers: int


class Network:
    @abc.abstractmethod
    def configure_atp(self, atp: lt.add_torrent_params) -> None:
        raise UnknownTorrentError(str(atp.info_hash))

    @abc.abstractmethod
    def match_tracker_url(self, tracker_url: str) -> bool:
        return False

    @abc.abstractmethod
    def scrape(self, info_hash: types.InfoHash) -> ScrapeResponse:
        raise UnknownTorrentError(info_hash)

    def can_access(self, info_hash: types.InfoHash) -> bool:
        try:
            self.scrape(info_hash)
        except UnknownTorrentError:
            return False
        return True


class Libraries:
    def __init__(self):
        self.networks: Dict[str, Network] = {}
        self.metadata: Dict[str, MetadataLibrary] = {}
        self.pseudo_info: Dict[str, PseudoInfoLibrary] = {}

    def get_metadata(
        self, info_hash: types.InfoHash, file_index: int, *names: str
    ) -> Metadata:
        result = Metadata()
        for library in list(self.metadata.values()):
            if all(name in result for name in names):
                break
            try:
                result.update(library.get(info_hash, file_index, *names))
            except UnknownTorrentError:
                pass
        return result

    def get_pseudo_info(
        self, info_hash: types.InfoHash, exact_paths=False
    ) -> protocol.BDict:
        for library in list(self.pseudo_info.values()):
            try:
                return library.get(info_hash, exact_paths=exact_paths)
            except UnknownTorrentError:
                pass
        raise UnknownTorrentError(info_hash)


class LibraryService:
    def __init__(self, *, opener: TorrentFileOpener, libraries: Libraries):
        self.opener = opener
        self.libraries = libraries
        self.root = _Root(libs=self)
        self.browse_nodes: Dict[str, fs.Node] = {}

    @staticmethod
    def get_torrent_path(info_hash: types.InfoHash) -> Path:
        return Path().joinpath("v1", info_hash)

    def lookup_torrent(self, info_hash: types.InfoHash) -> fs.Node:
        return self.root.traverse(self.get_torrent_path(info_hash))
