# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Utility functions for tvaf."""

from typing import Iterator
from typing import Tuple


def range_to_pieces(piece_length: int, start: int,
                    stop: int) -> Tuple[int, int]:
    """Converts a range of bytes to a range of pieces.

    Pieces are assumed to be zero-aligned.

    Args:
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Returns:
        A (start_piece, stop_piece) tuple, where start_piece is the first piece
            overlapping the input range, and stop_piece is the last piece
            overlapping the input range, plus one.
    """
    # Any cleaner way to do this?
    if stop <= start:
        return (start // piece_length, start // piece_length)
    return (start // piece_length, (stop - 1) // piece_length + 1)


def enum_piecewise_ranges(piece_length: int, start: int,
                          stop: int) -> Iterator[Tuple[int, int, int]]:
    """Splits a byte range into smaller piece-aligned ranges.

    The given byte range (start, stop) is split into smaller sub-ranges, such
    that each sub-range overlaps exactly one piece of piece_length.

    Args:
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Yields:
        Tuples of (piece, start, stop).
    """
    for piece in range(*range_to_pieces(piece_length, start, stop)):
        r_start = piece * piece_length
        r_stop = (piece + 1) * piece_length
        if r_start < start:
            r_start = start
        if r_stop > stop:
            r_stop = stop
        yield piece, r_start, r_stop


class Bitmap:

    def __init__(self, map_bytes: bytes) -> None:
        self.map_bytes = map_bytes

    def __len__(self) -> int:
        """Returns the length of the bitmap."""
        return len(self.map_bytes) * 8

    def __getitem__(self, index: int) -> bool:
        """Returns True if bitmap is set at the i'th bit."""
        if not isinstance(index, int):
            raise TypeError(index)
        if index < 0 or index >= len(self):
            raise KeyError(index)
        return bool(self.map_bytes[index >> 3] & (0x80 >> (index & 7)))
