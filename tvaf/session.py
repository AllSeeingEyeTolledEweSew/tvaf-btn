import libtorrent as lt
import contextlib
from tvaf import config as config_lib
from typing import Callable
import threading
from typing import Dict
from typing import Any
from tvaf import ltpy

_OVERRIDES = {
        "announce_ip": "",
        "handshake_client_version": "",
        "enable_lsd": False,
        "enable_dht": False,
        "alert_queue_size": 2 ** 32 - 1,
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

class SessionService:

    def __init__(self, *, get_required_alert_mask:Callable[[], int]=None, config:config_lib.Config=None):
        assert get_required_alert_mask is not None
        assert config is not None

        self._lock = threading.RLock()
        self.get_required_alert_mask = get_required_alert_mask

        with _translate_exceptions():
            self._settings = self._parse_config(config)
            self.session = lt.session(self._settings)

    def _parse_config(self, config:config_lib.Config) -> Dict[str, Any]:
        config.setdefault("session_settings_base", "default_settings")

        settings_base_name = config.require_str("session_settings_base")
        if settings_base_name not in ("default_settings",
                "high_performance_seed"):
            raise config_lib.InvalidConfigError(f"no settings pack named \"{settings_base_name}\"")
        settings:Dict[str, Any] = getattr(lt, settings_base_name)()

        for key, value in config.items():
            if not key.startswith("session_"):
                continue
            key = key[len("session_"):]
            if key == "settings_base":
                continue

            if key in _BLACKLIST:
                continue

            settings[key] = value

        # Update our static overrides
        settings.update(_OVERRIDES)

        # Specialized override: alert_mask
        alert_mask = settings.get("alert_mask", 0)
        if not isinstance(alert_mask, int):
            raise config_lib.InvalidConfigError(f"alert_mask is {alert_mask!r}, not int")
        settings["alert_mask"] = alert_mask | self.get_required_alert_mask()

        return settings

    def set_config(self, config:config_lib.Config):
        with _translate_exceptions():
            settings = self._parse_config(config)
            with self._lock:
                deltas = dict(set(settings.items()) -
                        set(self._settings.items()))
                if not deltas:
                    return
                # As far as I can tell, apply_settings never partially fails
                self.session.apply_settings(deltas)
                self._settings = settings
