# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
from __future__ import annotations

import json
import pathlib
from typing import Callable
import dataclasses
import ipaddress
import pathlib
from typing import Dict
from typing import Union

import libtorrent as lt


FILENAME = "config.json"
RESUME_DATA_DIR_NAME = "resume"
DEFAULT_DOWNLOAD_DIR_NAME = "downloads"

SettingsPack = Dict[str, Union[str, int, bool]]

class SettingsPack(dict):

    @staticmethod
    def get_overrides():
        return {
            "announce_ip": "",
            "handshake_client_version": "",
            "enable_lsd": False,
            "enable_dht": False,
            # For testing
            #"peer_fingerprint": lt.generate_fingerprint("DE", 1, 3, 9, 0),
            # For testing
            #"user_agent": "Deluge 1.3.9",
            "alert_queue_size": 2 ** 32 - 1,
        }

    @staticmethod
    def get_blacklist():
        return {
            "user_agent",
            "peer_fingerprint",
        }

    def __setitem__(self, key, value):
        raise TypeError("SettingsPack is immutable")

    def __delitem__(self, key):
        raise TypeError("SettingsPack is immutable")


def get_libtorrent_alert_categories() -> Dict[str, int]:
    name_to_mask:Dict[str, int] = {}
    for name in dir(lt.alert_category):
        if name.startswith("__"):
            continue
        value = getattr(lt.alert_category, name)
        if not isinstance(value, int):
            continue
        # Only return single-bit masks
        if value & (value - 1) == 0:
            continue
        name_to_mask[name] = value
    return name_to_mask


_IPAdress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
_IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


@dataclasses.dataclass(frozen=True)
class Config:

    config_dir: pathlib.Path = pathlib.Path()

    sftp_enabled: bool = False
    sftp_bind_address: _IPAddress = dataclasses.field(default=ipaddress.ip_address("::"))
    sftp_port: int = 0
    sftp_ip_whitelist: List[_IPNetwork] = dataclasses.field(default_factory=list)

    http_enabled: bool = False
    http_bind_address: _IPAddress = dataclasses.field(
            default=ipaddress.ip_address("::"))
    http_port:int = 0
    http_host_whitelist: List[str] = dataclasses.field(
            default_factory=list)
    http_ip_whitelist: List[_IPNetwork] = dataclasses.field(
            default_factory=list)

    download_dir: pathlib.Path = pathlib.Path()
    libtorrent_settings_base: str = ""
    libtorrent_settings: SettingsPack = dataclasses.field(
        default_factory=SettingsPack)

    def __post_init__(self):
        super().__setattr__("http_enabled", bool(self.http_enabled))
        super().__setattr__("http_port", int(self.http_port))
        super().__setattr__("http_bind_address",
                ipaddress.ip_address(self.http_bind_address))
        super().__setattr__("http_ip_whitelist",
                [ipaddress.ip_network(net) for net in self.http_ip_whitelist])

        super().__setattr__("sftp_enabled", bool(self.sftp_enabled))
        super().__setattr__("sftp_port", int(self.sftp_port))
        super().__setattr__("sftp_bind_address",
                ipaddress.ip_address(self.sftp_bind_address))
        super().__setattr__("sftp_ip_whitelist",
                [ipaddress.ip_network(net) for net in self.sftp_ip_whitelist])

        super().__setattr__("download_dir",
                pathlib.Path(self.download_dir).resolve(strict=False))
        super().__setattr__("libtorrent_settings",
                SettingsPack(self.libtorrent_settings))

    def replace(self, **changes) -> Config:
        return dataclasses.replace(self, **changes)

    def get_libtorrent_settings_base(self) -> str:
        attr = getattr(lt, self.libtorrent_settings_base, None)
        if callable(attr) and isinstance(attr(), dict):
            return self.libtorrent_settings_base
        return "default_settings"

    def get_effective_libtorrent_settings(self) -> SettingsPack:
        result = getattr(lt, self.get_libtorrent_settings_base())()
        user_settings = dict(self.libtorrent_settings)
        for key in SettingsPack.get_blacklist():
            user_settings.pop(key, None)
        result.update(user_settings)
        result.update(SettingsPack.get_overrides())
        return SettingsPack(result)

    def normalize(self) -> Config:
        return self.replace(
            libtorrent_settings_base=self.get_libtorrent_settings_base())

    def to_json(self) -> Dict[str, Any]:
        result = dataclasses.asdict(self)

        # Don't serialize config_dir
        result.pop("config_dir", None)

        result["http_bind_address"] = str(result["http_bind_address"])
        result["http_ip_whitelist"] = [
            str(net) for net in result["http_ip_whitelist"]]

        result["sftp_bind_address"] = str(result["sftp_bind_address"])
        result["sftp_ip_whitelist"] = [
            str(net) for net in result["sftp_ip_whitelist"]]

        result["download_dir"] = str(result["download_dir"])

        return result

    @classmethod
    def get_default(cls, config_dir:pathlib.Path):
        return cls(
            config_dir=config_dir,
            sftp_enabled=True,
            sftp_bind_address="::1",
                sftp_port=7387,
                sftp_ip_whitelist=["127.0.0.0/8", "::1/128"],
                http_enabled=True,
                http_bind_address="::1",
                http_port=8823,
                http_host_whitelist=["localhost"],
                http_ip_whitelist=["127.0.0.0/8"],
                download_dir=config_dir.joinpath(DEFAULT_DOWNLOAD_DIR_NAME),
                libtorrent_settings_base="default_settings",
        )

    @classmethod
    def load(cls, config_dir:pathlib.Path):
        config = cls.get_default(config_dir)
        path = config_dir.joinpath(FILENAME)
        try:
            with path.open() as config_file:
                config_json = json.load(config_file)
            config = config.replace(**config_json)
        except FileNotFoundError:
            pass
        return config

    def save(self):
        config_data = self.normalize().to_json()
        path = self.config_dir.joinpath(FILENAME)
        path.parent.mkdir(exist_ok=True, parents=True)
        tmp_path = path.with_suffix(".tmp")
        try:
            with tmp_path.open(mode="w") as fp:
                json.dump(config_data, fp, sort_keys=True, indent=4)
            tmp_path.replace(path)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    def get_resume_data_dir(self) -> pathlib.Path:
        return self.config_dir.joinpath(RESUME_DATA_DIR_NAME)


GetConfig = Callable[[], Config]
