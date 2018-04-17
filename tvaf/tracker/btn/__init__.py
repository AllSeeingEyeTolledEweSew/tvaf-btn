import hashlib
import logging
import os
import re
import struct
import urlparse

from tvaf import plex as tvaf_plex
from tvaf import scan as tvaf_scan


NAME = "btn"

CATEGORY_EPISODE = "Episode"
CATEGORY_SEASON = "Season"


def log():
    """Gets a module-level logger."""
    return logging.getLogger(__name__)


class Series(tvaf_plex.MetadataItem):

    def __init__(self, series):
        self.series = series

        self._guid = None

    @property
    def type(self):
        return self.TYPE_SHOW

    @property
    def guid(self):
        if self._guid is None:
            if self.series.tvdb_id:
                self._guid = urlparse.urlunparse((
                    tvaf_plex.AGENT_TVDB, "%d" % self.series.tvdb_id, "", None,
                    "lang=en", None))
            else:
                self._guid = urlparse.urlunparse((
                    tvaf_plex.AGENT_NONE, "btn", "%d" % self.series.id, None,
                    None, None))
        return self._guid

    @property
    def title(self):
        if not self.series.tvdb_id:
            return self.series.name

    @property
    def default_title(self):
        return self.series.name


class NumericSeason(tvaf_plex.MetadataItem):

    def __init__(self, series, season):
        self.series = series
        self.season = season

        self._parent = None
        self._guid = None

    @property
    def type(self):
        return self.TYPE_SEASON

    @property
    def parent(self):
        if self._parent is None:
            self._parent = Series(self.series)
        return self._parent

    @property
    def guid(self):
        if self._guid is None:
            self._guid = self.guid_from_parent()
        return self._guid

    @property
    def guid_index(self):
        return "%s" % self.season

    @property
    def index(self):
        return self.season


class GroupSeason(tvaf_plex.MetadataItem):

    def __init__(self, group):
        self.group = group

        self._parent = None
        self._guid = None

    @property
    def type(self):
        return self.TYPE_SEASON

    @property
    def parent(self):
        if self._parent is None:
            self._parent = Series(self.group.series)
        return self._parent

    @property
    def guid(self):
        if self._guid is None:
            self._guid = self.guid_from_parent()
        return self._guid

    @property
    def guid_index(self):
        return "%d" % self.group.id

    @property
    def title(self):
        return self.group.name

    @property
    def index(self):
        return self.group.id


class Episode(tvaf_plex.MetadataItem):

    def __init__(self, group, filename=None, date=None, episode=None,
                 season=None, exact_season=False):
        self.group = group
        self.filename = filename
        self.date = date
        self.episode = episode
        self.season = season
        self.exact_season = exact_season
        assert (self.episode is not None or self.date is not None or
                self.filename is not None or
                self.group.category == CATEGORY_EPISODE)

        self._parent = None
        self._guid = None

    @property
    def type(self):
        return self.TYPE_EPISODE

    @property
    def parent(self):
        if self._parent is None:
            if self.exact_season:
                self._parent = NumericSeason(self.group.series, self.season)
            elif self.group.category == CATEGORY_EPISODE or self.exact_season:
                self._parent = NumericSeason(
                    self.group.series, self.season or 0)
            elif self.group.category == CATEGORY_SEASON:
                self._parent = GroupSeason(self.group)
        return self._parent

    @property
    def guid(self):
        if self._guid is None:
            return self.guid_from_parent()
        return self._guid

    @property
    def guid_index(self):
        if self.date is not None:
            return self.date
        elif self.index is not None:
            return "%d" % self.index

    @property
    def title(self):
        if self.episode is not None:
            return None
        if self.date is not None:
            return None

        if self.group.category == CATEGORY_EPISODE:
            return self.group.name
        elif self.group.category == CATEGORY_SEASON:
            return self.filename

    @property
    def index(self):
        if self.episode is not None:
            return self.episode
        if self.filename is not None:
            # Hash the filename to a 32-bit int, negative so the UI hides it
            sha1 = hashlib.sha1(self.filename.encode()).digest()
            return -abs(struct.unpack("<l", sha1[:4])[0])
        else:
            return self.group.id

    @property
    def originally_available_at(self):
        return self.date


class MediaItem(tvaf_plex.MediaItem):

    def __init__(self, torrent_entry, file_infos, filename=None, date=None,
                 episode=None, season=None, exact_season=None, offset=None):
        self.torrent_entry = torrent_entry
        self.file_infos = file_infos
        self.filename = filename
        self.date = date
        self.episode = episode
        self.season = season
        self.exact_season = exact_season
        self.offset = offset
        assert len(self.file_infos) > 0
        #assert (not self.offset) or len(self.file_infos) == 1

        self._metadata_item = None
        self._parts = None

    @property
    def tracker(self):
        return NAME

    @property
    def metadata_item(self):
        if self._metadata_item is None:
            self._metadata_item = Episode(
                self.torrent_entry.group, filename=self.filename,
                date=self.date, episode=self.episode, season=self.season,
                exact_season=self.exact_season)
        return self._metadata_item

    @property
    def parts(self):
        if self._parts is None:
            self._parts = [
                MediaPart(self.torrent_entry, index, fi)
                for index, fi in enumerate(self.file_infos)]
        return self._parts


class MediaPart(tvaf_plex.MediaPart):

    def __init__(self, torrent_entry, index, file_info):
        self.torrent_entry = torrent_entry
        self.index = index
        self.file_info = file_info

    @property
    def tracker(self):
        return NAME

    @property
    def torrent_id(self):
        return self.torrent_entry.id

    @property
    def file_index(self):
        return self.file_info.index

    @property
    def path(self):
        return self.file_info.path

    @property
    def time(self):
        return self.torrent_entry.time

    @property
    def length(self):
        return self.file_info.length


BTN_FULL_SEASON_REGEX = re.compile(r"Season (?P<season>\d+)$")
BTN_EPISODE_REGEX = re.compile(r"S(?P<season>\d+)(?P<episodes>(E\d+)+)$")
BTN_EPISODE_PART_REGEX = re.compile(r"E(?P<episode>\d+)")
BTN_DATE_EPISODE_REGEX = re.compile(
    r"(?P<y>\d{4})[\.-](?P<m>\d\d)[\.-](?P<d>\d\d)$")
BTN_SEASON_PARTIAL_REGEXES = (
    re.compile(r"Season (?P<season>\d+)"),
    re.compile(r"(?P<season>\d{4})[\.-]\d\d[\.-]\d\d"),
    re.compile(r"S(?P<season>\d+)(E\d+)+"))


class Scanner(object):

    def __init__(self, torrent_entry, debug_scanner=False):
        self.torrent_entry = torrent_entry
        self.debug_scanner = debug_scanner

    def iter_media_items(self):
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

        if self.torrent_entry.group.category == CATEGORY_EPISODE:
            m = BTN_EPISODE_REGEX.match(self.torrent_entry.group.name)
            if m:
                s = int(m.group("season"))
                episodes = m.group("episodes")
                episodes = [
                    int(e)
                    for e in BTN_EPISODE_PART_REGEX.findall(episodes)]
                if all(e != 0 for e in episodes):
                    for i, e in enumerate(episodes):
                        yield MediaItem(
                            self.torrent_entry, fis, episode=e, season=s,
                            exact_season=True, offset=i / len(episodes) * 100)
                    return
            m = BTN_DATE_EPISODE_REGEX.match(self.torrent_entry.group.name)
            if m:
                date = "%s-%s-%s" % (m.group("y"), m.group("m"), m.group("d"))
                yield MediaItem(self.torrent_entry, fis, date=date)
                return
            yield MediaItem(self.torrent_entry, fis)
            return

        if self.torrent_entry.group.category == CATEGORY_SEASON:
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

            for rx in BTN_SEASON_PARTIAL_REGEXES:
                m = rx.match(self.torrent_entry.group.name)
                if m:
                    season = int(m.group("season"))
                    break
            else:
                season = None

            exact_season = bool(BTN_FULL_SEASON_REGEX.match(
                self.torrent_entry.group.name))

            scanner = tvaf_scan.SeriesPathnameScanner(
                fis, known_season=season, known_strings=known_strings,
                debug=self.debug_scanner)

            for mi in scanner.iter_media_items():
                if season is not None and exact_season:
                    mi.details.season = season
                yield MediaItem(
                    self.torrent_entry, mi.parts, episode=mi.details.episode,
                    season=mi.details.season, date=mi.details.date,
                    filename=mi.details.filename, offset=mi.details.offset,
                    exact_season=exact_season)
