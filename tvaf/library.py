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

import dataclasses
import io
import pathlib
from typing import Optional
from typing import Callable
import logging
from tvaf import protocol
from typing import List
import collections
from typing import Dict
from typing import Iterator
import stat as stat_lib
from tvaf import config as config_lib
from typing import Any
from typing import cast
from tvaf import fs
from tvaf import util
from tvaf import types


_log = logging.getLogger(__name__)

Path = pathlib.PurePosixPath

GetTorrent = Callable[[], bytes]


class Hints(collections.UserDict):

    pass


TorrentFileOpener = Callable[[types.TorrentRef, GetTorrent], io.RawIOBase]


class TorrentFile(fs.File):

    def __init__(self, *, opener:TorrentFileOpener=None,
            ref:types.TorrentRef=None,
            get_torrent:GetTorrent=None, hints:Hints=None):
        assert opener is not None
        assert ref is not None
        assert get_torrent is not None
        assert hints is not None
        super().__init__(size=len(ref), mtime=hints.get("mtime"))
        self.opener = opener
        self.ref = ref
        self.get_torrent = get_torrent
        self.hints = hints

    def open_raw(self, mode:str="r") -> io.RawIOBase:
        if set(mode) & set("wxa+"):
            raise fs.mkoserror(errno.EPERM)
        return self.opener(self.ref, self.get_torrent)


def _is_valid_path(path:List[str]):
    for part in path:
        if "/" in part:
            return False
        if part in (".", ".."):
            return False
    return True


class _V1TorrentAccess(fs.StaticDir):

    def __init__(self, libs:LibraryService, info_hash:str, info:protocol.Info, access:Access):
        assert access.redirect_to is None
        super().__init__()

        self._by_path = fs.StaticDir()
        self.mkchild("f", self._by_path)
        self._by_index = fs.StaticDir()
        self.mkchild("i", self._by_index)

        for spec in info.iter_files():
            self._add_torrent_file(libs, info_hash, spec, access)

    def _add_torrent_file(self, libs:LibraryService, info_hash:str, spec:protocol.FileSpec,
            access:Access):
        if spec.is_pad:
            return
        if spec.is_symlink:
            # TODO
            return

        hints = Hints()
        for name, func in libs.get_hints_funcs.items():
            try:
                hints.update(func(info_hash, spec.index))
            except KeyError:
                pass
            except Exception as e:
                _log.exception("%s: get_hints(%s, %s)", name, info_hash,
                        spec.index)
        hints["filename"] = spec.full_path[-1]
        torrent_file = TorrentFile(opener=libs.opener,
            ref=types.TorrentRef(info_hash=info_hash, start=spec.start, stop=spec.stop),
            get_torrent=access.get_torrent, hints=hints)
        self._by_index.mkchild(str(spec.index), torrent_file)

        if not _is_valid_path(spec.full_path):
            return

        parent = self._try_mkdirs(spec.full_path[:-1])
        if not parent:
            return
        parent.mkchild(spec.full_path[-1], fs.Symlink(target=torrent_file))

    def _try_mkdirs(self, dirnames:List[str]) -> Optional[fs.StaticDir]:
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

    def __init__(self, libs:LibraryService, info_hash:str, info:protocol.Info):
        super().__init__()
        self.libs = libs
        self.info_hash = info_hash
        self.info = info

    def _get_one_access(self, info_hash:str, accessor_name:str) -> Optional[Access]:
        func = self.libs.get_access_funcs.get(accessor_name)
        if not func:
            return None

        try:
            return func(info_hash)
        except KeyError:
            pass
        except Exception:
            _log.exception("%s: get_access(%s)", accessor_name, info_hash)
        return None

    def get_node(self, name:str) -> Optional[fs.Node]:
        access = self._get_one_access(self.info_hash, name)
        if not access:
            return None
        if access.redirect_to:
            return fs.Symlink(target=access.redirect_to)
        else:
            return _V1TorrentAccess(self.libs, self.info_hash, self.info,
                    access)

    def readdir(self) -> Iterator[fs.Dirent]:
        for name in self.libs.get_access_funcs:
            access = self._get_one_access(self.info_hash, name)
            if not access:
                continue
            if access.redirect_to:
                yield fs.Dirent(name=name,
                        stat=fs.Stat(filetype=stat_lib.S_IFLNK))
            else:
                yield fs.Dirent(name=name,
                        stat=fs.Stat(filetype=stat_lib.S_IFDIR))


class _V1(fs.Dir):

    def __init__(self, libs:LibraryService):
        super().__init__(perms=0o444)
        self.libs = libs

    def get_node(self, info_hash: str) -> Optional[fs.Node]:
        info_dict = None
        for name, func in self.libs.get_layout_info_dict_funcs.items():
            try:
                info_dict = func(info_hash)
                break
            except KeyError:
                pass
            except Exception as e:
                _log.exception("%s: get_layout_info_dict(%s)", name, info_hash)
        if not info_dict:
            return None
        return _V1Torrent(self.libs, info_hash, protocol.Info(info_dict))


class _Browse(fs.DictDir):

    def __init__(self, libs:LibraryService):
        super().__init__()
        self.libs = libs

    def get_dict(self):
        return self.libs.browse_nodes


class _Root(fs.StaticDir):

    def __init__(self, libs:LibraryService):
        super().__init__()
        self.mkchild("v1", _V1(libs))
        self.mkchild("browse", _Browse(libs))


@dataclasses.dataclass
class Access:

    redirect_to :Optional[str] = None
    seeders: Optional[int] = None
    get_torrent: Optional[GetTorrent] = None

    def __post_init__(self):
        assert (self.redirect_to is not None) ^ (self.get_torrent is not None)


GetAccess = Callable[[str], Access]
GetBDict = Callable[[str], protocol.BDict]
GetHints = Callable[[str, int], Hints]

class LibraryService:

    def __init__(self, *, opener:TorrentFileOpener=None):
        assert opener is not None
        self.opener = opener
        self.root = _Root(libs=self)
        self.get_access_funcs:Dict[str, GetAccess] = {}
        self.get_layout_info_dict_funcs:Dict[str, GetBDict] = {}
        self.get_hints_funcs:Dict[str, GetHints] = {}
        self.browse_nodes : Dict[str, fs.Node] = {}

    @staticmethod
    def get_torrent_path(info_hash:str) -> Path:
        return Path().joinpath("v1", info_hash)

    def lookup_torrent(self, info_hash:str) -> fs.Node:
        return self.root.traverse(self.get_torrent_path(info_hash))
