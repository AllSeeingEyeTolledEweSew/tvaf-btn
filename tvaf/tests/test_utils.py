import libtorrent as lt


def create_isolated_session():
    return lt.session({
        "enable_dht": False,
        "enable_lsd": False,
        "enable_natpmp": False,
        "enable_upnp": False,
        "listen_interfaces": "127.0.0.1:0",
        "alert_mask": -1
    })
