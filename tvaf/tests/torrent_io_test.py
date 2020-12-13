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

import io

from tvaf import torrent_io

from . import request_test_utils


class TestBufferedTorrentIO(request_test_utils.RequestServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        atp = self.torrent.atp()
        self.service.configure_atp(atp)
        self.session.add_torrent(atp)
        self.feed_pieces()

    def open(self) -> torrent_io.BufferedTorrentIO:
        return torrent_io.BufferedTorrentIO(
            request_service=self.service,
            info_hash=self.torrent.info_hash,
            start=0,
            stop=self.torrent.length,
            configure_atp=self.torrent.configure_atp,
        )

    def test_read_some(self) -> None:
        data = self.open().read(1024)
        self.assertEqual(data, self.torrent.data[:1024])

    def test_read_with_explicit_close(self) -> None:
        fp = self.open()
        data = fp.read(1024)
        self.assertEqual(data, self.torrent.data[:1024])
        fp.close()
        self.assertTrue(fp.closed)

    def test_context_manager_with_read(self) -> None:
        with self.open() as fp:
            data = fp.read(1024)
            self.assertEqual(data, self.torrent.data[:1024])

    def test_read_all(self) -> None:
        data = self.open().read()
        self.assertEqual(data, self.torrent.data)

    def test_readinto(self) -> None:
        array = bytearray(1024)
        value = self.open().readinto(array)
        self.assertEqual(value, 1024)
        self.assertEqual(array, self.torrent.data[:1024])

    def test_read1(self) -> None:
        data = self.open().read1()
        self.assertEqual(data, self.torrent.pieces[0])

    def test_readinto1(self) -> None:
        array = bytearray(self.torrent.length)
        value = self.open().readinto1(array)
        self.assertEqual(value, len(self.torrent.pieces[0]))
        self.assertEqual(
            array[: len(self.torrent.pieces[0])], self.torrent.pieces[0]
        )

    def test_misc_methods(self) -> None:
        fp = self.open()

        self.assertTrue(fp.seekable())
        self.assertTrue(fp.readable())
        self.assertFalse(fp.writable())

        with self.assertRaises(OSError):
            fp.fileno()
        with self.assertRaises(OSError):
            fp.write(b"data")

    def test_seek_and_read(self) -> None:
        fp = self.open()

        fp.seek(0, io.SEEK_END)
        self.assertEqual(fp.tell(), self.torrent.length)

        fp.seek(1024)
        self.assertEqual(fp.tell(), 1024)
        data = fp.read(1024)
        self.assertEqual(data, self.torrent.data[1024:2048])

    def test_second_read_buffered(self) -> None:
        fp = self.open()
        data = fp.read(1024)
        self.assertEqual(data, self.torrent.data[:1024])

        # The data should be buffered
        second = fp.read(1024)
        self.assertEqual(second, self.torrent.data[1024:2048])

    def test_second_read_partial_buffer(self) -> None:
        fp = self.open()
        data = fp.read(1024)
        self.assertEqual(data, self.torrent.data[:1024])

        # The data should be partially buffered
        data = fp.read(self.torrent.piece_length)
        self.assertEqual(
            data, self.torrent.data[1024 : self.torrent.piece_length + 1024]
        )

    def test_seek_resets_buffer(self) -> None:
        fp = self.open()
        data = fp.read(1024)
        self.assertEqual(data, self.torrent.data[:1024])

        # Seek back to the start. The buffer should reset, but reads should
        # work as normal.
        fp.seek(0)
        data = fp.read(1024)
        self.assertEqual(data, self.torrent.data[:1024])
