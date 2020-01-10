# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.
"""Tests for the tvaf.audit module."""

import dataclasses

import tvaf.audit as audit_lib
import tvaf.const as const
from tvaf.tests import lib
from tvaf.types import Audit
from tvaf.types import TorrentStatus
from tvaf.types import Request


class TestGet(lib.TestCase):
    """Tests for tvaf.audit.AuditService.get()."""

    def setUp(self) -> None:
        self.app = lib.get_mock_app()

        for i, infohash in enumerate([
                "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                "8d532e88704b4f747b3e1083c2e6fd7dc53fdacf"
        ]):
            for j, tracker in enumerate(("foo", "cool")):
                for k, origin in enumerate(("user_a", "user_b")):
                    for generation in (1, 2):
                        atime = (12345678 + i + j * 2 + k * 4 + generation * 8)
                        lib.add_fixture_row(self.app,
                                            "audit",
                                            infohash=infohash,
                                            tracker=tracker,
                                            origin=origin,
                                            generation=generation,
                                            atime=atime,
                                            num_bytes=1)

    def test_no_grouping(self) -> None:
        audits = self.app.audit.get()
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 16)
        self.assert_golden_audit(*audits)

    def test_group_by_infohash(self) -> None:
        audits = self.app.audit.get(group_by=("infohash",))
        self.assertEqual(len(audits), 2)
        self.assertNotEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_tracker(self) -> None:
        audits = self.app.audit.get(group_by=("tracker",))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].infohash, None)
        self.assertNotEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_origin(self) -> None:
        audits = self.app.audit.get(group_by=("origin",))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertNotEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_generation(self) -> None:
        audits = self.app.audit.get(group_by=("generation",))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertNotEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_group_by_everything(self) -> None:
        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
        self.assertEqual(len(audits), 16)
        self.assertNotEqual(audits[0].infohash, None)
        self.assertNotEqual(audits[0].tracker, None)
        self.assertNotEqual(audits[0].origin, None)
        self.assertNotEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 1)
        self.assert_golden_audit(*audits)

    def test_filter_infohash(self) -> None:
        audits = self.app.audit.get(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash,
                         "da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_filter_tracker(self) -> None:
        audits = self.app.audit.get(tracker="foo")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, "foo")
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_filter_origin(self) -> None:
        audits = self.app.audit.get(origin="user_a")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, "user_a")
        self.assertEqual(audits[0].generation, None)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)

    def test_filter_generation(self) -> None:
        audits = self.app.audit.get(generation=1)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].infohash, None)
        self.assertEqual(audits[0].tracker, None)
        self.assertEqual(audits[0].origin, None)
        self.assertEqual(audits[0].generation, 1)
        self.assertEqual(audits[0].num_bytes, 8)
        self.assert_golden_audit(*audits)


class TestApply(lib.TestCase):
    """Tests for tvaf.audit.AuditService.apply()."""

    def setUp(self) -> None:
        self.app = lib.get_mock_app()

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
                        lib.add_fixture_row(self.app,
                                            "audit",
                                            infohash=infohash,
                                            tracker=tracker,
                                            origin=origin,
                                            generation=generation,
                                            atime=atime,
                                            num_bytes=1)

    def test_apply_to_empty(self) -> None:
        self.app.audit.apply(
            Audit(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                  tracker="foo",
                  origin="some_user",
                  generation=1,
                  atime=12345678,
                  num_bytes=1))
        audits = self.app.audit.get()
        self.assertEqual(audits[0].num_bytes, 1)
        self.assertEqual(audits[0].atime, 12345678)
        self.assert_golden_db(self.app)

    def test_apply_to_existing(self) -> None:
        self.add_fixture_data()
        self.app.audit.apply(
            Audit(infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
                  tracker="foo",
                  origin="some_user",
                  generation=1,
                  atime=23456789,
                  num_bytes=1))
        audits = self.app.audit.get(
            infohash="da39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(audits[0].num_bytes, 9)
        self.assertEqual(audits[0].atime, 23456789)
        self.assert_golden_db(self.app)


class TestCalculate(lib.TestCase):
    """Tests for tvaf.audit.calculate_audits."""

    def setUp(self) -> None:
        self.app = lib.get_mock_app()

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

        audits = audit_lib.calculate_audits(self.empty_status,
                                            self.empty_status, should_not_call)
        self.assertEqual(audits, [])

        audits = audit_lib.calculate_audits(self.complete_status,
                                            self.complete_status,
                                            should_not_call)
        self.assertEqual(audits, [])

    def test_changes_with_no_requests(self) -> None:
        time_val = 1234567
        with lib.mock_time(time_val):
            audits = audit_lib.calculate_audits(self.empty_status,
                                                self.complete_status,
                                                lambda: [])

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, const.ORIGIN_UNKNOWN)
        self.assertEqual(audits[0].atime, time_val)
        self.assertEqual(type(audits[0].atime), int)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_changes_with_requests(self) -> None:
        audits = audit_lib.calculate_audits(self.empty_status,
                                            self.complete_status,
                                            lambda: [self.normal_req])

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
        audits = audit_lib.calculate_audits(self.empty_status,
                                            self.complete_status,
                                            lambda: [self.normal_req])

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.normal_req.origin)
        self.assertEqual(audits[0].atime, self.normal_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_high_priority_req_wins(self) -> None:
        audits = audit_lib.calculate_audits(
            self.empty_status, self.complete_status,
            lambda: [self.normal_req, self.high_pri_req])

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.high_pri_req.origin)
        self.assertEqual(audits[0].atime, self.high_pri_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_deactivated_requests(self) -> None:
        self.normal_req.deactivated_at = 12345678
        audits = audit_lib.calculate_audits(self.empty_status,
                                            self.complete_status,
                                            lambda: [self.normal_req])

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].origin, self.normal_req.origin)
        self.assertEqual(audits[0].atime, self.normal_req.time)
        self.assertEqual(audits[0].num_bytes, 1048576)
        self.assertEqual(audits[0].infohash, self.empty_status.infohash)
        self.assertEqual(audits[0].tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_active_wins_vs_high_pri(self) -> None:
        self.high_pri_req.deactivated_at = 12345678
        audits = audit_lib.calculate_audits(
            self.empty_status, self.complete_status,
            lambda: [self.normal_req, self.high_pri_req])

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
        audits = audit_lib.calculate_audits(self.empty_status,
                                            self.complete_status,
                                            lambda: [self.normal_req, newer])

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
        audits = audit_lib.calculate_audits(
            self.empty_status, self.complete_status,
            lambda: [self.normal_req, self.high_pri_req])

        self.assertEqual(len(audits), 2)
        self.assertEqual(sum(a.num_bytes for a in audits), 1048576)
        self.assert_golden_audit(*audits)


class TestResolve(lib.TestCase):
    """Tests for tvaf.audit.AuditService.resolve_locked."""

    def setUp(self) -> None:
        self.app = lib.get_mock_app()
        lib.add_fixture_row(self.app,
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
            torrent_id="123",
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
            torrent_id="123",
            random=False,
            readahead=False)

    def test_no_changes(self) -> None:
        self.app.audit.resolve_locked([self.empty_status])

        audits = self.app.audit.get()
        audit = audits[0]
        self.assertEqual(audit.num_bytes, 0)

    def test_changes_with_no_requests(self) -> None:
        time_val = 1234567
        with lib.mock_time(time_val):
            self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
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
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
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
        lib.add_fixture_row(self.app, "torrent_status", **status_dict)
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
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
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.origin, self.normal_req.origin)
        self.assertEqual(audit.atime, self.normal_req.time)
        self.assertEqual(audit.num_bytes, 1048576)
        self.assertEqual(audit.infohash, self.empty_status.infohash)
        self.assertEqual(audit.tracker, self.empty_status.tracker)
        self.assert_golden_audit(*audits)

    def test_audit_high_pri_wins(self) -> None:
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.high_pri_req))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
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
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
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
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.high_pri_req))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
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
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.app, "request", **dataclasses.asdict(newer))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
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
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.normal_req))
        lib.add_fixture_row(self.app, "request",
                            **dataclasses.asdict(self.high_pri_req))

        self.app.audit.resolve_locked([self.complete_status])

        audits = self.app.audit.get(group_by=("infohash", "generation",
                                              "tracker", "origin"))
        self.assertEqual(len(audits), 2)
        self.assertEqual(sum(a.num_bytes for a in audits), 1048576)
        self.assert_golden_audit(*audits)
