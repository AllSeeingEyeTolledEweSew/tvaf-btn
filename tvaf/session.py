import contextlib
import logging
import threading
from typing import Any
from typing import Collection
from typing import Dict
from typing import Iterator

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import ltpy

_LOG = logging.getLogger()

_OVERRIDES = {
    "announce_ip": "",
    "handshake_client_version": "",
    "enable_lsd": False,
    "enable_dht": False,
    "alert_queue_size": 2**32 - 1,
}

_BLACKLIST = {
    "user_agent",
    "peer_fingerprint",
}


@contextlib.contextmanager
def _translate_exceptions():
    try:
        with ltpy.translate_exceptions():
            yield
    except (KeyError, TypeError, ltpy.Error) as exc:
        raise config_lib.InvalidConfigError(str(exc)) from exc


def parse_config(config: config_lib.Config) -> Dict[str, Any]:
    config.setdefault("session_settings_base", "default_settings")

    settings_base_name = config.require_str("session_settings_base")
    if settings_base_name not in ("default_settings", "high_performance_seed"):
        raise config_lib.InvalidConfigError(
            f"no settings pack named \"{settings_base_name}\"")
    settings: Dict[str, Any] = getattr(lt, settings_base_name)()

    for key, value in config.items():
        if not key.startswith("session_"):
            continue
        key = key[len("session_"):]
        if key == "settings_base":
            continue

        if key in _BLACKLIST:
            continue

        if key not in settings:
            raise config_lib.InvalidConfigError(f"no setting named {key}")
        if settings[key].__class__ != value.__class__:
            raise config_lib.InvalidConfigError(
                f"{key} should be {settings[key].__class__}, "
                f"not {value.__class__}")

        settings[key] = value

    # Update our static overrides
    settings.update(_OVERRIDES)

    return settings


_LOG2 = {1 << i: i for i in range(64)}


def _get_mask_bits(mask: int) -> Collection[int]:
    bits = set()
    while mask != 0:
        mask_without_one_bit = mask & (mask - 1)
        one_bit_mask = mask & ~mask_without_one_bit
        bits.add(_LOG2[one_bit_mask])
        mask = mask_without_one_bit
    return bits


_ALERT_MASK_NAME: Dict[int, str] = {}


def _init_alert_mask_name():
    for name in dir(lt.alert.category_t):
        if name.startswith("_"):
            continue
        mask = getattr(lt.alert.category_t, name)
        if mask not in _LOG2:
            continue
        _ALERT_MASK_NAME[mask] = name


_init_alert_mask_name()
del _init_alert_mask_name


class SessionService(config_lib.HasConfig):

    def __init__(self,
                 *,
                 alert_mask: int = 0,
                 config: config_lib.Config = None):
        self._lock = threading.RLock()
        self._alert_mask_bit_count: Dict[int, int] = {}
        self._inc_alert_mask_bits_locked(alert_mask)
        if config is None:
            config = config_lib.Config()

        with _translate_exceptions():
            self._settings = parse_config(config)
            self._config_alert_mask: int = self._settings["alert_mask"]
            self._settings["alert_mask"] |= alert_mask
            self._inc_alert_mask_bits_locked(self._config_alert_mask)
            self.session = lt.session(self._settings)

    def _inc_alert_mask_bits_locked(self, alert_mask: int):
        for bit in _get_mask_bits(alert_mask):
            self._alert_mask_bit_count[bit] = (
                self._alert_mask_bit_count.get(bit, 0) + 1)

    def _dec_alert_mask_bits_locked(self, alert_mask: int):
        for bit in _get_mask_bits(alert_mask):
            self._alert_mask_bit_count[bit] -= 1
            if self._alert_mask_bit_count[bit] == 0:
                self._alert_mask_bit_count.pop(bit)

    def inc_alert_mask(self, alert_mask: int):
        with self._lock:
            self._inc_alert_mask_bits_locked(alert_mask)
            # Can't fail to update alert mask (?)
            self._update_alert_mask_locked()

    def dec_alert_mask(self, alert_mask: int):
        with self._lock:
            self._dec_alert_mask_bits_locked(alert_mask)
            # Can't fail to update alert mask (?)
            self._update_alert_mask_locked()

    def _update_alert_mask_locked(self):
        alert_mask = self._get_alert_mask_locked()
        self._apply_settings_locked({"alert_mask": alert_mask})
        self._settings["alert_mask"] = alert_mask

    def _get_alert_mask_locked(self):
        alert_mask = 0
        for bit in self._alert_mask_bit_count:
            alert_mask |= 1 << bit
        return alert_mask

    def _apply_settings_locked(self, settings: Dict[str, Any]):
        deltas = dict(set(settings.items()) - set(self._settings.items()))
        if not deltas:
            return
        if _LOG.isEnabledFor(logging.DEBUG):
            delta_alert_mask = settings["alert_mask"] ^ self._settings[
                "alert_mask"]
            for bit in _get_mask_bits(delta_alert_mask):
                mask = 1 << bit
                name = _ALERT_MASK_NAME.get(mask, mask)
                if settings["alert_mask"] & mask:
                    _LOG.debug("enabling alerts: %s", name)
                else:
                    _LOG.debug("disabling alerts: %s", name)
        # As far as I can tell, apply_settings never partially fails
        self.session.apply_settings(deltas)

    @contextlib.contextmanager
    def stage_config(self, config: config_lib.Config) -> Iterator[None]:
        settings = parse_config(config)

        with self._lock:
            yield
            config_alert_mask: int = settings["alert_mask"]
            self._dec_alert_mask_bits_locked(self._config_alert_mask)
            self._inc_alert_mask_bits_locked(config_alert_mask)
            settings["alert_mask"] = self._get_alert_mask_locked()
            self._apply_settings_locked(settings)
            self._settings = settings
            self._config_alert_mask = config_alert_mask
