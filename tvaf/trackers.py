"""Tracker-level functions for tvaf."""

from __future__ import annotations

import abc
from typing import Iterable
from typing import Optional

from tvaf import app as app_lib
from tvaf import exceptions as exc_lib
from tvaf.types import TorrentEntry


class Tracker(abc.ABC):
    """An abstract base class for functions about a specific tracker.

    Attributes:
        app: Our app instance.
        name: The name of this tracker.
    """

    def __init__(self, app: app_lib.App, name: str) -> None:
        self.app = app
        self.name = name

    @abc.abstractmethod
    def get_torrent_entry(self,
                          torrent_id: Optional[str] = None,
                          infohash: Optional[str] = None) -> TorrentEntry:
        """Get a TorrentEntry.

        Callers should supply only one of id or infohash.

        Args:
            torrent_id: An identifier for the TorrentEntry, in the namespace of
                the tracker.
            infohash: The infohash of the desired TorrentEntry.

        Returns:
            A TorrentEntry.

        Raises:
            exc_lib.TorrentEntryNotFound: If the TorrentEntry wasn't found.
        """
        assert torrent_id is not None or infohash is not None
        assert torrent_id is None or infohash is None


class TrackerService:
    """Tracker-level functions for the tvaf app.

    Attributes:
        app: Our app instance.
        trackers: A dictionary of Trackers by name.
    """

    def __init__(self, app: app_lib.App,
                 trackers: Iterable[Tracker] = ()) -> None:
        self.app = app
        self.trackers = {}
        print("init", trackers)
        for tracker in trackers:
            print("loop", tracker, tracker.name)
            self.trackers[tracker.name] = tracker

    def get(self, name: str) -> Tracker:
        """Get a Tracker by name.

        Args:
            name: The name of the Tracker.

        Returns:
            A Tracker instance.

        Raises:
            exc_lib.TrackerNotFound: If the tracker was not found.
        """
        try:
            return self.trackers[name]
        except KeyError:
            raise exc_lib.TrackerNotFound(name)

    def get_torrent_entry(self,
                          torrent_id: Optional[str] = None,
                          infohash: Optional[str] = None) -> TorrentEntry:
        """Get a TorrentEntry from any tracker.

        Callers should supply only one of id or infohash.

        Args:
            torrent_id: An identifier for the TorrentEntry, in the namespace of
                the tracker.
            infohash: The infohash of the desired TorrentEntry.

        Returns:
            A TorrentEntry.

        Raises:
            exc_lib.TorrentEntryNotFound: If the TorrentEntry wasn't found on
                any tracker.
        """
        assert torrent_id is None or infohash is None
        assert torrent_id is not None or infohash is not None

        # TODO(AllSeeingEyeTolledEweSew): Add a preference of trackers.
        for tracker in self.trackers.values():
            try:
                return tracker.get_torrent_entry(infohash=infohash,
                                                 torrent_id=torrent_id)
            except exc_lib.TorrentEntryNotFound:
                pass

        raise exc_lib.TorrentEntryNotFound(torrent_id or infohash)
