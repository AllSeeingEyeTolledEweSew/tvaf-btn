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
