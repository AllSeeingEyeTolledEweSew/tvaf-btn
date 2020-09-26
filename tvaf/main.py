import argparse
import contextlib
import pathlib
import signal
from typing import Any
from typing import Iterator

from tvaf import app as app_lib


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="TVAF")
    parser.add_argument("--config_dir", required=True, type=pathlib.Path)
    return parser


class Loader:

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    def load(self) -> app_lib.App:
        return app_lib.App(self.args.config_dir)


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
