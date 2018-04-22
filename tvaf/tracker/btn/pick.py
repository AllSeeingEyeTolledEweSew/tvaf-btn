# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import collections
import contextlib
import logging
import threading

import promise

import tvaf.tracker.btn
import tvaf.tracker.btn.scan


def log():
    return logging.getLogger(__name__)


class Resolver(object):

    def __init__(self, tvdb, thread_pool):
        self.tvdb = tvdb
        self.thread_pool = thread_pool
        self._lock = threading.RLock()
        self._cache = {}

    def match_episode_by_date(self, series_id, date):
        r = self.tvdb.get(
            "/series/%d/episodes/query" % series_id,
            params={"firstAired": date})
        assert r.status_code in (200, 404), r.text
        return r.json()

    def match_episode_by_date_promise(self, series_id, date):
        key = (series_id, date)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            f = self.thread_pool.submit(
                self.match_episode_by_date, series_id, date)
            p = promise.Promise.cast(f)
            self._cache[key] = p
            return p

    def need_to_resolve(self, item):
        return bool(item.date and item.torrent_entry.group.series.tvdb_id)

    def resolve_promise(self, item):
        tvdb_id = item.torrent_entry.group.series.tvdb_id
        p = self.match_episode_by_date_promise(tvdb_id, item.date)
        def got_response(response):
            episodes = response.get("data")
            if not episodes:
                log().error(
                    "No match for series %s date %s", tvdb_id, item.date)
                return [item.__class__(
                    item.torrent_entry, item.file_infos, filename=item.date,
                    offset=item.offset)]

            def episode_key(episode):
                s = episode["airedSeason"]
                e = episode["airedEpisodeNumber"]
                return (s != 0, s, e)
            episodes = sorted(episodes, key=episode_key)
            episode = episodes[0]
            episode_number = episode["airedEpisodeNumber"]
            season_number = episode["airedSeason"]
            log().debug(
                "Matched series %s date %s -> (%s, %s)",
                tvdb_id, item.date, season_number, episode_number)
            return [item.__class__(
                item.torrent_entry, item.file_infos, episode=episode_number,
                season=season_number, exact_season=season_number,
                offset=item.offset)]
        p = p.then(got_response)
        return p


class WholeSeriesPicker(object):

    def __init__(self, torrents, config, tvdb, thread_pool, debug=False):
        self.torrents = torrents
        self.config = config
        self.resolver = Resolver(tvdb, thread_pool)
        self.debug = debug

        self._guid_to_items = {}
        self._torrent_id_to_items = {}

    def name(self):
        return tvaf.tracker.btn.NAME

    def guid_to_items(self):
        return self._guid_to_items

    def torrent_id_to_items(self):
        return self._torrent_id_to_items

    def scan(self, torrent_entry):
        return tvaf.tracker.btn.scan.Scanner(
            torrent_entry, debug=self.debug).iter_media_items()

    def pick(self):
        log().info("Picking batch with %s torrents", len(self.torrents))

        items = []
        item_promises = []

        self._torrent_id_to_items = {}
        for torrent_entry in self.torrents:
            self._torrent_id_to_items[torrent_entry.id] = []
            if self.debug:
                log().debug("%s:", torrent_entry)
            for item in self.scan(torrent_entry):
                if self.debug:
                    log().debug("    %s", item)
                if self.resolver.need_to_resolve(item):
                    item_promises.append(
                        self.resolver.resolve_promise(item))
                else:
                    items.append(item)

        for promise in item_promises:
            for item in promise.get():
                items.append(item)

        self._guid_to_items = collections.defaultdict(list)
        for item in items:
            self._guid_to_items[item.metadata_item.guid].append(item)
        for guid, items in list(self._guid_to_items.items()):
            self._guid_to_items[guid] = self.config.filter(items)

        if self.debug:
            for guid, items in sorted(self._guid_to_items.items()):
                log().debug("%s -> %s", guid, items)

        for items in self._guid_to_items.values():
            for item in items:
                torrent_id = item.torrent_entry.id
                self._torrent_id_to_items[torrent_id].append(item)
