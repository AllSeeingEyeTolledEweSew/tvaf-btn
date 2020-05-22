# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import libtorrent as lt

import hashlib
import random

PIECE_LENGTH = 16384
NAME = b"test.txt"
LEN = PIECE_LENGTH * 9 + 1000
DATA = bytes(random.getrandbits(7) for _ in range(LEN))
PIECES = [DATA[i:i + PIECE_LENGTH] for i in range(0, LEN, PIECE_LENGTH)]

INFO_DICT = {
        b"name": NAME,
        b"piece length": PIECE_LENGTH,
        b"length": len(DATA),
        b"pieces": b"".join(hashlib.sha1(p).digest() for p in PIECES),
    }

DICT = {
    b"info": INFO_DICT,
}

INFOHASH_BYTES = hashlib.sha1(lt.bencode(INFO_DICT)).digest()
INFOHASH = INFOHASH_BYTES.hex()
SHA1_HASH = lt.sha1_hash(INFOHASH_BYTES)


class File:

    def __init__(self, *, data=None, length=None, path=None, path_split=None):
        assert length is not None
        assert path or path_split

        if data is not None:
            assert len(data) == length

        if not path:
            path = b"/".join(path_split)
        if not path_split:
            path_split = path.split(b"/")

        self._data = data
        self.path = path
        self.path_split = path_split
        self.length = length

    @property
    def data(self):
        if self._data is None:
            # 7-bit data to make it easy to work around libtorrent bug #4612
            self._data = bytes(random.getrandbits(7) for _ in
                    range(self.length))
        return self._data


class Torrent:

    @classmethod
    def single_file(cls, *, piece_length=16384, length=None, name=None):
        return cls(piece_length=piece_length, files=[dict(length=length,
            path=name)])

    def __init__(self, *, piece_length=16384, files=None):
        assert piece_length is not None
        assert files

        self.piece_length = piece_length
        self.files = [File(**f) for f in files]
        self.length = sum(f.length for f in self.files)

        self._data = None
        self._pieces = None
        self._info = None
        self._dict = None
        self._infohash_bytes = None

    @property
    def data(self):
        if self._data is None:
            self._data = b"".join(f.data for f in self.files)
        return self._data

    @property
    def pieces(self):
        if self._pieces is None:
            self._pieces = [self.data[i:i + self.piece_length] for i in
                    range(0, self.length, self.piece_length)]
        return self._pieces

    @property
    def info(self):
        if self._info is None:
            self._info = {
                b"piece length": self.piece_length,
                b"length": self.length,
                b"pieces": b"".join(hashlib.sha1(p).digest() for p in
                    self.pieces),
            }

            if len(self.files) == 1:
                self._info[b"name"] = self.files[0].path
            else:
                assert len(set(f.path_split[0] for f in self.files)) == 1
                assert all(len(f.path_split) > 1 for f in self.files)
                self._info[b"name"] = self.files[0].path_split[0]
                self._info[b"files"] = []
                for f in self.files:
                    fdict = {
                        b"length": f.length,
                        b"path": f.path_split[1:],
                    }
                    self._info[b"files"].append(f)
        return self._info

    @property
    def dict(self):
        if self._dict is None:
            self._dict = {
                b"info": self.info,
            }
        return self._dict

    @property
    def infohash_bytes(self):
        if self._infohash_bytes is None:
            self._infohash_bytes = hashlib.sha1(lt.bencode(self.info)).digest()
        return self._infohash_bytes

    @property
    def infohash(self):
        return self.infohash_bytes.hex()

    @property
    def sha1_hash(self):
        return lt.sha1_hash(self.infohash_bytes)

    def ti(self):
        return lt.torrent_info(self.dict)

    def atp(self):
        atp = lt.add_torrent_params()
        atp.ti = self.ti()
        # this is necessary so that
        # atp == read_resume_data(write_resume_data(atp))
        atp.info_hash = self.sha1_hash
        return atp


DEFAULT = Torrent.single_file(piece_length=16384, name=b"test.txt",
        length=16384 * 9 + 1000)
