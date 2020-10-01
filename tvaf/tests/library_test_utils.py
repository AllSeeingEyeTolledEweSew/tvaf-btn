from typing import Dict
from typing import Sequence
from typing import Tuple

import libtorrent as lt

from tvaf import library
from tvaf import protocol
from tvaf import types

from . import tdummy

SINGLE = tdummy.Torrent.single_file(name=b"test.txt", length=16384 * 9 + 1000)
MULTI = tdummy.Torrent(files=[
    dict(length=10000, path=b"multi/file.tar.gz"),
    dict(length=100, path=b"multi/info.nfo"),
])
PADDED = tdummy.Torrent(files=[
    dict(length=10000, path=b"padded/file.tar.gz"),
    dict(length=6384, path=b"padded/.pad/6834", attr=b"p"),
    dict(length=100, path=b"padded/info.nfo"),
])
CONFLICT_FILE = tdummy.Torrent(files=[
    dict(length=100, path=b"conflict/file.zip"),
    dict(length=200, path=b"conflict/file.zip"),
])
CONFLICT_FILE_DIR = tdummy.Torrent(files=[
    dict(length=100, path=b"conflict/path/file.zip"),
    dict(length=200, path=b"conflict/path"),
])
CONFLICT_DIR_FILE = tdummy.Torrent(files=[
    dict(length=100, path=b"conflict/path"),
    dict(length=200, path=b"conflict/path/file.zip"),
])
BAD_PATHS = tdummy.Torrent(files=[
    dict(length=10, path=b"bad/./file"),
    dict(length=20, path=b"bad/../file"),
    dict(length=30, path_split=[b"bad", b"slash/slash", b"file"]),
])

TORRENTS = (SINGLE, MULTI, PADDED, CONFLICT_FILE, CONFLICT_FILE_DIR,
            CONFLICT_DIR_FILE, BAD_PATHS)


class InfoLibrary(library.PseudoInfoLibrary):

    def __init__(self, *torrents: tdummy.Torrent):
        self.torrents = {torrent.info_hash: torrent for torrent in torrents}

    def get(self,
            info_hash: types.InfoHash,
            exact_paths=False) -> protocol.BDict:
        try:
            return self.torrents[info_hash].info
        except KeyError:
            raise library.UnknownTorrentError(info_hash)


class MetadataLibrary(library.MetadataLibrary):

    def __init__(self, metadata: Dict[Tuple[str, int], library.Metadata]):
        self.metadata = metadata

    def get(self, info_hash: types.InfoHash, file_index: int,
            *names: str) -> library.Metadata:
        return self.metadata.get((info_hash, file_index), library.Metadata())


class Network(library.Network):

    def __init__(self, *torrents: tdummy.Torrent):
        self.torrents = {torrent.info_hash: torrent for torrent in torrents}

    def configure_atp(self, atp: lt.add_torrent_params) -> None:
        info_hash = types.InfoHash(str(atp.info_hash))
        try:
            atp.ti = self.torrents[info_hash].torrent_info()
        except KeyError:
            raise library.UnknownTorrentError(info_hash)

    def match_tracker_url(self, tracker_url: str) -> bool:
        return False

    def scrape(self, info_hash: str) -> library.ScrapeResponse:
        if info_hash in self.torrents:
            return library.ScrapeResponse()
        raise library.UnknownTorrentError(info_hash)


def add_test_libraries(
        libraries: library.Libraries,
        torrents: Sequence[tdummy.Torrent] = None,
        metadata: Dict[Tuple[str, int], library.Metadata] = None) -> None:
    if torrents is None:
        torrents = TORRENTS
    if metadata is None:
        metadata = {
            (SINGLE.info_hash, 0):
                library.Metadata(mime_type="text/plain"),
            (MULTI.info_hash, 0):
                library.Metadata(mime_type="application/x-tar",
                                 content_encoding="gzip"),
            (MULTI.info_hash, 1):
                library.Metadata(mime_type="text/plain"),
        }

    libraries.pseudo_info["test"] = InfoLibrary(*torrents)
    libraries.metadata["test"] = MetadataLibrary(metadata)
    libraries.networks["test"] = Network(*torrents)
