# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for audit functions in the tvaf.dal module."""

import dataclasses

import apsw

import tvaf.const as const
from tvaf import dal
from tvaf.tests import lib
from tvaf.types import Audit
from tvaf.types import Request
from tvaf.types import TorrentStatus


class TestGet(lib.TestCase):
    """Tests for tvaf.dal.get_audits()."""

    def setUp(self) -> None:
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

        for i, infohash in enumerate([
                "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                "8d532e88704b4f747b3e1083c2e6fd7dc53fdacf"
        ]):
            for j, tracker in enumerate(("foo", "cool")):
                for k, origin in enumerate(("user_a", "user_b")):
                    for generation in (1, 2):
                        atime = (12345678 + i + j * 2 + k * 4 + generation * 8)
                        lib.add_fixture_row(self.conn,
                                            "audit",
                                            infohash=infohash,
                                            tracker=tracker,
                                            origin=origin,
                                            generation=generation,
                                            atime=atime,
                                            num_bytes=1)

    def test_no_grouping(self) -> None:
        audits = list(dal.get_audits(self.conn))
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 16)
        self.assert_golden_audit(*audits)

    def test_group_by_infohash(self) -> None:
        audits = list(dal.get_audits(self.conn, group_by=("infohash",)))
        self.assertEqual(len(audits), 2)
        self.assertNotEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_tracker(self) -> None:
        audits = list(dal.get_audits(self.conn, group_by=("tracker",)))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].infohash, None)
        self.assertNotEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_origin(self) -> None:
        audits = list(dal.get_audits(self.conn, group_by=("origin",)))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertNotEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_generation(self) -> None:
        audits = list(dal.get_audits(self.conn, group_by=("generation",)))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertNotEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_everything(self) -> None:
        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 16)
        self.assertNotEqual(audits[0].infohash, None)
        self.assertNotEqual(audits[0].tracker, None)
        self.assertNotEqual(audits[0].origin, None)
        self.assertNotEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 1)
        self.assert_golden_audit(*audits)

    def test_filter_infohash(self) -> None:
        audits = list(
            dal.get_audits(self.conn,
                           infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709"))
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash,
                         "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_filter_tracker(self) -> None:
        audits = list(dal.get_audits(self.conn, tracker="foo"))
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, "foo")
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_filter_origin(self) -> None:
        audits = list(dal.get_audits(self.conn, origin="user_a"))
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, "user_a")
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_filter_generation(self) -> None:
        audits = list(dal.get_audits(self.conn, generation=1))
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, 1)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)


class TestApply(lib.TestCase):
    """Tests for tvaf.dal.apply_audits()."""

    def setUp(self) -> None:
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

    def add_fixture_data(self) -> None:
        """Add some fixture data."""
        for i, infohash in enumerate([
                "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                "8d532e88704b4f747b3e1083c2e6fd7dc53fdacf"
        ]):
            for j, tracker in enumerate(("foo", "cool")):
                for k, origin in enumerate(("user_a", "user_b")):
                    for generation in (1, 2):
                        atime = (12345678 + i + j * 2 + k * 4 + generation * 8)
                        lib.add_fixture_row(self.conn,
                                            "audit",
                                            infohash=infohash,
                                            tracker=tracker,
                                            origin=origin,
                                            generation=generation,
                                            atime=atime,
                                            num_bytes=1)

    def test_apply_to_empty(self) -> None:
        dal.apply_audits(
            self.conn,
            Audit(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                  tracker="foo",
                  origin="some_user",
                  generation=1,
                  atime=12345678,
                  num_bytes=1))
        audits = list(dal.get_audits(self.conn))
        self.assertEqual(audits[0].num_bytes, 1)
        self.assertEqual(audits[0].atime, 12345678)
        self.assert_golden_db(self.conn)

    def test_apply_to_existing(self) -> None:
        self.add_fixture_data()
        dal.apply_audits(
            self.conn,
            Audit(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                  tracker="foo",
                  origin="some_user",
                  generation=1,
                  atime=23456789,
                  num_bytes=1))
        audits = list(
            dal.get_audits(self.conn,
                           infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709"))
        self.assertEqual(audits[0].num_bytes, 9)
        self.assertEqual(audits[0].atime, 23456789)
        self.assert_golden_db(self.conn)


class TestCalculate(lib.TestCase):
    """Tests for tvaf.dal.calculate_audits()."""

    def setUp(self) -> None:
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)

        self.empty_status = TorrentStatus(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            tracker="foo",
            piece_bitmap=b"\x00\x00",
            piece_length=65536,
            length=1048576,
            seeders=0,
            leechers=0,
            announce_message="ok")
        self.first_half_status = TorrentStatus(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            tracker="foo",
            piece_bitmap=b"\xff\x00",
            piece_length=65536,
            length=1048576,
            seeders=0,
            leechers=0,
            announce_message="ok")
        self.complete_status = TorrentStatus(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            tracker="foo",
            piece_bitmap=b"\xff\xff",
            piece_length=65536,
            length=1048576,
            seeders=0,
            leechers=0,
            announce_message="ok")

        self.normal_req = Request(
            request_id=1,
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            origin="normal",
            priority=1000,
            start=0,
            stop=1048576,
            time=12345678)
        self.high_pri_req = Request(
            request_id=2,
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            origin="high_pri",
            priority=10000,
            start=0,
            stop=1048576,
            time=12345678)

    def test_no_changes(self) -> None:

        def should_not_call():
            assert False

        audits = list(
            dal.calculate_audits(self.empty_status, self.empty_status,
                                 should_not_call))
        self.assertEqual(audits, [])

        audits = list(
            dal.calculate_audits(self.complete_status, self.complete_status,
                                 should_not_call))
        self.assertEqual(audits, [])

    def test_changes_with_no_requests(self) -> None:
        time_val = 1234567
        with lib.mock_time(time_val):
            audits = list(
                dal.calculate_audits(self.empty_status, self.complete_status,
                                     lambda: []))

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, const.ORIGIN_UNKNOWN)
        self.assertEqual(audits[0].atime, time_val)
        self.assertEqual(type(audits[0].atime), int)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_changes_with_requests(self) -> None:
        audits = list(
            dal.calculate_audits(self.empty_status, self.complete_status,
                                 lambda: [self.normal_req]))

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.normal_req.origin)
        self.assertEqual(audits[0].atime, self.normal_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_piece_lengths(self) -> None:
        self.normal_req.start = 10000
        self.normal_req.stop = 1000000
        audits = list(
            dal.calculate_audits(self.empty_status, self.complete_status,
                                 lambda: [self.normal_req]))

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.normal_req.origin)
        self.assertEqual(audits[0].atime, self.normal_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_high_priority_req_wins(self) -> None:
        audits = list(
            dal.calculate_audits(self.empty_status, self.complete_status,
                                 lambda: [self.normal_req, self.high_pri_req]))

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.high_pri_req.origin)
        self.assertEqual(audits[0].atime, self.high_pri_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_deactivated_requests(self) -> None:
        self.normal_req.deactivated_at = 12345678
        audits = list(
            dal.calculate_audits(self.empty_status, self.complete_status,
                                 lambda: [self.normal_req]))

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.normal_req.origin)
        self.assertEqual(audits[0].atime, self.normal_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_active_wins_vs_high_pri(self) -> None:
        self.high_pri_req.deactivated_at = 12345678
        audits = list(
            dal.calculate_audits(self.empty_status, self.complete_status,
                                 lambda: [self.normal_req, self.high_pri_req]))

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.normal_req.origin)
        self.assertEqual(audits[0].atime, self.normal_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_newer_request_wins(self) -> None:
        newer = Request(**dataclasses.asdict(self.normal_req))
        newer.time += 100
        newer.origin = "newer"
        audits = list(
            dal.calculate_audits(self.empty_status, self.complete_status,
                                 lambda: [self.normal_req, newer]))

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, newer.origin)
        self.assertEqual(audits[0].atime, newer.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_multiple_audits(self) -> None:
        self.normal_req.stop = 524288
        self.high_pri_req.start = 524288
        audits = list(
            dal.calculate_audits(self.empty_status, self.complete_status,
                                 lambda: [self.normal_req, self.high_pri_req]))

        self.assertEqual(len(audits), 2)
        self.assertEqual(sum(a.num_bytes for a in audits), 1048576)
        self.assert_golden_audit(*audits)


class TestResolve(lib.TestCase):
    """Tests for tvaf.dal._resolve_audits_locked()."""

    def setUp(self) -> None:
        self.conn = apsw.Connection(":memory:")
        dal.create_schema(self.conn)
        lib.add_fixture_row(self.conn,
                            "torrent_meta",
                            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                            generation=1)

        self.empty_status = TorrentStatus(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            tracker="foo",
            piece_bitmap=b"\x00\x00",
            piece_length=65536,
            length=1048576,
            seeders=0,
            leechers=0,
            announce_message="ok")
        self.first_half_status = TorrentStatus(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            tracker="foo",
            piece_bitmap=b"\xff\x00",
            piece_length=65536,
            length=1048576,
            seeders=0,
            leechers=0,
            announce_message="ok")
        self.complete_status = TorrentStatus(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            tracker="foo",
            piece_bitmap=b"\xff\xff",
            piece_length=65536,
            length=1048576,
            seeders=0,
            leechers=0,
            announce_message="ok")

        self.normal_req = Request(
            request_id=1,
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            origin="normal",
            priority=1000,
            start=0,
            stop=1048576,
            time=12345678,
            tracker="foo",
            random=False,
            readahead=False)
        self.high_pri_req = Request(
            request_id=2,
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            origin="high_pri",
            priority=10000,
            start=0,
            stop=1048576,
            time=12345678,
            tracker="foo",
            random=False,
            readahead=False)

    def test_no_changes(self) -> None:
        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.empty_status])

        audits = list(dal.get_audits(self.conn))
        audit = audits[0]
        self.assertEqual(audit.num_bytes, 0)

    def test_changes_with_no_requests(self) -> None:
        time_val = 1234567
        with lib.mock_time(time_val):
            # pylint: disable=protected-access
            dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, const.ORIGIN_UNKNOWN)
        self.assertEqual(audit.atime, time_val)
        self.assertEqual(type(audit.atime), int)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.complete_status.infohash)
        self.assertEqual(audit.tracker, self.complete_status.tracker)
        self.assert_golden_audit(*audits)

    def test_changes_with_requests(self) -> None:
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, self.normal_req.origin)
        self.assertEqual(audit.atime, self.normal_req.time)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.complete_status.infohash)
        self.assertEqual(audit.tracker, self.complete_status.tracker)
        self.assert_golden_audit(*audits)

    def test_half_changes_with_requests(self) -> None:
        status_dict = dataclasses.asdict(self.first_half_status)
        status_dict.pop("files")
        lib.add_fixture_row(self.conn, "torrent_status", **status_dict)
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, self.normal_req.origin)
        self.assertEqual(audit.atime, self.normal_req.time)
        self.assertEqual(audit.num_bytes, 524288)
        self.assertEqual(audit.infohash, self.complete_status.infohash)
        self.assertEqual(audit.tracker, self.complete_status.tracker)
        self.assert_golden_audit(*audits)

    def test_audit_piece_lengths(self) -> None:
        self.normal_req.start = 10000
        self.normal_req.stop = 1000000
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, self.normal_req.origin)
        self.assertEqual(audit.atime, self.normal_req.time)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.empty_status.infohash)
        self.assertEqual(audit.tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_audit_high_pri_wins(self) -> None:
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.high_pri_req))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, self.high_pri_req.origin)
        self.assertEqual(audit.atime, self.high_pri_req.time)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.empty_status.infohash)
        self.assertEqual(audit.tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_deactivated_request(self) -> None:
        self.normal_req.deactivated_at = 12345678
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, self.normal_req.origin)
        self.assertEqual(audit.atime, self.normal_req.time)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.empty_status.infohash)
        self.assertEqual(audit.tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_active_wins_vs_high_pri(self) -> None:
        self.high_pri_req.deactivated_at = 12345678
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.high_pri_req))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, self.normal_req.origin)
        self.assertEqual(audit.atime, self.normal_req.time)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.empty_status.infohash)
        self.assertEqual(audit.tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_newer_request_wins(self) -> None:
        newer = Request(**dataclasses.asdict(self.normal_req))
        newer.request_id = 2
        newer.time += 100
        newer.origin = "newer"
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.conn, "request", **dataclasses.asdict(newer))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, newer.origin)
        self.assertEqual(audit.atime, newer.time)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.empty_status.infohash)
        self.assertEqual(audit.tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_multiple_audits(self) -> None:
        self.normal_req.stop = 524288
        self.high_pri_req.start = 524288
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.conn, "request",
                            **dataclasses.asdict(self.high_pri_req))

        # pylint: disable=protected-access
        dal._resolve_audits_locked(self.conn, [self.complete_status])

        audits = list(
            dal.get_audits(self.conn,
                           group_by=("infohash", "generation", "tracker",
                                     "origin")))
        self.assertEqual(len(audits), 2)
        self.assertEqual(sum(a.num_bytes for a in audits), 1048576)
        self.assert_golden_audit(*audits)
