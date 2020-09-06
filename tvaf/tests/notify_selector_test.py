import selectors
import threading
import time
import unittest

from tvaf import notify_selector
from tvaf import util


class NotifySelectorTest(unittest.TestCase):

    TEST_CLASS = notify_selector.NotifySelector

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
