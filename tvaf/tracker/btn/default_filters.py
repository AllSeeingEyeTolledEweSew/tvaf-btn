# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.


class torrent_entry_quality_heuristic_keyer(object):

    RESOLUTION_SCORE = {
        "2160p": 5,
        "1080p": 4,
        "720p": 3,
        "1080i": 2,
        "SD": 1,
        "Portable Device": 0}

    CONTAINER_SCORE = {
        "MKV": 1,
        "AVI": 1,
        "MPEG": 1,
        "MP4": 1,
        "WMV": 1,
        "M4V": 1,
        "TS": 1}

    SOURCE_SCORE = {
        "Bluray": 4,
        "WEB-DL": 3,
        "HDTV": 2,
        "PDTV": 2,
        "WEBRip": 1}

    def key(self, torrent_entry):
        return (
            self.CONTAINER_SCORE.get(torrent_entry.container, -1),
            self.RESOLUTION_SCORE.get(torrent_entry.resolution, -1),
            self.SOURCE_SCORE.get(torrent_entry.source, -1))


class torrent_entry_heuristic_keyer(object):

    DEFAULT_MIN_SEEDERS = 20

    def __init__(self, quality_keyer=None, min_seeders=None):
        if min_seeders is None:
            min_seeders = self.DEFAULT_MIN_SEEDERS
        if quality_keyer is None:
            quality_keyer = torrent_entry_quality_heuristic_keyer()

        self.quality_keyer = quality_keyer
        self.min_seeders = min_seeders

    def key(self, torrent_entry):
        if torrent_entry.seeders > self.min_seeders:
            seeders = self.min_seeders
        else:
            seeders = torrent_entry.seeders
        return (
            seeders, self.quality_keyer.key(torrent_entry),
            torrent_entry.seeders, torrent_entry.id)


def best_with_heuristics(items):
    keyer = torrent_entry_heuristic_keyer()
    items = sorted(items, key=lambda i: keyer.key(i.torrent_entry))
    return [items[-1]]


def most_seeds(items):
    return [sorted(items, key=lambda i: i.torrent_entry.seeders)[-1]]
