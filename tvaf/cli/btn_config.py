# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import argparse
import json
import logging
import sys

import tvaf.plex
import tvaf.tracker.btn


def log():
    return logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count")

    parser.add_argument("--plex_path", default="/var/lib/plexmediaserver")

    mxg = parser.add_mutually_exclusive_group(required=True)
    mxg.add_argument("--library_section_name")
    mxg.add_argument("--library_section_id", type=int)

    parser.add_argument("--btn_cache_path")
    parser.add_argument("--yatfs_path")
    parser.add_argument("--filter")

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

    config = btn_library.get_config()
    update = False

    if config:
        if args.btn_cache_path:
            config.btn_cache_path = args.btn_cache_path
            _ = config.api
            update = True
        if args.yatfs_path:
            config.yatfs_path = args.yatfs_path
            update = True
        if args.filter:
            config.filter_name = args.filter
            _ = config.filter
            update = True

        log().info(
            "TVAF configuration for %s: %s", library_section, json.dumps(
                config.to_dict(), sys.stdout, sort_keys=True, indent=4))

        if update:
            btn_library.set_config(config)
        else:
            log().info("Not updating anything")
    else:
        log().info("No TVAF configuration in section %s", library_section)
        if args.btn_cache_path or args.yatfs_path or args.filter:
            log().error("Can't update config")
