import concurrent.futures
import io

import libtorrent as lt

from tvaf import torrent_io
from tvaf import types

from . import request_test_utils
from . import tdummy


class TestBufferedTorrentIO(request_test_utils.RequestServiceTestCase):

    def setUp(self):
        super().setUp()
        self.executor = concurrent.futures.ThreadPoolExecutor()

    def open(self):
        tslice = types.TorrentSlice(info_hash=tdummy.INFOHASH,
                                    start=0,
                                    stop=tdummy.LEN)
        return torrent_io.BufferedTorrentIO(
            request_service=self.service,
            tslice=tslice,
            get_torrent=lambda: lt.bencode(tdummy.DICT),
            user="tvaf")

    def test_read_some(self):
        future = self.executor.submit(self.open().read, 1024)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="read")
        self.assertEqual(future.result(), tdummy.DATA[:1024])

    def test_read_with_explicit_close(self):
        fp = self.open()
        future = self.executor.submit(fp.read, 1024)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="read")
        self.assertEqual(future.result(), tdummy.DATA[:1024])
        fp.close()
        self.assertTrue(fp.closed)

    def test_context_manager_with_read(self):
        with self.open() as fp:
            future = self.executor.submit(fp.read, 1024)
            self.feed_pieces()
            self.pump_alerts(future.done, msg="read")
            self.assertEqual(future.result(), tdummy.DATA[:1024])

    def test_read_all(self):
        future = self.executor.submit(self.open().read)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="read")
        self.assertEqual(future.result(), tdummy.DATA)

    def test_readinto(self):
        array = bytearray(1024)
        future = self.executor.submit(self.open().readinto, array)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="readinto")
        self.assertEqual(future.result(), 1024)
        self.assertEqual(array, tdummy.DATA[:1024])

    def test_read1(self):
        future = self.executor.submit(self.open().read1)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="read1")
        self.assertEqual(future.result(), tdummy.PIECES[0])

    def test_readinto1(self):
        array = bytearray(tdummy.LEN)
        future = self.executor.submit(self.open().readinto1, array)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="readinto1")
        self.assertEqual(future.result(), len(tdummy.PIECES[0]))
        self.assertEqual(array[:len(tdummy.PIECES[0])], tdummy.PIECES[0])

    def test_misc_methods(self):
        fp = self.open()

        self.assertTrue(fp.seekable())
        self.assertTrue(fp.readable())
        self.assertFalse(fp.writable())

        with self.assertRaises(OSError):
            fp.fileno()
        with self.assertRaises(OSError):
            fp.write(b"data")

    def test_seek_and_read(self):
        fp = self.open()

        fp.seek(0, io.SEEK_END)
        self.assertEqual(fp.tell(), tdummy.LEN)

        fp.seek(1024)
        self.assertEqual(fp.tell(), 1024)
        future = self.executor.submit(fp.read, 1024)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="read")
        self.assertEqual(future.result(), tdummy.DATA[1024:2048])

    def test_second_read_buffered(self):
        fp = self.open()
        future = self.executor.submit(fp.read, 1024)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="read")
        self.assertEqual(future.result(), tdummy.DATA[:1024])

        # The data should be buffered, so we shouldn't need to pump_alerts
        second = fp.read(1024)
        self.assertEqual(second, tdummy.DATA[1024:2048])

    def test_second_read_partial_buffer(self):
        fp = self.open()
        future = self.executor.submit(fp.read, 1024)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="first read")
        self.assertEqual(future.result(), tdummy.DATA[:1024])

        # The data should be partially buffered. We'll need to pump_alerts
        # again.
        future = self.executor.submit(fp.read, tdummy.PIECE_LENGTH)
        self.pump_alerts(future.done, msg="second read")
        self.assertEqual(future.result(),
                         tdummy.DATA[1024:tdummy.PIECE_LENGTH + 1024])

    def test_seek_resets_buffer(self):
        fp = self.open()
        future = self.executor.submit(fp.read, 1024)
        self.feed_pieces()
        self.pump_alerts(future.done, msg="first read")
        self.assertEqual(future.result(), tdummy.DATA[:1024])

        # Seek back to the start. The buffer should reset, but reads should
        # work as normal.
        fp.seek(0)
        future = self.executor.submit(fp.read, 1024)
        self.pump_alerts(future.done, msg="second read")
        self.assertEqual(future.result(), tdummy.DATA[:1024])
