import contextlib
import logging
import os
import threading
import time
import urlparse
import xml.etree.ElementTree as ElementTree

import apsw


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


class PlexDatabase(object):

    @classmethod
    def _create_schema(cls, conn):
        with conn:
            conn.cursor().execute(
                "create table if not exists tvaf_library_section_settings ("
                "id integer not null, "
                "name text not null,"
                "value text not null)")
            conn.cursor().execute(
                "create unique index if not exists "
                "tvaf_library_section_settings_id_name "
                "on tvaf_library_section_settings (id, name)")
            conn.cursor().execute(
                "create table if not exists tvaf_metadata ("
                "id integer primary key, "
                "tracker text, "
                "torrent_id integer, "
                "first_file_index integer, "
                "offset integer)")
            conn.cursor().execute(
                "create index if not exists tvaf_metadata_on_tracker_tid_idx "
                "on tvaf_metadata (tracker, torrent_id, first_file_index)")


    def __init__(self, plex_path, busy_timeout=120000):
        self.plex_path = plex_path

        self._local = threading.local()
        self._busy_timeout = busy_timeout

    @property
    def path(self):
        return os.path.join(self.plex_path, LIBRARY_PATH)

    @property
    def conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = apsw.Connection(self.path)
        conn.setbusytimeout(self._busy_timeout)
        self._local.conn = conn
        self.__class__._create_schema(conn)
        return conn

    @contextlib.contextmanager
    def begin(self):
        start = time.time()
        self.conn.cursor().execute("begin immediate")
        end = time.time()
        delta = (end - start) * 1000
        if delta > 100:
            log().debug("BEGIN IMMEDIATE took %dms", delta)
        try:
            yield
        except:
            start = time.time()
            self.conn.cursor().execute("rollback")
            end = time.time()
            delta = (end - start) * 1000
            if delta > 100:
                log().debug("ROLLBACK took %dms", delta)
            raise
        else:
            start = time.time()
            self.conn.cursor().execute("commit")
            end = time.time()
            delta = (end - start) * 1000
            if delta > 100:
                log().debug("COMMIT took %dms", delta)


class LibrarySection(object):

    def __init__(self, db, name=None, id=None):
        self.db = db
        assert id or name
        self._name = name
        self._id = id

    @property
    def id(self):
        if self._id is not None:
            return self._id
        r = self.db.conn.cursor().execute(
            "select id from library_sections where name = ?",
            (self.name,)).fetchone()
        assert r, "library section doesn't exist"
        self._id = r[0]
        return self._id

    @property
    def name(self):
        if self._name is not None:
            return self._name
        r = self.db.conn.cursor().execute(
            "select name from library_sections where id = ?",
            (self.id,)).fetchone()
        assert r, "library section doesn't exist"
        self._name = r[0]
        return self._name

    def __str__(self):
        return "<LibrarySection %d \"%s\">" % (self.id, self.name)

    def get_setting(self, name):
        row = self.db.conn.cursor().execute(
            "select value from tvaf_library_section_settings where id = ? and "
            "name = ?", (self.id, name,)).fetchone()
        return row[0] if row else None

    def set_setting(self, name, value):
        with self.db.conn:
            self.db.conn.cursor().execute(
                "insert or replace into tvaf_library_section_settings "
                "(id, name, value) values (?, ?, ?)",
                (self.id, name, value))

    def delete_setting(self, name):
        with self.db.conn:
            self.db.conn.cursor().execute(
                "delete from tvaf_library_section_settings where "
                "id = ? and name = ?", (self.id, name,))
