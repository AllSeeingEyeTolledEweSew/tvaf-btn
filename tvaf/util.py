# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Utility functions for tvaf."""

from typing import Iterator
from typing import Tuple


def bitmap_is_set(bitmap: bytes, i: int) -> bool:
    """Returns True if bitmap is set at the i'th bit."""
    assert (i >> 3) < len(bitmap), f"{i} out of range ({len(bitmap)})"
    return bool(bitmap[i >> 3] & (0x80 >> (i & 7)))


def iter_bitmap(bitmap: bytes, start: int, stop: int) -> Iterator[bool]:
    """Yields a boolean for the i'th bit in bitmap, for start <= i < stop."""
    for i in range(start, stop):
        yield bitmap_is_set(bitmap, i)


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


def enum_piece_is_set(bitmap: bytes, piece_length: int, start: int,
                      stop: int) -> Iterator[Tuple[int, bool]]:
    """Yields a (piece, is_set) tuple for each piece of a byte range.

    The given byte range (start, stop) is converted to a piece range. For every
    piece in that piece range, this function yields a (piece, is_set) tuple.

    Args:
        bitmap: A piece-indexed bitmap.
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Yields:
        A (piece, is_set) tuple, for each piece overlapping the input range.
    """
    for piece in range(*range_to_pieces(piece_length, start, stop)):
        yield (piece, bitmap_is_set(bitmap, piece))


def iter_piece_is_set(bitmap: bytes, piece_length: int, start: int,
                      stop: int) -> Iterator[bool]:
    """Yields whether each piece overlapping a byte range is set.

    The given byte range (start, stop) is converted to a piece range. For every
    piece in that piece range, this function yields whether the corresponding
    bit in bitmap is set.

    Args:
        bitmap: A piece-indexed bitmap.
        piece_length: The length of a piece.
        start: The first byte of the range.
        stop: The last byte of the range, plus one.

    Yields:
        A boolean for each bit in bitmap, corresponding to pieces overlapping
            the given byte range.
    """
    for _, is_set in enum_piece_is_set(bitmap, piece_length, start, stop):
        yield is_set


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
