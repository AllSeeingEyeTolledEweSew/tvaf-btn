"""Support code for a virtual filesystem of torrents.

The intent is to support both high- and low-level filesystem implementation
systems, like FUSE and SFTP.

Paths and filenames are currently always specified as unicode str objects, as
passed through the "surrogateescape" filter. Bytes objects aren't used.
"""

from __future__ import annotations

import dataclasses
import errno
import os
import os.path
import stat as stat_lib
import pathlib
import time
from typing import Any
from typing import Dict
from typing import Iterator
from typing import Optional
from typing import cast


def mkoserror(code: int, *args: Any) -> OSError:
    """Returns OSError with a proper error message."""
    return OSError(code, os.strerror(code), *args)


@dataclasses.dataclass
class TorrentRef:
    """A reference to a block of data within a torrent.

    Attributes:
        tracker: The well-known name of the tracker (e.g. "btn").
        infohash: The infohash of the torrent.
        start: The offset of the first byte of the referenced data.
        stop: The offset of the last byte of the referenced data, plus one.
    """

    tracker: str = ""
    infohash: str = ""
    start: int = 0
    stop: int = 0


@dataclasses.dataclass
class Stat:
    """A minimal stat structure, as returned by os.stat.

    Attributes:
        filetype: The type of the file. One of the S_IF* constants, currently
            only either S_IFREG or S_IFDIR.
        size: The size of the node.
        mtime: The last-modified time of the node.
    """
    filetype: int = 0
    size: int = 0
    mtime: Optional[int] = 0


@dataclasses.dataclass
class Dirent:
    """A filename entry within a directory.

    Attributes:
        name: The name of the file or directory.
        stat: The stat structure for the file or directory.
        next_offset: The offset of the next dirent after this one. See
            Dir.readdir().
    """

    name: str = ""
    stat: Stat = dataclasses.field(default_factory=Stat)
    next_offset: int = 0


class Node:
    """A top-level abstract class for directories and files of all types.

    Attributes:
        filetype: The filetype field of stat(). One of the S_IF* constants.
        size: If not None, the fixed size of this file. Otherwise, file size
            may be determined by calling stat() (but may be None for
            directories).
        mtime: If not None, the fixed mtime field of stat(). Otherwise, mtime
            may be determined by calling stat() (but may be None if
            unspecified).
        parent: The parent directory. This is only necessary when using
            symlinks whose target is a Node. Always None for root directories.
        name: The canonical name of this file within its parent directory. This
            is used for symlinks whose target is a Node. Always None for root
            directories.
    """

    def __init__(self,
                 *,
                 parent: Optional[fs.Dir]=None,
                 name: Optional[str] = None,
                 filetype: int = None,
                 size: Optional[int] = None,
                 mtime: Optional[int] = None):
        self.name = name
        self.parent = parent
        self.filetype = filetype
        self.size = size
        self.mtime = mtime

    def stat(self) -> Stat:
        """Returns a minimalist Stat for this node."""
        assert self.filetype is not None
        assert self.size is not None
        return Stat(filetype=self.filetype, size=self.size, mtime=self.mtime)


def lookup(root: Dir, path: Union[os.PathLike, str]) -> Node:
    """Recursively look up a node by path.

    Args:
        root: A root directory.
        path: A relative path to another node within the root. Must not be an
            absolute path.

    Returns:
        A Node somewhere in the subtree of this Node.

    Raises:
        FileNotFoundError: If the given path couldn't be found within the root.
        NotADirectoryError: If a non-terminal part of the path refers to a
            non-directory.
        OSError: If some other error occurs.
        ValueError: If the given path is absolute.
    """
    path = pathlib.PurePath(path)
    if path.is_absolute():
        raise ValueError(path)
    node: Node = root
    for part in path.parts:
        if node.stat().filetype != stat_lib.S_IFDIR:
            raise mkoserror(errno.ENOTDIR)
        cur_dir = cast(Dir, node)
        node = cur_dir.lookup(part)
    return node


class Dir(Node):
    """A virtual directory."""

    def __init__(self, *, name:Optional[str]=None,
            parent:Optional[fs.Dir]=None, mtime: Optional[int] = None, size: Optional[int] = 0):
        super().__init__(filetype=stat_lib.S_IFDIR, name=name, parent=parent, mtime=mtime, size=size)

    def stat(self) -> Stat:
        """Returns a default Stat for this node, with current mtime."""
        assert self.filetype is not None
        assert self.size is not None
        mtime = self.mtime
        if mtime is None:
            mtime = int(time.time())
        return Stat(filetype=self.filetype, size=self.size, mtime=mtime)

    def lookup(self, name: str) -> Node:
        """Look up a child Node by name.

        Args:
            name: The name of the child.

        Raises:
            FileNotFoundError: If the child Node was not found.
            OSError: If some implementation error occurs.
        """
        # pylint: disable=no-self-use
        raise mkoserror(errno.ENOSYS)

    def readdir(self, offset: int = 0) -> Iterator[Dirent]:
        """List the contents of a directory.

        If offset is 0 (the default), the result will start with the first
        directory entry.

        The next_offset field of each Dirent may be passed as the offset. If
        next_offset is used, readdir will return directory entries starting
        with the next entry after the Dirent whose next_offset was used.

        Any other values passed as offset are invalid and may result in
        undefined behavior.

        Args:
            offset: An offset to start reading.

        Yields:
            A Dirent for each directory entry.
        """
        # pylint: disable=no-self-use
        raise mkoserror(errno.ENOSYS)


class StaticDir(Dir):
    """A directory with fixed contents that never vary.

    The intent is that the directory structure will be created in the
    constructor.

    Attributes:
        children: A name-to-Node dictionary.
    """

    def __init__(self, *, name:Optional[str]=None,
            parent:Optional[fs.Dir]=None, mtime: Optional[int] = None):
        super().__init__(name=name, parent=parent, mtime=mtime)
        self.children: Dict[str, Node] = {}

    def mkchild(self, node: Node, name:Optional[str]=None) -> None:
        """Adds a child node."""
        if name is None:
            name = node.name
        assert name is not None
        if node.parent is None:
            node.parent = self
        self.children[name] = node

    def lookup(self, name: str) -> Node:
        """Returns a child Node by name."""
        try:
            return self.children[name]
        except KeyError:
            raise mkoserror(errno.ENOENT, name)

    def readdir(self, offset: int = 0) -> Iterator[Dirent]:
        """Yields all child directory entries."""
        dirents = []
        for i, (name, node) in enumerate(sorted(self.children.items())):
            dirents.append(
                Dirent(name=name, stat=node.stat(), next_offset=i + 1))
        return iter(dirents[offset:])


class File(Node):
    """An abstract file.

    The caller should check get_torrent_ref() to see if this is a
    torrent-backed file.

    Reading other files isn't currently implemented.
    """

    def __init__(self, *, name:Optional[str]=None,
            parent:Optional[fs.Dir]=None, size: Optional[int] = None, mtime: Optional[int] = None):
        super().__init__(filetype=stat_lib.S_IFREG, name=name, parent=parent, size=size, mtime=mtime)

    def get_torrent_ref(self) -> Optional[TorrentRef]:
        """Returns a TorrentRef if this is a torrent-backed file, else None."""
        # pylint: disable=no-self-use
        return None


class Symlink(Node):

    def __init__(self, *, name:Optional[str]=None,
            parent:Optional[fs.Dir]=None, target:Optional[Union[str,
                os.PathLike, fs.Node]]=None, mtime:Optional[int]=None):
        super().__init__(filetype=stat_lib.S_IFLNK, name=name, parent=parent,
                mtime=mtime)
        self.target = target

    def readlink(self) -> pathlib.PurePath:
        if self.target is None:
            raise mkoserror(errno.ENOSYS)
        if isinstance(self.target, Node):
            base = self.parent
            parts = []
            while base is not None:
                node = self.target
                rparts = []
                while node and (node is not base):
                    if not node.name:
                        break
                    rparts.append(node.name)
                    node = node.parent
                if node is base:
                    break
                parts.append("..")
                base = base.parent
            if base is None:
                raise mkoserror(errno.ENOSYS)
            rparts.reverse()
            parts += rparts
            return pathlib.PurePath().joinpath(*parts)
        return pathlib.PurePath(os.fspath(self.target))


class TorrentFile(File):
    """A File representing some torrent data.

    Attributes:
        tracker: The well-known name of the tracker (e.g. "btn").
        infohash: The infohash of the torrent.
        start: The offset of the first byte of the referenced data.
        stop: The offset of the last byte of the referenced data, plus one.
    """

    def __init__(self,
                 tracker: Optional[str] = None,
                 infohash: Optional[str] = None,
                 start: Optional[int] = None,
                 stop: Optional[int] = None,
                 mtime: Optional[int] = None) -> None:
        size: Optional[int] = None
        if start is not None and stop is not None:
            size = stop - start
        super().__init__(size=size, mtime=mtime)
        self.tracker = tracker
        self.infohash = infohash
        self.start = start
        self.stop = stop

    def get_torrent_ref(self) -> Optional[TorrentRef]:
        """Returns a TorrentRef for this tracker data."""
        assert self.tracker is not None
        assert self.infohash is not None
        assert self.start is not None
        assert self.stop is not None
        return TorrentRef(tracker=self.tracker,
                          infohash=self.infohash,
                          start=self.start,
                          stop=self.stop)
