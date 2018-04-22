import hashlib
import json
import logging
import os
import re
import struct
import threading
import urlparse

import btn

import tvaf.plex
import tvaf.util


NAME = "btn"

CATEGORY_EPISODE = "Episode"
CATEGORY_SEASON = "Season"


def log():
    """Gets a module-level logger."""
    return logging.getLogger(__name__)


class Series(tvaf.plex.MetadataItem):

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
                    tvaf.plex.AGENT_TVDB, "%d" % self.series.tvdb_id, "", None,
                    "lang=en", None))
            else:
                self._guid = urlparse.urlunparse((
                    tvaf.plex.AGENT_NONE, "btn", "%d" % self.series.id, None,
                    None, None))
        return self._guid

    @property
    def title(self):
        if not self.series.tvdb_id:
            return self.series.name

    @property
    def default_title(self):
        return self.series.name


class NumericSeason(tvaf.plex.MetadataItem):

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


class GroupSeason(tvaf.plex.MetadataItem):

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


class Episode(tvaf.plex.MetadataItem):

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


class MediaItem(tvaf.plex.MediaItem):

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


class MediaPart(tvaf.plex.MediaPart):

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


class Config(object):

    def __init__(self, filter_name=None, yatfs_path=None, btn_cache_path=None,
                 **kwargs):
        self.filter_name = filter_name
        self.yatfs_path = yatfs_path
        self.btn_cache_path = btn_cache_path

        self._lock = threading.RLock()
        self._filter_name_cache = None
        self._filter = None
        self._btn_cache_path_cache = None
        self._api = None

    @property
    def filter(self):
        with self._lock:
            if self._filter_name_cache == self.filter_name:
                return self._filter
            self._filter = tvaf.util.name_to_global(self.filter_name)
            self._filter_name_cache = self.filter_name
            return self._filter

    @property
    def api(self):
        with self._lock:
            if self._btn_cache_path_cache == self.btn_cache_path:
                return self._api
            self._api = btn.API(cache_path=self.btn_cache_path)
            self._btn_cache_path_cache = self.btn_cache_path
            return self._api

    def __eq__(self, o):
        if type(o) is not type(self):
            return False
        return (
            self.filter_name == o.filter_name and
            self.yatfs_path == o.yatfs_path and
            self.btn_cache_path == o.btn_cache_path)

    def __repr__(self):
        return "%s.%s(%s)" % (
            self.__class__.__module__, self.__class__.__name__,
            ", ".join("%s=%r" % (k, v) for k, v in self.to_dict().items()))

    def to_dict(self):
        return dict(
            filter_name=self.filter_name, yatfs_path=self.yatfs_path,
            btn_cache_path=self.btn_cache_path)


class LibrarySection(object):

    KEY_CONFIG = "tvaf_btn_etl_config"
    KEY_SEQUENCE = "tvaf_btn_etl_sequence"

    def __init__(self, library_section):
        self.library_section = library_section

        self._lock = threading.RLock()
        self._config_data_cache = None
        self._config = None

    def get_config(self):
        data = self.library_section.get_setting(self.KEY_CONFIG)
        if not data:
            return None
        data = json.loads(data)
        with self._lock:
            if self._config_data_cache != data:
                self._config = Config(**data)
                self._config_data_cache = data
            return self._config

    def set_config(self, config):
        self.library_section.set_setting(
            self.KEY_CONFIG, json.dumps(config.to_dict()))

    def get_sequence(self):
        sequence = self.library_section.get_setting(self.KEY_SEQUENCE)
        return int(sequence) if sequence is not None else None

    def set_sequence(self, sequence):
        self.library_section.set_setting(self.KEY_SEQUENCE, sequence)
