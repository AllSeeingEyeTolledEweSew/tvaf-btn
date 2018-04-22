# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import tvaf.checkpoint


class SeriesBatch(object):

    def __init__(self, series_id_to_torrents, from_changestamp=None,
                 to_changestamp=None):
        self.series_id_to_torrents = series_id_to_torrents
        if from_changestamp or to_changestamp:
            self.delta = tvaf.checkpoint.SourceDelta(
                from_changestamp, to_changestamp)
        else:
            self.delta = None


class SeriesBatchExtractor(object):

    def __init__(self, config):
        self.config = config

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
        batch_series_id_to_torrents = {}
        batch_changestamp = None
        prev_changestamp = from_changestamp
        for series_id, changestamp in c:
            if (batch_changestamp is not None and
                    changestamp != batch_changestamp):
                yield SeriesBatch(
                    batch_series_id_to_torrents, prev_changestamp,
                    batch_changestamp)
                prev_changestamp = batch_changestamp
                batch_series_id_to_torrents = {}
            batch_changestamp = changestamp
            batch_series_id_to_torrents[series_id] = self.get_series_torrents(
                    series_id)
        if batch_changestamp is not None:
            yield SeriesBatch(
                batch_series_id_to_torrents, prev_changestamp,
                batch_changestamp)
