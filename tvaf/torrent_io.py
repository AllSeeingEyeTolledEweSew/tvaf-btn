import errno
import io
import mmap
import threading
from typing import List
from typing import Sequence
from typing import Union

from tvaf import ltpy
from tvaf import request as request_lib
from tvaf import types
from tvaf import xmemoryview as xmv

ReadintoTarget = Union[bytearray, mmap.mmap, memoryview]


class BufferedTorrentIO(io.BufferedIOBase):
    # We only implement a BufferedIOBase instead of a BufferedReader around a
    # "raw" IOBase. BufferedReader reads zero-aligned blocks, and trusts the
    # caller to specify a good block size. But torrent pieces are much larger
    # than the typical buffer size and often not zero-aligned.

    # To back up the above claim: I surveyed torrents on BTN, and found 40%
    # have piece size of 1mb or 2mb; and only 1 uses bep47 padding, which
    # indicates most files in multi-file torrents are piece-misaligned.

    def __init__(self, *, request_service: request_lib.RequestService,
                 tslice: types.TorrentSlice, get_torrent: types.GetTorrent,
                 user: str):
        super().__init__()
        self._request_service = request_service
        self._tslice = tslice
        self._get_torrent = get_torrent
        self._user = user

        self._read_lock = threading.RLock()
        self._offset = 0
        self._buffer = xmv.EMPTY

    def seekable(self):
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        with self._read_lock:
            if whence == io.SEEK_SET:
                pass
            elif whence == io.SEEK_CUR:
                offset += self._offset
            elif whence == io.SEEK_END:
                offset += self._tslice.stop - self._tslice.start
            else:
                raise ValueError("Invalid value for whence: %s" % whence)

            if offset != self._offset:
                # TODO(AllSeeingEyeTolledEweSew): maybe update readahead logic
                self._buffer = xmv.EMPTY
                self._offset = offset

            return self._offset

    # TODO(AllSeeingEyeTolledEweSew): maybe cancel readaheads in close()

    def readable(self):
        return True

    def readvec(self, size: int = -1) -> Sequence[memoryview]:
        with self._read_lock:
            return self._readvec_unlocked(size, False)

    def readvec1(self, size: int = -1) -> Sequence[memoryview]:
        with self._read_lock:
            return self._readvec_unlocked(size, True)

    def read(self, size: int = None) -> bytes:
        if size is None:
            size = -1
        # This copies twice. Is there a better way?
        return b"".join(v.tobytes() for v in self.readvec(size))

    def read1(self, size: int = -1) -> bytes:
        # This copies twice. Is there a better way?
        return b"".join(v.tobytes() for v in self.readvec1(size))

    def _readvec_unlocked(self, size: int, read1: bool) -> Sequence[memoryview]:
        # Readahead notes:
        #  - mediainfo http://...mkv
        #    - requests whole file, drops connection when probe is done
        #    - then does range requests, dropping connection on some
        #  - ffprobe -i http://...mkv
        #    - does only range requests
        #    - drops connection on most
        result: List[memoryview] = []

        # By convention, negative size means read all
        if size < 0:
            size = self._tslice.stop - self._offset

        # Clamp size
        size = min(self._tslice.stop - self._offset, size)

        # Consume the buffer
        if self._buffer and size > 0:
            amount = min(len(self._buffer), size)
            result.append(self._buffer[:amount].to_memoryview())
            self._buffer = self._buffer[amount:]
            self._offset += amount
            size -= amount

        if size == 0:
            return result

        # We've consumed the entire buffer, but still need to read more.

        if read1:
            if result:
                return result
            # Only request one byte, which will read exactly one piece.
            stop = self._offset + 1
        else:
            stop = self._offset + size

        # Submit a new request.
        tslice = types.TorrentSlice(info_hash=self._tslice.info_hash,
                                    start=self._offset,
                                    stop=stop)
        params = request_lib.Params(tslice=tslice,
                                    get_torrent=self._get_torrent,
                                    user=self._user,
                                    mode=request_lib.Mode.READ)
        request = self._request_service.add_request(params)

        chunk = xmv.EMPTY
        while request.has_next():
            try:
                # TODO: timeouts
                chunk = request.get_next()
            except OSError:  # pylint: disable=try-except-raise
                # Do this here because ltpy.Error has some subtypes that also
                # inherit OSError.
                raise
            except ltpy.Error as exc:
                raise OSError(errno.EIO, str(exc)) from exc
            except request_lib.CancelledError as exc:
                raise OSError(errno.ECANCELED, str(exc)) from exc
            except request_lib.Error as exc:
                raise OSError(errno.EIO, str(exc)) from exc
            if read1:
                # We requested a 1-byte read. Now expand the chunk, up to the
                # requested size.
                stop = chunk.start + min(size, len(chunk.obj) - chunk.start)
                chunk = xmv.MemoryView(obj=chunk.obj,
                                       start=chunk.start,
                                       stop=stop)
            result.append(chunk.to_memoryview())
            self._offset += len(chunk)
            size -= len(chunk)

        # Save the "leftovers" from the final chunk as our buffer
        self._buffer = xmv.MemoryView(obj=chunk.obj,
                                      start=chunk.stop,
                                      stop=len(chunk.obj))

        return result

    def readinto(self, out: ReadintoTarget) -> int:
        return self._readinto(out, False)

    def readinto1(self, out: ReadintoTarget) -> int:
        return self._readinto(out, True)

    def _readinto(self, out: ReadintoTarget, read1: bool) -> int:
        if isinstance(out, memoryview):
            out = out.cast("B")

        with self._read_lock:
            vec = self._readvec_unlocked(len(out), read1)

        offset = 0
        for buf in vec:
            buflen = len(buf)
            out[offset:offset + buflen] = buf
            offset += buflen
        return offset

    # IOBase.readline() checks if peek exists. We could implement it for faster
    # readline

    # IOBase.fileno() raises OSError, as appropriate
