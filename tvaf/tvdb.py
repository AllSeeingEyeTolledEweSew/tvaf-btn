# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import contextlib
import json
import logging
import threading
import urllib.parse

import requests


def log():
    return logging.getLogger(__name__)


class Tvdb(object):

    API_KEY = "0629B785CE550C8D"
    HOST = "api.thetvdb.com"

    def __init__(self, apikey=None, username=None, userkey=None,
                 max_connections=10, max_retries=10):
        self.apikey = apikey or self.API_KEY
        self.username = username
        self.userkey = userkey

        self._lock = threading.RLock()
        self._token = None
        self._languages = None
        self.session = requests.Session()
        retries= requests.packages.urllib3.util.retry.Retry(
            total=None, connect=max_retries, read=max_retries,
            backoff_factor=0.1, status_forcelist=(500, 502, 503, 504))
        adapter = requests.adapters.HTTPAdapter(
            max_retries=retries, pool_connections=max_connections,
            pool_maxsize=max_connections)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    @property
    def token(self):
        with self._lock:
            if self._token is not None:
                return self._token
            payload = {"apikey": self.apikey}
            if self.username is not None:
                payload["username"] = self.username
            if self.userkey is not None:
                payload["userkey"] = self.userkey
            r = self.post_noauth("/login", payload)
            assert r.status_code == 200, (r.status_code, r.headers, r.text)
            self._token = r.json()["token"]
            return self._token

    def call_noauth(self, method, path, headers=None, **kwargs):
        headers = headers or {}
        headers["Accept"] = "application/json"
        url = urllib.parse.urlunparse(
            ("https", self.HOST, path, None, None, None))
        return getattr(self.session, method)(
            url, headers=headers, timeout=5, **kwargs)

    def call(self, method, path, headers=None, **kwargs):
        headers = headers or {}
        headers["Authorization"] = "Bearer " + self.token
        return self.call_noauth(method, path, headers=headers, **kwargs)

    def post(self, path, data, headers=None, **kwargs):
        headers = headers or {}
        headers["Content-Type"] = "application/json"
        return self.call(
            "post", data=json.dumps(data or {}), headers=headers, **kwargs)

    def post_noauth(self, path, data, headers=None, **kwargs):
        headers = headers or {}
        headers["Content-Type"] = "application/json"
        return self.call_noauth(
            "post", path, data=json.dumps(data or {}), headers=headers,
            **kwargs)

    def get(self, path, **kwargs):
        return self.call("get", path, **kwargs)

    @property
    def languages(self):
        with self._lock:
            if self._languages is not None:
                return self._languages
            r = self.get("/languages")
            assert r.status_code == 200, (r.status_code, r.headers, r.text)
            self._languages = r.json()["data"]
            return self._languages
