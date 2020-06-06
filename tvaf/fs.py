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
from typing import Any
from typing import Dict
from typing import Tuple
from typing import List
from typing import Iterator
from typing import Optional
from typing import cast
from typing import Union


Path = pathlib.PurePosixPath
PathLike = Union[str, Path]


def mkoserror(code: int, *args: Any) -> OSError:
    """Returns OSError with a proper error message."""
    return OSError(code, os.strerror(code), *args)


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
    perms: int = -1
    mtime: Optional[int] = None

    def __post_init__(self):
        if self.perms == -1:
            if self.filetype == stat_lib.S_IFDIR:
                self.perms = 0o555
            elif self.filetype == stat_lib.S_IFLNK:
                self.perms = 0o777
            else:
                self.perms = 0o444


@dataclasses.dataclass
class Dirent:
    """A filename entry within a directory.

    Attributes:
        name: The name of the file or directory.
        stat: The stat structure for the file or directory.
    """

    name: str = ""
    stat: Stat = dataclasses.field(default_factory=Stat)


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
                 parent: Dir=None,
                 name: str = None,
                 filetype: int = None,
                 perms: int = None,
                 size: int = None,
                 mtime: int = None):
        self.name = name
        self.parent = parent
        self.filetype = filetype
        self.perms = perms
        self.size = size
        self.mtime = mtime

    def stat(self) -> Stat:
        """Returns a minimalist Stat for this node."""
        assert self.filetype is not None
        return Stat(filetype=self.filetype, perms=self.perms or 0, size=self.size or
                0, mtime=self.mtime)

    def abspath(self) -> Path:
        parts : List[str] = []
        node = self
        while node.parent:
            assert node.name is not None
            parts.append(node.name)
            node = node.parent
        return Path("/").joinpath(*reversed(parts))


def _partial_traverse(cur_dir:Dir, path:Path, follow_symlinks=True) -> Tuple[Node, Path, Optional[OSError]]:
    seen_symlink:Dict[Symlink, Optional[Node]] = {}

    def inner(cur_dir:Dir, path:Path, depth:int) -> Tuple[Node, Path, Optional[OSError]]:
        if path.is_absolute():
            cur_dir = cur_dir.get_root()
            path = path.relative_to("/")

        node:Node = cur_dir
        for i, part in enumerate(path.parts):
            # If we fail before lookup, our remainder includes the current part
            # we failed to lookup.
            rest = lambda: Path().joinpath(*path.parts[i:])

            if node.stat().filetype != stat_lib.S_IFDIR:
                return node, rest(), mkoserror(errno.ENOTDIR)

            cur_dir = cast(Dir, node)
            if part == "..":
                if cur_dir.parent:
                    node = cur_dir.parent
            else:
                try:
                    node = cur_dir.lookup(part)
                except OSError as e:
                    return cur_dir, rest(), e

            # We looked up the next node. From here on, our remainder is
            # whatever we would lookup after this.
            rest = lambda: Path().joinpath(*path.parts[i + 1:])

            # Only do symlink lookup for the final path component if
            # follow_symlinks=True.
            if i == len(path.parts) - 1 and depth == 0 and not follow_symlinks:
                continue

            if node.stat().filetype == stat_lib.S_IFLNK:
                symlink = cast(Symlink, node)
                if symlink in seen_symlink:
                    maybe_node = seen_symlink.get(symlink)
                    if maybe_node is not None:
                        # We resolved this symlink already. Use the cached
                        # value to save recursive calls and node construction.
                        node = maybe_node
                        continue
                    else:
                        # We are trying to resolve this symlink somewhere in
                        # our call stack. We reached it again, so we're in a
                        # symlink loop.
                        return symlink, rest(), mkoserror(errno.ELOOP)
                seen_symlink[symlink] = None

                # Optimization: if symlink.target is a Node, we can use it
                # directly, but we must still recurse to check for loops.
                try:
                    target = symlink.readlink()
                except OSError as e:
                    return symlink, rest(), e

                # Recurse into the symlink.
                node, inner_rest, exc = inner(cur_dir, target, depth + 1)
                if exc:
                    return node, inner_rest.joinpath(rest()), exc
                seen_symlink[symlink] = node

        # Success
        return node, Path(), None

    return inner(cur_dir, path, 0)


class Dir(Node):
    """A virtual directory."""

    def __init__(self, *, perms:int = None, mtime: int = None, size: int = 0):
        super().__init__(filetype=stat_lib.S_IFDIR, perms=perms, mtime=mtime, size=size)

    def stat(self) -> Stat:
        """Returns a default Stat for this node, with current mtime."""
        assert self.filetype is not None
        assert self.size is not None
        return Stat(filetype=self.filetype, perms=self.perms or 0, size=self.size, mtime=self.mtime)

    def get_node(self, name:str) -> Optional[Node]:
        raise mkoserror(errno.ENOSYS)

    def lookup(self, name: str) -> Node:
        """Look up a child Node by name.

        Args:
            name: The name of the child.

        Raises:
            FileNotFoundError: If the child Node was not found.
            OSError: If some implementation error occurs.
        """
        node = self.get_node(name)
        if node is None:
            raise mkoserror(errno.ENOENT)
        node.parent = self
        node.name = name
        return node

    def get_root(self) -> Dir:
        cur = self
        while cur.parent:
            cur = cur.parent
        return cur

    def traverse(self, path: PathLike, follow_symlinks=True) -> Node:
        """Recursively look up a node by path.

        Args:
            path: A relative path to another node within this Dir. Must not be an
                absolute path.

        Returns:
            A Node somewhere in the subtree of this Dir.

        Raises:
            FileNotFoundError: If the given path couldn't be found within the root.
            NotADirectoryError: If a non-terminal part of the path refers to a
                non-directory.
            OSError: If some other error occurs.
        """
        node, rest, e = _partial_traverse(self, Path(path),
                follow_symlinks=follow_symlinks)
        if e:
            raise e
        return node

    def realpath(self, path: PathLike) -> Path:
        node, rest, _ = _partial_traverse(self, Path(path))
        return node.abspath().joinpath(rest)

    def path_to(self, other:Node) -> Path:
        base: Optional[Dir] = self
        ups :List[str] = []
        while base:
            node:Optional[Node] = other
            rparts :List[str] = []
            while node:
                if node is base:
                    return Path().joinpath(*ups).joinpath(*reversed(rparts))
                if node.name is not None:
                    rparts.append(node.name)
                node = node.parent
            ups.append("..")
            base = base.parent
        raise mkoserror(errno.ENOSYS)

    def readdir(self) -> Iterator[Dirent]:
        """List the contents of a directory.

        Yields:
            A Dirent for each directory entry.
        """
        # pylint: disable=no-self-use
        raise mkoserror(errno.ENOSYS)


class DictDir(Dir):

    def get_dict(self) -> Dict[str, Node]:
        raise mkoserror(errno.ENOSYS)

    def get_node(self, name:str) -> Optional[Node]:
        return self.get_dict().get(name)

    def readdir(self) -> Iterator[Dirent]:
        for name, node in self.get_dict().items():
            yield Dirent(name=name, stat=node.stat())



class StaticDir(DictDir):
    """A directory with fixed contents that never vary.

    The intent is that the directory structure will be created in the
    constructor.

    Attributes:
        children: A name-to-Node dictionary.
    """

    def __init__(self, *, mtime: int = None, perms:int = None):
        super().__init__(mtime=mtime, perms=perms)
        self.children: Dict[str, Node] = {}

    def mkchild(self, name:str, node: Node):
        """Adds a child node."""
        node.name = name
        node.parent = self
        self.children[name] = node

    def get_dict(self):
        return self.children


class File(Node):
    """An abstract file.

    The caller should check get_torrent_ref() to see if this is a
    torrent-backed file.

    Reading other files isn't currently implemented.
    """

    def __init__(self, *, perms:int=None, size: int = None, mtime: int = None):
        super().__init__(filetype=stat_lib.S_IFREG, perms=perms, size=size, mtime=mtime)

SymlinkTarget = Union[str, os.PathLike, Node]


class Symlink(Node):

    def __init__(self, *, target:SymlinkTarget=None, perms:int=None, mtime:int=None):
        super().__init__(filetype=stat_lib.S_IFLNK, perms=perms, mtime=mtime, size=0)
        self.target = target

    def stat(self) -> Stat:
        """Returns a minimalist Stat for this node."""
        assert self.filetype is not None
        return Stat(filetype=self.filetype, perms=self.perms or 0,
                size=len(str(self.readlink())), mtime=self.mtime)

    def readlink(self) -> Path:
        if self.target is None:
            raise mkoserror(errno.ENOSYS)
        if isinstance(self.target, Node):
            if self.parent is None:
                raise mkoserror(errno.ENOSYS)
            return self.parent.path_to(self.target)
        return Path(os.fspath(self.target))
