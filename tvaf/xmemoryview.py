import collections.abc
import dataclasses
from typing import Union

Target = Union[bytes, bytearray, memoryview]


@dataclasses.dataclass(frozen=True)
class MemoryView(collections.abc.ByteString):
    # This would be memoryview, if we could access the bounds within the
    # backing object. BufferedTorrentIO would like to reuse the underlying
    # object as its buffer.
    obj: Target = b""
    start: int = 0
    stop: int = 0

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step != 1:
                raise NotImplementedError
            start += self.start
            stop += self.start
            # The "full" slice is a common case when reading
            if (start, stop) == (self.start, self.stop):
                return self
            return self.__class__(obj=self.obj, start=start, stop=stop)
        if isinstance(index, int):
            # Not sure if I should use __index__ instead of isinstance(...,int)
            if index >= len(self):
                raise IndexError()
            return self.obj[index % len(self)]
        raise TypeError("%r should be either slice or int" % index)

    def __len__(self) -> int:
        return self.stop - self.start

    def __bytes__(self) -> bytes:
        return self.to_memoryview().tobytes()

    def to_memoryview(self) -> memoryview:
        return memoryview(self.obj)[self.start:self.stop]


# Singleton empty MemoryView, to save a malloc
EMPTY = MemoryView()
