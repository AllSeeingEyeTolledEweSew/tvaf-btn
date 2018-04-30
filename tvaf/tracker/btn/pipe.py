import logging
import time

import tvaf.checkpoint
import tvaf.sync
import tvaf.tracker.btn
import tvaf.tracker.btn.pick


def log():
    return logging.getLogger(__name__)


class ContinuousIncrementalPipe(object):

    def __init__(self, btn_library, tvdb=None, thread_pool=None, debug=False,
                 reset=False, transaction_size=None, pretend=False,
                 plex_host=None):
        self.btn_library = btn_library
        self.library_section = btn_library.library_section
        self.config = self.btn_library.get_config()
        self.tvdb = tvdb
        self.thread_pool = thread_pool
        self.debug = debug
        self.reset = reset
        self.transaction_size = transaction_size
        self.pretend = pretend
        self.plex_host = plex_host

    def get_series_torrents(self, series_id):
        c = self.config.api.db.cursor()
        c.execute(
            "select torrent_entry.id from torrent_entry "
            "inner join torrent_entry_group on "
            "torrent_entry.group_id = torrent_entry_group.id "
            "inner join series on "
            "torrent_entry_group.series_id = series.id "
            "where (not torrent_entry.deleted) and "
            "series.id = ?", (series_id,))
        return [self.config.api.getTorrentByIdCached(r[0]) for r in c]

    def get_deleted_torrent_ids(self, from_changestamp, to_changestamp):
        c = self.config.api.db.cursor()
        c.execute(
            "select id from torrent_entry where deleted and "
            "updated_at > ? and updated_at <= ?",
            (from_changestamp, to_changestamp))
        return [r[0] for r in c]

    def extract(self, from_changestamp):
        assert not self.config.api.db.getautocommit()
        from_changestamp = from_changestamp or 0

        series_query = (
            "select id, updated_at from series "
            "where updated_at > :changestamp")
        group_query = (
            "select series_id, updated_at "
            "from torrent_entry_group "
            "where updated_at > :changestamp")
        torrent_entry_query = (
            "select torrent_entry_group.series_id, "
            "torrent_entry.updated_at "
            "from torrent_entry "
            "inner join torrent_entry_group "
            "on torrent_entry.group_id = torrent_entry_group.id "
            "where torrent_entry.updated_at > :changestamp ")
        query = (
            "select id, max(updated_at) from (%s union all %s union all %s) "
            "group by 1 order by 2" % (
                series_query, group_query, torrent_entry_query))

        c = self.config.api.db.cursor()
        c.execute(query, {"changestamp": from_changestamp})

        def make_result(torrents, from_changestamp, to_changestamp):
            return (
                torrents, self.get_deleted_torrent_ids(
                    from_changestamp, to_changestamp),
                tvaf.checkpoint.SourceDelta(from_changestamp, to_changestamp))

        torrents = []
        to_changestamp = None
        for series_id, changestamp in c:
            if to_changestamp is not None and changestamp != to_changestamp:
                yield make_result(torrents, from_changestamp, to_changestamp)
                torrents = []
                from_changestamp = to_changestamp
            to_changestamp = changestamp
            torrents.extend(self.get_series_torrents(series_id))
        if to_changestamp is not None:
            yield make_result(torrents, from_changestamp, to_changestamp)

    def pick(self, torrents):
        picker = tvaf.tracker.btn.pick.WholeSeriesPicker(
            torrents, self.config, self.tvdb, self.thread_pool,
            debug=self.debug)
        start = time.time()
        items = picker.pick()
        end = time.time()
        log().debug(
            "Picked %s torrents -> %s items in %.3fs", len(torrents),
            len(items), end - start)
        return items

    def sync(self, items, deleted_torrent_ids, from_changestamp,
             to_changestamp):
        if self.pretend:
            return

        syncer = tvaf.sync.Syncer(
            self.library_section, plex_host=self.plex_host,
            yatfs_path=self.config.yatfs_path)

        log().debug(
            "Syncing %s -> %s: %s items", from_changestamp, to_changestamp,
            len(items))

        delta = tvaf.checkpoint.SourceDelta(from_changestamp, to_changestamp)
        changes = tvaf.sync.Changes.from_exclusive_items(items)
        changes.tracker_torrent_id_to_items.update({
            (tvaf.tracker.btn.NAME, i): [] for i in deleted_torrent_ids})

        with self.library_section.db.begin():
            start = time.time()
            with tvaf.checkpoint.checkpoint(
                    self.btn_library, self.config, delta):
                syncer.sync_changes(changes)
            end = time.time()
        log().debug("Batch sync took %dms", (end - start) * 1000)

        syncer.finalize()

    def run(self):
        with self.config.api.db:
            if self.reset:
                self.btn_library.set_sequence(None)

            from_changestamp = self.btn_library.get_sequence()

            txn_items = []
            txn_deleted_torrent_ids = []
            to_changestamp = None
            log().debug("Extracting from %s", from_changestamp)
            for torrents, deleted_torrent_ids, delta in self.extract(
                    from_changestamp):
                if log().isEnabledFor(logging.INFO):
                    log().info(
                        "Extracted batch %s -> %s: %s deleted; series %s",
                        delta.from_sequence, delta.to_sequence,
                        len(deleted_torrent_ids), sorted(set(
                            (te.group.series.id, te.group.series.name)
                            for te in torrents)))
                assert (not to_changestamp) or (
                        delta.from_sequence == to_changestamp), (
                                delta.from_sequence, to_changestamp)
                items = self.pick(torrents)
                if txn_items and (
                        len(txn_items) + len(items) > self.transaction_size):
                    self.sync(
                        txn_items, txn_deleted_torrent_ids, from_changestamp,
                        to_changestamp)
                    txn_items = []
                    txn_deleted_torrent_ids = []
                    from_changestamp = to_changestamp
                txn_items.extend(items)
                txn_deleted_torrent_ids.extend(deleted_torrent_ids)
                to_changestamp = delta.to_sequence
            if to_changestamp:
                self.sync(
                    txn_items, txn_deleted_torrent_ids, from_changestamp,
                    to_changestamp)


class OneShotPipe(object):

    def __init__(self, btn_library, syncer, tvdb=None, thread_pool=None,
            debug=False, series=None, series_id=None, tvdb_id=None):
        self.btn_library = btn_library
        self.config = self.btn_library.config
        self.syncer = syncer
        self.tvdb = tvdb
        self.thread_pool = thread_pool
        self.debug = debug
        self.series = series
        self.series_id = series_id
        self.tvdb_id = tvdb_id

    def get_series_id(self):
        if self.series:
            row = self.api.db.cursor().execute(
                "select id from series where name = ?",
                (self.series,)).fetchone()
        elif self.series_id:
            row = (self.series_id,)
        elif args.tvdb_id:
            row = api.db.cursor().execute(
                "select id from series where tvdb_id = ?",
                (self.tvdb_id,)).fetchone()

        return row[0] if row else None

    def run(self):
        pass
