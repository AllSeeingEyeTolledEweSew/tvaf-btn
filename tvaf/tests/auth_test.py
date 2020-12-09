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

import concurrent.futures
import unittest

from tvaf import auth


class TestAuthService(unittest.TestCase):
    def setUp(self):
        self.auth_service = auth.AuthService()

    def test_auth_good(self):
        self.auth_service.auth_password_plain(
            self.auth_service.USER, self.auth_service.PASSWORD
        )

    def test_auth_bad(self):
        with self.assertRaises(auth.AuthenticationFailed):
            self.auth_service.auth_password_plain("invalid", "invalid")

    def test_push_get_pop(self):
        self.assertEqual(self.auth_service.get_user(), None)
        self.auth_service.push_user("username")
        self.assertEqual(self.auth_service.get_user(), "username")
        self.auth_service.pop_user()
        self.assertEqual(self.auth_service.get_user(), None)

    def test_push_contextmanager(self):
        self.assertEqual(self.auth_service.get_user(), None)
        with self.auth_service.push_user("username"):
            self.assertEqual(self.auth_service.get_user(), "username")
        self.assertEqual(self.auth_service.get_user(), None)

    def test_threading(self):
        def run_test(username):
            self.assertEqual(self.auth_service.get_user(), None)
            with self.auth_service.push_user(username):
                self.assertEqual(self.auth_service.get_user(), username)
            self.assertEqual(self.auth_service.get_user(), None)

        self.assertEqual(self.auth_service.get_user(), None)
        with self.auth_service.push_user("main_thread_user"):
            self.assertEqual(self.auth_service.get_user(), "main_thread_user")

            # Use executor to propagate exceptions
            executor = concurrent.futures.ThreadPoolExecutor()
            executor.submit(run_test, "second_thread_user").result()
        self.assertEqual(self.auth_service.get_user(), None)
