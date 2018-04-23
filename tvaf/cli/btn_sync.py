# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import argparse
import concurrent.futures
import importlib
import logging
import sys
import threading

import btn
import tvaf.plex
import tvaf.sync
import tvaf.tracker.btn.pipe
import tvaf.tvdb
import tvaf.util


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count")
    parser.add_argument("--debug", "-d", action="count")

    parser.add_argument("--pretend", action="store_true")
    parser.add_argument("--reset", action="store_true")

    parser.add_argument("--plex_path", default="/var/lib/plexmediaserver")
    parser.add_argument("--plex_host", default="127.0.0.1:32400")

    mxg = parser.add_mutually_exclusive_group(required=True)
    mxg.add_argument("--library_section_name")
    mxg.add_argument("--library_section_id")

    parser.add_argument("--max_threads", type=int, default=64)
    parser.add_argument("--transaction_size", type=int, default=1000)

    mxg = parser.add_mutually_exclusive_group(required=True)
    mxg.add_argument("--all", action="store_true")
    mxg.add_argument("--series")
    mxg.add_argument("--series_id", type=int)
    mxg.add_argument("--tvdb_id", type=int)

    args = parser.parse_args()

    if args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        stream=sys.stdout, level=level,
        format="%(asctime)s %(levelname)s %(threadName)s "
        "%(filename)s:%(lineno)d %(message)s")

    db = tvaf.plex.PlexDatabase(args.plex_path)
    library_section = tvaf.plex.LibrarySection(
        db, name=args.library_section_name, id=args.library_section_id)
    btn_library = tvaf.tracker.btn.LibrarySection(library_section)

    tvdb = tvaf.tvdb.Tvdb(max_connections=args.max_threads)

    thread_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=args.max_threads)

    if args.pretend:
        syncer = None
    else:
        syncer = tvaf.sync.Syncer(
            library_section, plex_host=args.plex_host,
            yatfs_path=btn_library.get_config().yatfs_path)

    if args.all:
        pipe = tvaf.tracker.btn.pipe.ContinuousIncrementalPipe(
            btn_library, syncer, tvdb=tvdb, thread_pool=thread_pool,
            debug=args.debug, reset=args.reset,
            transaction_size=args.transaction_size)
    else:
        pipe = tvaf.btn.tracker.pipe.OneshotPipe(
            btn_library, syncer, tvdb=tvdb, thread_pool=thread_pool,
            debug=args.debug, series=args.series, series_id=args.series_id,
            tvdb_id=args.tvdb_id)

    pipe.run()
