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
from typing import Type

from tvaf import util


class _Sentinel:
    pass


SENTINEL = _Sentinel()


# Type annotating this is cumbersome, because typeshed's annotations aren't
# publicly visible so I have to define FileDescriptorLike, etc. It seems to
# typecheck if I leave everything un-annotated though.
class NotifySelector(selectors.DefaultSelector):
    def __init__(self):
        super().__init__()
        self.notify_rfile, self.notify_wfile = util.selectable_pipe()
        super().register(
            self.notify_rfile, selectors.EVENT_READ, data=SENTINEL
        )

    def notify(self) -> None:
        self.notify_wfile.write(b"\0")

    def register(self, fileobj, events, data=None):
        key = super().register(fileobj, events, data=data)
        self.notify()
        return key

    def modify(self, fileobj, events, data=None):
        key = super().register(fileobj, events, data=data)
        self.notify()
        return key

    def unregister(self, fileobj):
        key = super().unregister(fileobj)
        self.notify()
        return key


DefaultNotifySelector: Type[selectors.BaseSelector]
if hasattr(selectors, "EpollSelector"):
    DefaultNotifySelector = selectors.EpollSelector
else:
    DefaultNotifySelector = NotifySelector
