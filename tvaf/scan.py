import itertools
import logging
import os
import re

from plex_scanners.Common import Stack as plex_stack
from plex_scanners.Common import VideoFiles as plex_video_files
from plex_scanners.Series import PlexSeriesScanner as plex_series_scanner


def log():
    return logging.getLogger(__name__)


PLEX_EPISODE_REGEXPS = tuple(
    re.compile(r, flags=re.IGNORECASE)
    for r in plex_series_scanner.episode_regexps)
PLEX_DATE_REGEXPS = tuple(
    re.compile(r) for r in plex_series_scanner.date_regexps)
PLEX_STANDALONE_EPISODE_REGEXPS = tuple(
    re.compile(r)
    for r in plex_series_scanner.standalone_episode_regexs)
PLEX_JUST_EPISODE_REGEXPS = tuple(
    re.compile(r, flags=re.IGNORECASE)
    for r in plex_series_scanner.just_episode_regexs)
PLEX_STARTS_WITH_EPISODE_NUMBER_REGEX = re.compile(r"^[0-9]+[ -]")


class MediaItem(object):

    def __init__(self, details, parts):
        self.details = details
        self.parts = parts


class SeriesDetails(object):

    def __init__(self, season=None, episode=None, offset=None, date=None,
                 filename=None):
        self.season = season
        self.episode = episode
        self.offset = offset
        self.date = date
        self.filename = filename


class SeriesPathnameScanner(object):

    def __init__(self, items, known_season=None, known_strings=None,
                 debug=False):
        self.items = items
        self.should_stack = True
        self.known_season = known_season
        self.known_strings = known_strings or []
        self.debug = debug

    def iter_details_for_name(self, name):
        if self.debug:
            log().debug("input: %s", name)
        name, ext = os.path.splitext(name)
        
        if not any(rx.search(name) for rx in itertools.chain(
                PLEX_EPISODE_REGEXPS[:-1],
                PLEX_STANDALONE_EPISODE_REGEXPS)):
            if self.debug:
                log().debug("...trying dates")
            for rx in PLEX_DATE_REGEXPS:
                m = rx.search(name)
                if not m:
                    continue
                if self.debug:
                    log().debug("......matched date: %s", rx)

                y, m, d = (
                    int(m.group("year")), int(m.group("month")),
                    int(m.group("day")))
                yield SeriesDetails(date="%04d-%02d-%02d" % (y, m, d))
                return

        _, year = plex_video_files.CleanName(name)
        if year != None:
            if self.debug:
                log().debug("...removing year: %s", year)
            name = name.replace(str(year), "XXXX")

        for s in self.known_strings:
            name = re.sub(re.escape(s), " ", name, flags=re.IGNORECASE)

        cleanName, _ = plex_video_files.CleanName(name)

        if self.debug:
            log().debug("...cleaned name to: %s", name)

        for i, rx in enumerate(PLEX_EPISODE_REGEXPS):
            m = rx.search(name)
            if not m:
                continue
            s = m.group("season")
            s = 0 if s.lower() == "sp" else int(s)
            e_start = int(m.group("ep"))
            e_end = e_start
            if "secondEp" in m.groupdict() and m.group("secondEp"):
                e_end = int(m.group("secondEp"))

            if self.debug:
                log().debug("......matches %s: (%s, %s, %s)",
                    rx, s, e_start, e_end)

            if i == len(PLEX_EPISODE_REGEXPS) - 1:
                if s == 0:
                    if self.debug:
                        log().debug(".........weak rx season 0, ignoring")
                    continue
                if self.known_season is not None and s != self.known_season:
                    if PLEX_STARTS_WITH_EPISODE_NUMBER_REGEX.match(name):
                        if self.debug:
                            log().debug(
                                ".........weak rx season mismatch looks like episode, ignoring")
                        continue
                    if self.debug:
                        log().debug(
                            ".........weak rx season mismatch assuming 100s")
                    e_start = s * 100 + e_start
                    if e_end:
                        e_end = s * 100 + e_end
                    s = None
                      
            for e in range(e_start, e_end + 1):
                if e_start != e_end:
                    offset = (e - e_start) / (e_end - e_start + 1) * 100
                else:
                    offset = None
                yield SeriesDetails(
                    season=s, episode=e, offset=offset, filename=cleanName)
            return

        name = cleanName

        if self.debug:
            log().debug("...further cleaned to: %s", name)

        for i, rx in enumerate(PLEX_JUST_EPISODE_REGEXPS):
            m = rx.search(name)
            if not m:
                continue
            e = int(m.group("ep"))
            if self.debug:
                log().debug("......matched %s: %s", rx, e)
            s = None
            if self.known_season:
                s = self.known_season
                if e >= 100 and e // 100 == s:
                    if self.debug:
                        log().debug(".........matched known season 100s")
                    e = e % 100

            if i == 0:
                self.should_stack = False

            yield SeriesDetails(season=s, episode=e, filename=name)
            return

        if self.debug:
            log().debug("...got nothing.")
        yield SeriesDetails(filename=name)

    def iter_media_items(self):
        path_to_item = {os.fsdecode(i.path): i for i in self.items}
        mis = []
        for item in self.items:
            name = os.path.basename(os.fsdecode(item.path))
            for d in self.iter_details_for_name(name):
                mis.append(MediaItem(d, [os.fsdecode(item.path)]))
        if self.should_stack:
            plex_stack.Scan(None, None, mis, None)
        for mi in mis:
            mi.parts = [path_to_item[p] for p in mi.parts]
        return mis
