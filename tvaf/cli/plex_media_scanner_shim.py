import argparse
import logging
import os
import re
import sys


def log():
    return logging.getLogger(__name__)


def get_passthrough_env():
    env = os.environ.copy()
    for k, v in env.copy().items():
        m = re.match(r"TVAF_PASSTHROUGH_(?P<name>.*)", k)
        if m:
            del env[k]
            name = m.group("name")
            env[name] = v
    return env


def passthrough_exec(args):
    path = os.path.join(os.environ["HOME"], "Plex Media Scanner.real")
    os.execve(path, args, get_passthrough_env())


def parse_args():
    parser = argparse.ArgumentParser(description="Plex Media Scanner Shim")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--log-file-suffix")

    parser.add_argument("-r", "--refresh", action="store_true")
    parser.add_argument("-a", "--analyze", action="store_true")
    parser.add_argument("--analyze-deeply", action="store_true")
    parser.add_argument("--analyze-loudness", action="store_true")
    parser.add_argument("-b", "--index", action="store_true")
    parser.add_argument("-s", "--scan", action="store_true")
    parser.add_argument("-i", "--info", action="store_true")
    parser.add_argument("-l", "--list", action="store_true")
    parser.add_argument("-g", "--generate", action="store_true")
    parser.add_argument("-t", "--tree", action="store_true")
    parser.add_argument("-w", "--reset", action="store_true")
    parser.add_argument("-n", "--add-section")
    parser.add_argument("--type", type=int)
    parser.add_argument("--agent")
    parser.add_argument("--location")
    parser.add_argument("--lang")
    parser.add_argument("-D", "--del-section", type=int)

    parser.add_argument("-c", "--section", type=int)
    parser.add_argument("-o", "--item", type=int)
    parser.add_argument("-d", "--directory")
    parser.add_argument("-f", "--file")

    parser.add_argument("-x", "--force", action="store_true")
    parser.add_argument("--no-thumbs", action="store_true")
    parser.add_argument("--chapter-thumbs-only", action="store_true")
    parser.add_argument("--thumbOffset")
    parser.add_argument("--artOffset")

    return parser.parse_args()


def main():
    passthrough_exec([a for a in sys.argv if a != "--scan"])
