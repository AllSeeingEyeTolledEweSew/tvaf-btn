import unittest

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import session as session_lib


class TestSession(unittest.TestCase):

    def setUp(self):
        self.config = config_lib.Config(session_listen_interfaces="127.0.0.1:0")
        self.required_alert_mask = (lt.alert_category.error |
                                    lt.alert_category.peer)
        self.get_required_alert_mask = lambda: self.required_alert_mask

    def create_session_service(self):
        return session_lib.SessionService(
            get_required_alert_mask=self.get_required_alert_mask,
            config=self.config)

    def test_session(self):
        session_service = self.create_session_service()
        settings = session_service.session.get_settings()

        # Test required alert mask is applied
        self.assertEqual(settings["alert_mask"] & self.required_alert_mask,
                         self.required_alert_mask)

        # Test overrides are applied
        self.assertEqual(settings["enable_dht"], False)

        # Test default config is added
        self.assertEqual(self.config["session_settings_base"],
                         "default_settings")

    def test_alert_mask(self):
        self.config["session_alert_mask"] = lt.alert_category.session_log

        session_service = self.create_session_service()
        settings = session_service.session.get_settings()

        # Test required mask was added
        self.assertEqual(
            settings["alert_mask"],
            lt.alert_category.session_log | self.required_alert_mask)

    def test_overrides(self):
        self.config["session_enable_dht"] = True

        session_service = self.create_session_service()
        settings = session_service.session.get_settings()

        # Test overrides are applied
        self.assertEqual(settings["enable_dht"], False)

    def test_blacklist(self):
        self.config["session_user_agent"] = "test"

        session_service = self.create_session_service()
        settings = session_service.session.get_settings()

        # Test blacklisted setting gets replaced by libtorrent default
        self.assertNotEqual(settings["user_agent"], "test")

    def test_reconfigure(self):
        session_service = self.create_session_service()
        settings = session_service.session.get_settings()

        # Sanity check: close_redundant_connections should be True by default
        self.assertEqual(settings["close_redundant_connections"], True)

        self.config["session_close_redundant_connections"] = False
        session_service.set_config(self.config)

        settings = session_service.session.get_settings()
        self.assertEqual(settings["close_redundant_connections"], False)

    def test_reconfigure_no_changes(self):
        session_service = self.create_session_service()
        session_service.set_config(self.config)

    def test_settings_base(self):
        self.config["session_settings_base"] = "high_performance_seed"

        session_service = self.create_session_service()
        settings = session_service.session.get_settings()

        # Check settings pack was applied as default
        self.assertEqual(settings["cache_size"],
                         lt.high_performance_seed()["cache_size"])

        # Check base pack name didn't get overwritten
        self.assertEqual(self.config["session_settings_base"],
                         "high_performance_seed")

    def test_settings_base_invalid(self):
        self.config["session_settings_base"] = "invalid"

        with self.assertRaises(config_lib.InvalidConfigError):
            self.create_session_service()

    def test_setting_invalid_type(self):
        self.config["session_cache_size"] = "invalid"

        with self.assertRaises(config_lib.InvalidConfigError):
            self.create_session_service()

    def test_alert_mask_invalid_type(self):
        self.config["session_alert_mask"] = "invalid"

        with self.assertRaises(config_lib.InvalidConfigError):
            self.create_session_service()
