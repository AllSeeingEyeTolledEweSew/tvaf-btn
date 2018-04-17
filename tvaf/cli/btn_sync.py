# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import argparse
import collections
import concurrent.futures
import contextlib
import importlib
import logging
import sys
import threading

import promise

import btn
import tvaf.sync
import tvaf.tracker.btn
import tvaf.tracker.btn.scan
import tvaf.tracker.btn.default_selectors
import tvaf.tvdb


def log():
    return logging.getLogger(__name__)


def chunks(l, n):
    for i in xrange(0, len(l), n):
        yield l[i:i+n]


def function(name):
    split = name.rsplit(".", 1)
    if len(split) < 2:
        raise argparse.ArgumentTypeError("%r not a valid function name" % name)
    module_name, function_name = split
    try:
        r = getattr(importlib.import_module(module_name), function_name)
    except (ImportError, AttributeError) as e:
        raise argparse.ArgumentTypeError("%r not found: %s" % (name, e))
    if not callable(r):
        raise argparse.ArgumentTypeError("%r is not callable" % r)
    return r


def get_series_id_to_torrents(api, parser, args):
    if args.torrent_id:
        r = api.db.cursor().execute(
            "select series.id, torrent_entry.id from torrent_entry "
            "inner join torrent_entry_group on "
            "torrent_entry.group_id = torrent_entry_group.id "
            "inner join series on "
            "torrent_entry_group.series_id = series.id "
            "where (not torrent_entry.deleted) and "
            "torrent_entry.id = ?",
            (args.torrent_id,)).fetchone()
        if not r:
            parser.error("torrent id does not exist")
        rows = [r]

    elif args.series:
        rows = api.db.cursor().execute(
            "select series.id, torrent_entry.id from torrent_entry "
            "inner join torrent_entry_group on "
            "torrent_entry.group_id = torrent_entry_group.id "
            "inner join series on "
            "torrent_entry_group.series_id = series.id "
            "where (not torrent_entry.deleted) and "
            "series.name = ?", (args.series,)).fetchall()

    elif args.series_id:
        rows = api.db.cursor().execute(
            "select series.id, torrent_entry.id from torrent_entry "
            "inner join torrent_entry_group on "
            "torrent_entry.group_id = torrent_entry_group.id "
            "inner join series on "
            "torrent_entry_group.series_id = series.id "
            "where (not torrent_entry.deleted) and "
            "series.id = ?", (args.series_id,)).fetchall()

    elif args.tvdb_id:
        rows = api.db.cursor().execute(
            "select series.id, torrent_entry.id from torrent_entry "
            "inner join torrent_entry_group on "
            "torrent_entry.group_id = torrent_entry_group.id "
            "inner join series on "
            "torrent_entry_group.series_id = series.id "
            "where (not torrent_entry.deleted) and "
            "series.tvdb_id = ?", (args.tvdb_id,)).fetchall()

    elif args.all:
        rows = api.db.cursor().execute(
            "select series.id, torrent_entry.id from torrent_entry "
            "inner join torrent_entry_group on "
            "torrent_entry.group_id = torrent_entry_group.id "
            "inner join series on "
            "torrent_entry_group.series_id = series.id "
            "where not torrent_entry.deleted").fetchall()

    series_id_to_torrents = {}
    for series_id, torrent_id in rows:
        if series_id not in series_id_to_torrents:
            series_id_to_torrents[series_id] = []
        series_id_to_torrents[series_id].append(torrent_id)
    return series_id_to_torrents


class Resolver(object):

    def __init__(self, tvdb, thread_pool):
        self.tvdb = tvdb
        self.thread_pool = thread_pool
        self._lock = threading.RLock()
        self._cache = {}

    def match_episode_by_date(self, series_id, date):
        r = self.tvdb.get(
            "/series/%d/episodes/query" % series_id,
            params={"firstAired": date})
        assert r.status_code in (200, 404), r.text
        return r.json()

    def match_episode_by_date_promise(self, series_id, date):
        key = (series_id, date)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            f = self.thread_pool.submit(
                self.match_episode_by_date, series_id, date)
            p = promise.Promise.cast(f)
            self._cache[key] = p
            return p

    def need_to_resolve(self, item):
        return bool(item.date and item.torrent_entry.group.series.tvdb_id)

    def resolve_promise(self, item):
        tvdb_id = item.torrent_entry.group.series.tvdb_id
        p = self.match_episode_by_date_promise(tvdb_id, item.date)
        def got_response(response):
            episodes = response.get("data")
            if not episodes:
                log().error(
                    "No match for series %s date %s", tvdb_id, item.date)
                return []

            def episode_key(episode):
                s = episode["airedSeason"]
                e = episode["airedEpisodeNumber"]
                return (s != 0, s, e)
            episodes = sorted(episodes, key=episode_key)
            episode = episodes[0]
            episode_number = episode["airedEpisodeNumber"]
            season_number = episode["airedSeason"]
            log().info(
                "Matched series %s date %s -> (%s, %s)",
                tvdb_id, item.date, season_number, episode_number)
            return [tvaf.tracker.btn.MediaItem(
                item.torrent_entry, item.file_infos, episode=episode_number,
                season=season_number, exact_season=season_number,
                offset=item.offset)]
        p = p.then(got_response)
        return p


def sync_series_torrent_ids(
        args, api, resolver, syncer, series_id, torrent_ids):
    log().info("Syncing series %s", series_id)

    items = []
    item_promises = []

    for torrent_id in torrent_ids:
        torrent_entry = api.getTorrentByIdCached(torrent_id)
        if args.list:
            sys.stdout.write("%s:\n" % torrent_entry)
        scanner = tvaf.tracker.btn.scan.Scanner(
            torrent_entry, debug_scanner=args.debug_scanner)
        for item in scanner.iter_media_items():
            if args.list:
                sys.stdout.write("  %s\n" % item)
            if resolver.need_to_resolve(item):
                item_promises.append(resolver.resolve_promise(item))
            else:
                items.append(item)

    for promise in item_promises:
        for item in promise.get():
            items.append(item)

    guid_to_items = collections.defaultdict(list)
    for item in items:
        guid_to_items[item.metadata_item.guid].append(item)
    for guid, items in list(guid_to_items.items()):
        guid_to_items[guid] = args.selector(items)

    torrent_id_to_items = {i: [] for i in torrent_ids}
    for items in guid_to_items.values():
        for item in items:
            torrent_id = item.torrent_entry.id
            torrent_id_to_items[torrent_id].append(item)

    for guid_items in chunks(sorted(guid_to_items.items()), 300):
        with contextlib.ExitStack() as stack:
            if not args.pretend:
                stack.enter_context(syncer.begin())
            for guid, items in guid_items:
                if args.list:
                    sys.stdout.write("%s -> %s\n" % (guid, items))
                if not args.pretend:
                    syncer.sync_guid_exclusive(guid, *items)

    if not args.pretend:
        with syncer.begin():
            for torrent_id, items in torrent_id_to_items.items():
                syncer.sync_torrent_exclusive(
                    tvaf.tracker.btn.NAME, torrent_id, *items)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count")
    parser.add_argument("--debug_scanner", action="store_true")

    parser.add_argument(
        "--selector", type=function,
        default=tvaf.tracker.btn.default_selectors.best_with_heuristics)
    parser.add_argument("--pretend", action="store_true")
    parser.add_argument("--list", action="store_true")

    parser.add_argument("--plex_path", default="/var/lib/plexmediaserver")
    parser.add_argument("--plex_host", default="127.0.0.1:32400")
    parser.add_argument("--plex_library_name")
    parser.add_argument("--yatfs_path")
    parser.add_argument("--max_threads", type=int, default=64)

    mxg = parser.add_mutually_exclusive_group(required=True)
    mxg.add_argument("--all", action="store_true")
    mxg.add_argument("--torrent_id", type=int)
    mxg.add_argument("--series")
    mxg.add_argument("--series_id", type=int)
    mxg.add_argument("--tvdb_id", type=int)

    btn.add_arguments(parser, create_group=True)

    args = parser.parse_args()

    if args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        stream=sys.stdout, level=level,
        format="%(asctime)s %(levelname)s %(threadName)s "
        "%(filename)s:%(lineno)d %(message)s")

    if args.pretend and (args.plex_library_name or args.yatfs_path):
        parser.error(
            "--pretend not allowed with --plex_library_name or --yatfs_path")
    if not args.pretend:
        if not args.plex_library_name or not args.yatfs_path:
            parser.error(
                "--plex_library_name and --yatfs_path are required.")

    if not (args.all or args.series or args.series_id or args.tvdb_id):
        parser.error(
            "you must select at least a full series with --all, --series, "
            "--series_id or --tvdb_id")

    api = btn.API.from_args(parser, args)

    tvdb = tvaf.tvdb.Tvdb(max_connections=args.max_threads)

    thread_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=args.max_threads)

    resolver = Resolver(tvdb, thread_pool)

    if args.pretend:
        syncer = None
    else:
        syncer = tvaf.sync.Syncer(
            args.plex_path, plex_host=args.plex_host,
            library_section_name=args.plex_library_name,
            yatfs_path=args.yatfs_path)

    with api.db:
        series_id_to_torrents = get_series_id_to_torrents(api, parser, args)

        for series_id, torrent_ids in sorted(series_id_to_torrents.items()):
            sync_series_torrent_ids(
                args, api, resolver, syncer, series_id, torrent_ids)

    if not args.pretend:
        syncer.finalize()
