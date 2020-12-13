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

import dataclasses
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Sequence

# mypy currently doesn't support cyclic definitions.
# BAny = Union["BDict", "BList", bytes, int]
# BDict = Dict[bytes, BAny]
# BList = List[BAny]
BDict = Dict[bytes, Any]
BList = List[Any]


def decode(bytes_: bytes) -> str:
    return bytes_.decode("utf-8", "surrogateescape")


def encode(str_: str) -> bytes:
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
    def length(self) -> int:
        return self.stop - self.start

    @property
    def is_symlink(self) -> bool:
        return b"l" in self.attr_bytes

    @property
    def is_hidden(self) -> bool:
        return b"h" in self.attr_bytes

    @property
    def is_executable(self) -> bool:
        return b"x" in self.attr_bytes

    @property
    def is_pad(self) -> bool:
        return b"p" in self.attr_bytes

    @property
    def base_name(self) -> str:
        return decode(self.base_name_bytes)

    @property
    def path(self) -> Sequence[str]:
        return [decode(elem) for elem in self.path_bytes]

    @property
    def full_path_bytes(self) -> Sequence[bytes]:
        return [self.base_name_bytes] + self.path_bytes

    @property
    def full_path(self) -> Sequence[str]:
        # += typechecks here, but + doesn't. Not sure why.
        result = [self.base_name]
        result += self.path
        return result

    @property
    def attr(self) -> str:
        return decode(self.attr_bytes)

    @property
    def target(self) -> Sequence[str]:
        return [decode(elem) for elem in self.target_bytes]

    @property
    def full_target_bytes(self) -> Sequence[bytes]:
        return [self.base_name_bytes] + self.target_bytes

    @property
    def full_target(self) -> Sequence[str]:
        # += typechecks here, but + doesn't. Not sure why.
        result = [self.base_name]
        result += self.target
        return result


class Info:
    def __init__(self, info_dict: BDict):
        self.dict = info_dict

    def iter_files(self) -> Iterator[FileSpec]:
        # libtorrent doesn't even test bep52's 'meta version', it just relies
        # on the bep3-compatible format. we do the same here.
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
                yield FileSpec(
                    index=index,
                    start=offset,
                    stop=offset + length,
                    base_name_bytes=base_name_bytes,
                    path_bytes=path_bytes,
                    attr_bytes=attr_bytes,
                    target_bytes=target_bytes,
                )
                offset += length
        else:
            length = self.dict[b"length"]
            attr_bytes = self.dict.get(b"attr", b"")
            yield FileSpec(
                index=0,
                start=0,
                stop=length,
                base_name_bytes=base_name_bytes,
                attr_bytes=attr_bytes,
            )
