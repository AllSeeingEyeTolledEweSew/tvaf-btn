# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import argparse
import concurrent.futures
import importlib
import logging
import sys
import threading

import btn
import tvaf.sync
import tvaf.tracker.btn.default_selectors
import tvaf.tracker.btn.pick
import tvaf.tvdb


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


def get_series_ids(api, parser, args):
    if args.series:
        rows = api.db.cursor().execute(
            "select id from series where name = ?", (args.series,)).fetchall()

    elif args.series_id:
        rows = [(args.series_id,)]

    elif args.tvdb_id:
        rows = api.db.cursor().execute(
            "select id from series where tvdb_id = ?",
            (args.tvdb_id,)).fetchall()

    elif args.all:
        rows = api.db.cursor().execute(
            "select id from series where not deleted").fetchall()

    return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count")
    parser.add_argument("--debug", "-d", action="count")

    parser.add_argument(
        "--selector", type=function,
        default=tvaf.tracker.btn.default_selectors.best_with_heuristics)
    parser.add_argument("--pretend", action="store_true")

    parser.add_argument("--plex_path", default="/var/lib/plexmediaserver")
    parser.add_argument("--plex_host", default="127.0.0.1:32400")
    parser.add_argument("--plex_library_name")
    parser.add_argument("--yatfs_path")
    parser.add_argument("--max_threads", type=int, default=64)

    mxg = parser.add_mutually_exclusive_group(required=True)
    mxg.add_argument("--all", action="store_true")
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

    scanner = lambda te: tvaf.tracker.btn.scan.Scanner(
        te, debug=args.debug).iter_media_items()

    if args.pretend:
        syncer = None
    else:
        syncer = tvaf.sync.Syncer(
            args.plex_path, plex_host=args.plex_host,
            library_section_name=args.plex_library_name,
            yatfs_path=args.yatfs_path)

    with api.db:
        series_ids = get_series_ids(api, parser, args)

        for series_id in series_ids:
            picker = tvaf.tracker.btn.pick.WholeSeriesPicker(
                series_id, api, scanner, args.selector, tvdb, thread_pool,
                debug=args.debug)
            picker.pick()
            if not args.pretend:
                syncer.sync_from_picker(picker)

    if not args.pretend:
        syncer.finalize()
