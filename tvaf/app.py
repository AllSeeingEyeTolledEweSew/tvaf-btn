# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""The app linkage code for tvaf."""

import tvaf.audit as audit_lib
import tvaf.db as db_lib
import tvaf.requests as requests_lib
import tvaf.torrents as torrents_lib
import tvaf.trackers as trackers_lib


class App:
    """The tvaf app object.

    The app acts as a container for the various component services.

    Attributes:
        requests: An instance of requests_lib.RequestService.
        torrents: An instance of torrents_lib.TorrentsService.
        audit: An instance of audit_lib.AuditService.
        db: An instance of db_lib.Database.
        trackers: An instance of trackers_lib.TrackerService.
    """

    def __init__(self):
        self.audit = audit_lib.AuditService(self)
        self.db = db_lib.Database(self)
        self.requests = requests_lib.RequestsService(self)
        self.torrents = torrents_lib.TorrentsService(self)
        self.trackers = trackers_lib.TrackerService(self)
