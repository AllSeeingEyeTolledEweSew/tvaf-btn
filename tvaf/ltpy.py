import libtorrent as lt
import os
from typing import Optional


class Error(Exception):

    CATEGORY = None

    def __init__(self, ec):
        super().__init__(ec.message())
        self.ec = ec
        self.value = ec.value()
        self.category = ec.category()


class LibtorrentError(Error):

    CATEGORY = lt.libtorrent_category()


class UPNPError(Error):

    CATEGORY = lt.upnp_category()


class HTTPError(Error):

    CATEGORY = lt.http_category()


class SocksError(Error):

    CATEGORY = lt.socks_category()


class BdecodeError(Error):

    CATEGORY = lt.bdecode_category()


class I2PError(Error):

    CATEGORY = lt.i2p_category()


class UnknownError(Error):

    pass


_GENERIC_CATEGORY = lt.generic_category()
_SYSTEM_CATEGORY = lt.system_category()


def exception_from_error_code(ec: lt.error_code) -> Optional[Exception]:
    # libtorrent represents non-errors as a non-None error_code object with a
    # value of 0
    if not ec.value():
        return None

    category = ec.category()

    # Look up various categories of application-level errors
    for exc_type in (LibtorrentError, UPNPError, HTTPError, SocksError, BdecodeError, I2PError):
        if category == exc_type.CATEGORY:
            return exc_type(ec)

    # generic_category seems to be meant for "portable" errno values, and
    # system_category is meant for "system-specific" errors.

    # libtorrent uses generic_category for errors in platform-independent code,
    # and system_category for any code which is specialized between windows and
    # not-windows, which includes file i/o code. On windows, the error codes
    # are [WSA]GetLastError values; on not-windows they are errno values.
    if category == _GENERIC_CATEGORY or (os.name != "nt" and category ==
            _SYSTEM_CATEGORY):
        return OSError(ec.value(), ec.message())

    if os.name == "nt" and category == _SYSTEM_CATEGORY:
        # TIL: under windows, if the 4th arg is an int, Python will treat it as
        # a "winerror", and will derive an "approximate translation" value for
        # errno, ignoring the 1st arg
        return OSError(0, ec.message(), None, ec.value())

    return UnknownError(ec)


def exception_from_alert(alert: lt.alert) -> Optional[Exception]:
    ec = getattr(alert, "error", None)
    if not ec:
        return None
    return exception_from_error_code(ec)
