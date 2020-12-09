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

import selectors
import threading
import time
from typing import Type
import unittest

from tvaf import notify_selector
from tvaf import util


class NotifySelectorTest(unittest.TestCase):

    TEST_CLASS: Type[selectors.BaseSelector] = notify_selector.NotifySelector

    def test_register_while_selecting(self):
        rfile, wfile = util.selectable_pipe()
        wfile.write(b"\0")
        selector = self.TEST_CLASS()

        def register_from_thread():
            # Is there a way to synchronize this?
            time.sleep(0.1)
            selector.register(rfile, selectors.EVENT_READ)

        threading.Thread(target=register_from_thread).start()
        # The selector may return the notify pipe
        while True:
            events = selector.select(timeout=5)
            # Check timeout
            self.assertNotEqual(events, [])
            for key, _ in events:
                # The selector may return the notify pipe
                if key.data == notify_selector.SENTINEL:
                    continue
                if key.fileobj == rfile:
                    return


class DefaultNotifySelectorTest(NotifySelectorTest):

    TEST_CLASS = notify_selector.DefaultNotifySelector
