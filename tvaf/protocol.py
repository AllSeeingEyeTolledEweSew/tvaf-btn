from typing import Union
from typing import Any
from typing import Dict
from typing import List
from typing import Iterator
from typing import Optional
import dataclasses

# mypy currently doesn't support cyclic definitions.
#BAny = Union["BDict", "BList", bytes, int]
#BDict = Dict[bytes, BAny]
#BList = List[BAny]
BDict = Dict[bytes, Any]
BList = List[Any]


def decode(bytes_:bytes) -> str:
    return bytes_.decode("utf-8", "surrogateescape")


def encode(str_:str) -> bytes:
    return str_.encode("utf-8", "surrogateescape")


@dataclasses.dataclass
class FileSpec:

    index: int = 0
    start: int = 0
    stop: int = 0
    base_name_bytes: bytes = b""
    path_bytes: List[bytes] = dataclasses.field(default_factory=list)
    attr_bytes: bytes = b""
    target_bytes: List[bytes] = dataclasses.field(default_factory=list)

    @property
    def length(self):
        return self.stop - self.start

    @property
    def is_symlink(self):
        return b"l" in self.attr_bytes

    @property
    def is_hidden(self):
        return b"h" in self.attr_bytes

    @property
    def is_executable(self):
        return b"x" in self.attr_bytes

    @property
    def is_pad(self):
        return b"p" in self.attr_bytes

    @property
    def base_name(self):
        if not hasattr(self, "_base"):
            setattr(self, "_base", decode(self.base_name_bytes))
        return self._base

    @property
    def path(self):
        if not hasattr(self, "_path"):
            setattr(self, "_path", [decode(elem) for elem in
                self.path_bytes])
        return self._path

    @property
    def full_path_bytes(self):
        return [self.base_name_bytes] + self.path_bytes

    @property
    def full_path(self):
        return [self.base_name] + self.path

    @property
    def attr(self):
        if not hasattr(self, "_attr"):
            setattr(self, "_attr", decode(self.attr_bytes))
        return self._attr

    @property
    def target(self):
        if not hasattr(self, "_target"):
            setattr(self, "_target", [decode(elem) for elem in
                self.target_bytes])
        return self._target

    @property
    def full_target_bytes(self):
        return [self.base_name_bytes] + self.target_bytes

    @property
    def full_target(self):
        return [self.base_name] + self.target


class Info:

    def __init__(self, info_dict:BDict):
        self.dict = info_dict

    def iter_files(self) -> Iterator[FileSpec]:
        # libtorrent doesn't even test bep52's 'meta version', it just relies on
        # the bep3-compatible format. we do the same here.
        base_name_bytes = self.dict[b"name"]
        if b"files" in self.dict:
            offset = 0
            for index, file_dict in enumerate(self.dict[b"files"]):
                # length can be absent for symlinks
                length = file_dict.get(b"length", 0)
                path_bytes = file_dict[b"path"]
                attr_bytes = file_dict.get(b"attr", b"")
                if b"l" in attr_bytes:
                    target_bytes = file_dict.get(b"symlink path", [])
                else:
                    target_bytes = []
                yield FileSpec(index=index, start=offset, stop=offset + length,
                        base_name_bytes=base_name_bytes,
                        path_bytes=path_bytes,
                        attr_bytes=attr_bytes,
                        target_bytes=target_bytes)
                offset += length
        else:
            length = self.dict[b"length"]
            attr_bytes = self.dict.get(b"attr", b"")
            yield FileSpec(index=0, start=0, stop=length,
                    base_name_bytes=base_name_bytes, attr_bytes=attr_bytes)
