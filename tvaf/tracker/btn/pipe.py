import logging

import tvaf.tracker.btn.extract
import tvaf.tracker.btn.pick


def log():
    return logging.getLogger(__name__)


class ContinuousIncrementalPipe(object):

    def __init__(self, btn_library, syncer, tvdb=None, thread_pool=None,
                 debug=False, reset=False):
        self.btn_library = btn_library
        self.config = self.btn_library.get_config()
        self.syncer = syncer
        self.tvdb = tvdb
        self.thread_pool = thread_pool
        self.debug = debug
        self.reset = reset

        self.extractor = tvaf.tracker.btn.extract.SeriesBatchExtractor(
            self.config)

    def run_batch(self, batch):
        log().debug(
            "Running batch: %s -> %s", batch.delta.from_sequence,
            batch.delta.to_sequence)
        picker = tvaf.tracker.btn.pick.WholeSeriesPicker(
            batch, self.config, self.tvdb, self.thread_pool, debug=self.debug)
        picker.pick()

        if self.syncer:
            with self.btn_library.library_section.db.begin():
                with tvaf.checkpoint.checkpoint(
                        self.btn_library, self.config, batch.delta):
                    self.syncer.sync_from_picker(picker)

    def run(self):
        with self.config.api.db:
            from_changestamp = self.btn_library.get_sequence()

            if self.reset:
                from_changestamp = None

            for batch in self.extractor.extract(from_changestamp):
                self.run_batch(batch)

            if self.syncer:
                self.syncer.finalize()


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
