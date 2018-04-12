# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import argparse
import collections
import logging
import sys

import btn
from tvaf import sync as tvaf_sync
from tvaf.tracker import btn as tvaf_btn


def log():
    return logging.getLogger(__name__)


def chunks(l, n):
    for i in xrange(0, len(l), n):
        yield l[i:i+n]


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


def sync_series_torrent_ids(args, api, syncer, series_id, torrent_ids):
    log().info("Syncing series %s", series_id)

    if args.one_per_guid:
        guid_to_items = {}

    for torrent_id in torrent_ids:
        torrent_entry = api.getTorrentByIdCached(torrent_id)
        if args.list:
            sys.stdout.write("%s:\n" % torrent_entry)
        scanner = tvaf_btn.Scanner(
            torrent_entry, debug_scanner=args.debug_scanner)
        items = []
        for item in scanner.iter_media_items():
            items.append(item)
            if args.list:
                sys.stdout.write("  %s\n" % item)
            if args.one_per_guid:
                guid = item.metadata_item.guid
                if guid not in guid_to_items:
                    guid_to_items[guid] = []
                guid_to_items[guid].append(item)

        if not args.one_per_guid and not args.pretend:
            with syncer.begin():
                syncer.sync_torrent_exclusive(
                    tvaf_btn.NAME, torrent_id, *items)

    if args.one_per_guid:
        torrent_id_to_items = {}
        for guid_items in chunks(list(guid_to_items.items()), 300):
            with syncer.begin():
                for guid, items in guid_items:
                    for item in items:
                        torrent_id = item.torrent_entry.id
                        if torrent_id not in torrent_id_to_items:
                            torrent_id_to_items[torrent_id] = []
                    item = sorted(
                        items, key=lambda i: i.torrent_entry.seeders)[-1]
                    torrent_id_to_items[item.torrent_entry.id].append(item)
                    if args.list:
                        sys.stdout.write("%s -> %s\n" % (guid, item))
                    if not args.pretend:
                        syncer.sync_guid_exclusive(guid, item)
        if not args.pretend:
            with syncer.begin():
                for torrent_id, items in torrent_id_to_items.items():
                    syncer.sync_torrent_exclusive(
                        tvaf_btn.NAME, torrent_id, *items)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count")
    parser.add_argument("--debug_scanner", action="store_true")

    parser.add_argument("--pretend", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--one_per_guid", action="store_true")

    parser.add_argument("--plex_path", default="/var/lib/plexmediaserver")
    parser.add_argument("--plex_host", default="127.0.0.1:32400")
    parser.add_argument("--plex_library_name")
    parser.add_argument("--yatfs_path")

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

    if args.one_per_guid:
        if not (args.all or args.series or args.series_id or args.tvdb_id):
            parser.error(
                "with --one_per_guid, you must select at least a full series "
                "with --all, --series, --series_id or --tvdb_id")

    api = btn.API.from_args(parser, args)

    if args.pretend:
        syncer = None
    else:
        syncer = tvaf_sync.Syncer(
            args.plex_path, plex_host=args.plex_host,
            library_section_name=args.plex_library_name,
            yatfs_path=args.yatfs_path)

    with api.db:
        series_id_to_torrents = get_series_id_to_torrents(api, parser, args)

        for series_id, torrent_ids in sorted(series_id_to_torrents.items()):
            sync_series_torrent_ids(args, api, syncer, series_id, torrent_ids)

    if not args.pretend:
        syncer.finalize()
