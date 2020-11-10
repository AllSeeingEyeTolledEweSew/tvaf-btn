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
