import logging
import os
import urlparse
import xml.etree.ElementTree as ElementTree


LIBRARY_PATH = os.path.join(
    "Library", "Application Support", "Plex Media Server", "Plug-in Support",
    "Databases", "com.plexapp.plugins.library.db")
PREFERENCES_PATH = os.path.join(
    "Library", "Application Support", "Plex Media Server", "Preferences.xml")

AGENT_NONE = "com.plexapp.agents.none"
AGENT_TVDB = "com.plexapp.agents.thetvdb"


def log():
    return logging.getLogger(__name__)


def get_token(path):
    if "X_PLEX_TOKEN" in os.environ:
        return os.environ["X_PLEX_TOKEN"]
    path = os.path.join(path, PREFERENCES_PATH)
    return ElementTree.parse(path).getroot().get("PlexOnlineToken")


def guid_parent(guid):
    u = urlparse.urlparse(guid)
    if not u.path or u.path == "/":
        return None
    p = u.path.split("/")
    p = p[:len(p) - 1]
    path = "/".join(p)
    return urlparse.urlunparse(
        (u.scheme, u.netloc, path, u.params, u.query, u.fragment))


def guid_child(guid, child_path):
    u = urlparse.urlparse(guid)
    path = u.path
    if not path or path[-1] != "/":
        path += "/"
    while child_path and child_path[0] == "/":
        child_path = child_path[1:]
    path += child_path
    return urlparse.urlunparse(
        (u.scheme, u.netloc, path, u.params, u.query, u.fragment))


class MetadataItem(object):

    TYPE_MOVIE = 1
    TYPE_SHOW = 2
    TYPE_SEASON = 3
    TYPE_EPISODE = 4
    TYPE_ARTIST = 8
    TYPE_ALBUM = 9
    TYPE_TRACK = 10
    TYPE_EXTRA = 12

    EXTRA_TYPE_TRAILER = 1

    type = None
    parent = None
    guid = None
    guid_index = None
    title = None
    default_title = None
    index = None
    originally_available_at = None

    def guid_from_parent(self):
        return guid_child(self.parent.guid, self.guid_index)

    def __repr__(self):
        params = [self.title, self.originally_available_at]
        params = [p for p in params if p is not None]
        if params:
            return "<Meta %s %s>" % (
                self.guid, " ".join("\"%s\"" % p for p in params))
        else:
            return "<Meta %s>" % self.guid


class MediaItem(object):

    metadata_item = None
    tracker = None
    offset = None
    parts = None

    def __repr__(self):
        return "<Media %s: %s%s>" % (
            self.metadata_item, self.parts, 
            " offset=%s" % self.offset if self.offset else "")


class MediaPart(object):

    tracker = None
    torrent_id = None
    index = None
    file_index = None
    path = None
    time = None
    length = None

    def __repr__(self):
        return "<Part %s %s:%s:%s \"%s\">" % (
            self.index, self.tracker, self.torrent_id, self.file_index,
            self.path)
