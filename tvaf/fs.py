"""Support code for a virtual filesystem of torrents.

The intent is to support both high- and low-level filesystem implementation
systems, like FUSE and SFTP.

Paths and filenames are currently always specified as unicode str objects, as
passed through the "surrogateescape" filter. Bytes objects aren't used.
"""

from __future__ import annotations

import dataclasses
import errno
import stat as stat_lib
import os
import os.path
from typing import Any
from typing import Optional
from typing import Iterator


def _mkoserror(code: int, *args: Any) -> OSError:
    """Returns OSError with a proper error message."""
    return OSError(code, os.strerror(code), *args)


@dataclasses.dataclass
class TorrentRef:
    """A reference to a block of data within a torrent.

    Attributes:
        tracker: The well-known name of the tracker (e.g. "btn").
        torrent_id: The unique id of the torrent in the tracker's local
            namespace.
        start: The offset of the first byte of the referenced data.
        stop: The offset of the last byte of the referenced data, plus one.
    """

    tracker: Optional[str] = None
    torrent_id: Optional[str] = None
    start: Optional[int] = None
    stop: Optional[int] = None


@dataclasses.dataclass
class Stat:
    """A minimal stat structure, as returned by os.stat.

    Attributes:
        filetype: The type of the file. One of the S_IF* constants, currently
            only either S_IFREG or S_IFDIR.
        size: The size of the node.
        mtime: The last-modified time of the node.
    """
    filetype: Optional[int] = 0
    size: Optional[int] = 0
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

    name: Optional[str] = None
    stat: Optional[Stat] = None
    next_offset: Optional[int] = None


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
    """

    def __init__(self,
                 filetype: int = None,
                 size: Optional[int] = None,
                 mtime: Optional[int] = None):
        self.filetype = filetype
        self.size = size
        self.mtime = mtime

    def stat(self) -> Stat:
        """Returns a minimalist Stat for this node."""
        return Stat(filetype=self.filetype, size=self.size, mtime=self.mtime)


def lookup(root: Dir, path: str) -> Node:
    """Recursively look up a node by path.

    Args:
        root: A root directory.
        path: A relative path to another node within the root. Must not be an
            absolute path.

    Returns:
        A Node somewhere in the subtree of this Node.

    Raises:
        FileNotFoundError: If the given path couldn't be found within the root.
        OSError: If some other error occurs.
    """
    path = os.path.normpath(path)
    assert not os.path.isabs(path)
    if path == ".":
        return root
    parts = path.split("/")
    node = root
    while parts:
        node = node.lookup(parts.pop(0))
    return node


class Dir(Node):
    """A virtual directory."""

    def __init__(self, mtime: Optional[int] = None):
        super().__init__(filetype=stat_lib.S_IFDIR, mtime=mtime)

    def lookup(self, name: str) -> Node:
        """Look up a child Node by name.

        Args:
            name: The name of the child.

        Raises:
            FileNotFoundError: If the child Node was not found.
            OSError: If some implementation error occurs.
        """
        # pylint: disable=no-self-use
        raise _mkoserror(errno.ENOSYS)

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
        raise _mkoserror(errno.ENOSYS)


class StaticDir(Dir):
    """A directory with fixed contents that never vary.

    The intent is that the directory structure will be created in the
    constructor.

    Attributes:
        children: A name-to-Node dictionary.
    """

    def __init__(self, mtime: Optional[int] = None):
        super().__init__(mtime=mtime)
        self.children = {}

    def mkchild(self, name: str, node: Node) -> None:
        """Adds a child node."""
        self.children[name] = node

    def lookup(self, name: str) -> Node:
        """Returns a child Node by name."""
        try:
            return self.children[name]
        except KeyError:
            raise _mkoserror(errno.ENOENT, name)

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

    def __init__(self, size: Optional[int] = None, mtime: Optional[int] = None):
        super().__init__(filetype=stat_lib.S_IFREG, size=size, mtime=mtime)

    def get_torrent_ref(self) -> Optional[TorrentRef]:
        """Returns a TorrentRef if this is a torrent-backed file, else None."""
        # pylint: disable=no-self-use
        return None


class TorrentFile(File):
    """A File representing some torrent data.

    Attributes:
        tracker: The well-known name of the tracker (e.g. "btn").
        torrent_id: The unique id of the torrent in the tracker's local
            namespace.
        start: The offset of the first byte of the referenced data.
        stop: The offset of the last byte of the referenced data, plus one.
    """

    def __init__(self,
                 tracker: Optional[str] = None,
                 torrent_id: Optional[str] = None,
                 start: Optional[int] = None,
                 stop: Optional[int] = None,
                 mtime: Optional[int] = None) -> None:
        if start is not None and stop is not None:
            size = stop - start
        else:
            size = None
        super().__init__(size=size, mtime=mtime)
        self.tracker = tracker
        self.torrent_id = torrent_id
        self.start = start
        self.stop = stop

    def get_torrent_ref(self) -> Optional[TorrentRef]:
        """Returns a TorrentRef for this tracker data."""
        return TorrentRef(tracker=self.tracker,
                          torrent_id=self.torrent_id,
                          start=self.start,
                          stop=self.stop)
