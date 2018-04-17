# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import logging
import os
import re
import threading

import tvaf.scan
import tvaf.tracker.btn as tvaf_btn


def log():
    """Gets a module-level logger."""
    return logging.getLogger(__name__)


class Matcher(object):

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

    def match_episode_by_date_request(self, series_id, date):
        key = (series_id, date)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            f = self.thread_pool.submit(
                self.match_episode_by_date, series_id, date)
            self._cache[key] = f
            return f


class Scanner(object):

    BTN_FULL_SEASON_REGEX = re.compile(r"Season (?P<season>\d+)$")
    BTN_EPISODE_REGEX = re.compile(r"S(?P<season>\d+)(?P<episodes>(E\d+)+)$")
    BTN_EPISODE_PART_REGEX = re.compile(r"E(?P<episode>\d+)")
    BTN_DATE_EPISODE_REGEX = re.compile(
        r"(?P<y>\d{4})[\.-](?P<m>\d\d)[\.-](?P<d>\d\d)$")
    BTN_SEASON_PARTIAL_REGEXES = (
        re.compile(r"Season (?P<season>\d+)"),
        re.compile(r"(?P<season>\d{4})[\.-]\d\d[\.-]\d\d"),
        re.compile(r"S(?P<season>\d+)(E\d+)+"))

    def __init__(self, torrent_entry, matcher, debug_scanner=False):
        self.torrent_entry = torrent_entry
        self.matcher = matcher
        self.debug_scanner = debug_scanner

    def iter_media_items(self):
        mi_futures = []
        for mi in self.iter_media_items_inner():
            tvdb_id = mi.torrent_entry.group.series.tvdb_id
            if mi.date and tvdb_id:
                f = self.matcher.match_episode_by_date_request(
                    tvdb_id, mi.date)
                mi_futures.append((mi, f))
            else:
                yield mi
        for mi, f in mi_futures:
            response = f.result()
            episodes = response.get("data")
            if not episodes:
                log().error(
                    "No match for series %s date %s",
                    mi.torrent_entry.group.series.tvdb_id, mi.date)
            else:
                def episode_key(episode):
                    s = episode["airedSeason"]
                    e = episode["airedEpisodeNumber"]
                    return (s != 0, s, e)
                episodes = sorted(episodes, key=episode_key)
                episode = episodes[0]
                log().info(
                    "Matched series %s date %s -> (%s, %s)",
                    mi.torrent_entry.group.series.tvdb_id, mi.date,
                    episode["airedSeason"], episode["airedEpisodeNumber"])
                mi.date = None
                mi.filename = None
                mi.episode = episode["airedEpisodeNumber"]
                mi.season = episode["airedSeason"]
                mi.exact_season = episode["airedSeason"]
                yield mi

    def iter_media_items_inner(self):
        if self.torrent_entry.container in ("VOB", "M2TS", "ISO"):
            return

        fis = []
        for fi in self.torrent_entry.file_info_cached:
            path = fi.path
            # Filter out files which don't seem to match the labeled container
            container = self.torrent_entry.container
            if container not in ("", "---"):
                _, ext = os.path.splitext(path)
                ext = os.fsencode(os.fsdecode(ext).lower())
                ext = {b".mpg": b".mpeg"}.get(ext) or ext
                if ext != b"." + container.lower().encode():
                    continue
            fis.append(fi)

        if not fis:
            return

        if self.torrent_entry.group.category == tvaf_btn.CATEGORY_EPISODE:
            m = self.BTN_EPISODE_REGEX.match(self.torrent_entry.group.name)
            if m:
                s = int(m.group("season"))
                episodes = m.group("episodes")
                episodes = [
                    int(e)
                    for e in self.BTN_EPISODE_PART_REGEX.findall(episodes)]
                if all(e != 0 for e in episodes):
                    for i, e in enumerate(episodes):
                        yield tvaf_btn.MediaItem(
                            self.torrent_entry, fis, episode=e, season=s,
                            exact_season=True, offset=i / len(episodes) * 100)
                    return
            m = self.BTN_DATE_EPISODE_REGEX.match(
                self.torrent_entry.group.name)
            if m:
                date = "%s-%s-%s" % (m.group("y"), m.group("m"), m.group("d"))
                yield tvaf_btn.MediaItem(self.torrent_entry, fis, date=date)
                return
            yield tvaf_btn.MediaItem(self.torrent_entry, fis)
            return

        if self.torrent_entry.group.category == tvaf_btn.CATEGORY_SEASON:
            known_strings = [
                self.torrent_entry.codec, self.torrent_entry.resolution,
                self.torrent_entry.source]

            if self.torrent_entry.resolution[-1] in ("i", "p"):
                known_strings.append(self.torrent_entry.resolution[:-1])

            if self.torrent_entry.source in (
                    "Bluray", "BD50", "BDRip", "BRRip"):
                known_strings.extend([
                    "blu-ray", "bluray", "blu ray", "blu_ray", "blu.ray",
                    "blue-ray", "blueray", "blue ray", "blue_ray",
                    "blue.ray"])
            if self.torrent_entry.source in ("WEB-DL", "WEBRip"):
                known_strings.append("WEB")

            for rx in self.BTN_SEASON_PARTIAL_REGEXES:
                m = rx.match(self.torrent_entry.group.name)
                if m:
                    season = int(m.group("season"))
                    break
            else:
                season = None

            exact_season = bool(self.BTN_FULL_SEASON_REGEX.match(
                self.torrent_entry.group.name))

            scanner = tvaf.scan.SeriesPathnameScanner(
                fis, known_season=season, known_strings=known_strings,
                debug=self.debug_scanner)

            for mi in scanner.iter_media_items():
                if season is not None and exact_season:
                    mi.details.season = season
                yield tvaf_btn.MediaItem(
                    self.torrent_entry, mi.parts, episode=mi.details.episode,
                    season=mi.details.season, date=mi.details.date,
                    filename=mi.details.filename, offset=mi.details.offset,
                    exact_season=exact_season)
