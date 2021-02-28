# Copyright (c) 2020 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

import argparse
import contextlib
import signal
from typing import Any
from typing import Iterator

from tvaf import app as app_lib


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="TVAF")
    return parser


class Loader:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    def load(self) -> app_lib.App:
        return app_lib.App()


class Runner:
    def __init__(self, app: app_lib.App) -> None:
        self.app = app
        self.done = False

    def handle_sigterm(self, _signum: int, _frame: Any) -> None:
        self.done = True

    def handle_sighup(self, _signum: int, _frame: Any) -> None:
        self.app.reload_config()

    @contextlib.contextmanager
    def handle_signals(self) -> Iterator[None]:
        signal.signal(signal.SIGHUP, self.handle_sighup)
        signal.signal(signal.SIGTERM, self.handle_sigterm)
        try:
            yield
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGHUP, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def loop(self) -> None:
        while not self.done:
            signal.pause()

    def run(self) -> None:
        self.app.start()
        with self.handle_signals():
            self.loop()
        self.app.terminate()
        self.app.join()


def main() -> None:
    parser = create_argument_parser()
    args = parser.parse_args()

    app = Loader(args).load()
    Runner(app).run()
