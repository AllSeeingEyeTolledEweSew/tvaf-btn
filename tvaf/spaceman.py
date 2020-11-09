# pylint: skip-file
"""Spaceman (Space Management) code."""


class Spaceman:
    def __init__(self):
        self.config = None
        self.trackers = None
        self.conn = None

    def is_pinned(self, torrent_status, meta) -> bool:
        assert torrent_status.infohash == meta.infohash
        if not meta.managed:
            return True
        if time.time() < meta.atime + self.config.pin_time:
            return True
        threshold = self.get_seed_threshold(torrent_status.tracker)
        if threshold is not None and torrent_status.seeders < threshold:
            return True
        if self.is_required_for_hnr(torrent_status):
            return True
        return False

    def get_seed_threshold(self, tracker):
        TODO

    def is_required_for_hnr(torrent_status):
        TODO

    def evaluate(self, torrent_status, meta) -> Tuple[bool, float]:
        if self.is_pinned(torrent_status, meta):
            return (True, 0)
        TODO
