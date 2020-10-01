from __future__ import annotations

import logging
import pathlib
import socket as socket_lib
from typing import Optional

import libtorrent as lt

from tvaf import auth as auth_lib
from tvaf import config as config_lib
from tvaf import driver as driver_lib
from tvaf import ftp as ftp_lib
from tvaf import http as http_lib
from tvaf import library
from tvaf import lt4604
from tvaf import request as request_lib
from tvaf import resume as resume_lib
from tvaf import session as session_lib
from tvaf import task as task_lib
from tvaf import torrent_io
from tvaf import types

_LOG = logging.getLogger(__name__)


class App(task_lib.Task):

    # pylint: disable=too-many-instance-attributes

    def __init__(self, config_dir: pathlib.Path):
        super().__init__(title="TVAF")
        self._config_dir = config_dir
        default_config = False

        try:
            self._config = self._load_config()
        except FileNotFoundError:
            default_config = True
            self._config = config_lib.Config()

        self._session_service = session_lib.SessionService(config=self._config)
        self._session = self._session_service.session
        self._alert_driver = driver_lib.AlertDriver(
            session_service=self._session_service)

        self._resume_service = resume_lib.ResumeService(
            config_dir=self._config_dir,
            session=self._session,
            alert_driver=self._alert_driver)

        self._request_service = request_lib.RequestService(
            config_dir=self._config_dir,
            session=self._session,
            resume_service=self._resume_service,
            alert_driver=self._alert_driver,
            config=self._config)

        self._auth_service = auth_lib.AuthService()

        self.libraries = library.Libraries()
        self._library_service = library.LibraryService(opener=self._open,
                                                       libraries=self.libraries)

        self._ftpd = ftp_lib.FTPD(auth_service=self._auth_service,
                                  root=self._library_service.root,
                                  config=self._config)
        self._httpd = http_lib.HTTPD(config=self._config, session=self._session)

        self._lt4604_fixup = lt4604.Fixup(alert_driver=self._alert_driver)

        if default_config:
            self._save_config()

    @property
    def http_socket(self) -> Optional[socket_lib.socket]:
        return self._httpd.socket

    @property
    def ftp_socket(self) -> Optional[socket_lib.socket]:
        return self._ftpd.socket

    def _load_config(self) -> config_lib.Config:
        return config_lib.Config.from_config_dir(self._config_dir)

    def _save_config(self) -> None:
        self._config.write_config_dir(self._config_dir)

    def _open(self, tslice: types.TorrentSlice,
              get_torrent: types.GetTorrent) -> torrent_io.BufferedTorrentIO:
        user = self._auth_service.get_user()
        if user is None:
            raise auth_lib.AuthenticationFailed(
                "Opening torrent outside of authentication!")

        def get_add_torrent_params():
            atp = lt.add_torrent_params()
            atp.ti = get_torrent()
            return atp

        return torrent_io.BufferedTorrentIO(
            request_service=self._request_service,
            info_hash=tslice.info_hash,
            start=tslice.start,
            stop=tslice.stop,
            get_add_torrent_params=get_add_torrent_params)

    def _set_config(self, config: config_lib.Config) -> None:
        config_lib.set_config(config, self._session_service.stage_config,
                              self._request_service.stage_config,
                              self._ftpd.stage_config)
        self._config = config

    def reload_config(self) -> None:
        self._set_config(self._load_config())

    def _terminate(self):
        pass

    def _run(self):
        # These need to be started first mainly because they have initialized
        # iterators. There could be some other way to do this.
        self._add_child(self._alert_driver)
        self._add_child(self._request_service)
        self._add_child(self._resume_service)
        self._add_child(self._lt4604_fixup)

        # Load resume data
        for atp in resume_lib.iter_resume_data_from_disk(self._config_dir):
            self._session.async_add_torrent(atp)

        # Start request-serving services only after resume data has been
        # loaded so we don't serve any 404s at startup
        self._add_child(self._ftpd)
        self._add_child(self._httpd)

        self._terminated.wait()
        self._log_terminate()

        # Fixup is only necessary for keeping requests going, can terminate
        # early
        self._lt4604_fixup.terminate()

        # Terminate all request-serving services
        self._request_service.terminate()
        self._ftpd.terminate()
        self._httpd.terminate()

        # Wait for requset-serving services to complete
        self._request_service.join()
        self._ftpd.join()
        self._httpd.join()

        # Ensure there are no more alert-generating actions
        self._lt4604_fixup.join()

        # Libtorrent shutdown sequence
        self._session.pause()
        self._resume_service.terminate()
        self._resume_service.join()

        # Wait for alert consumers to finish
        self._alert_driver.terminate()
        self._alert_driver.join()
