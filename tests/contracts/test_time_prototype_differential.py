"""Read-only differential against the frozen prototype time model (ca-time/0.1-spike at c21b50d).

The prototype is loaded from its file without modifying it. Agreements are asserted, and every
intentional difference listed in docs/phase2/ca-p2-002/ca-p2-002b.md is asserted to exist, so the
documentation cannot drift from actual behavior. The product package never imports the prototype.
"""

import importlib.util
import json
import unittest

import _support
from cloud_autopsy.contracts import timeinterval as ti

PROTOTYPE_TIME = _support.REPO / "prototype" / "ca_spike" / "timemodel.py"
VECTORS = _support.PACKAGE / "contracts" / "vectors" / (ti.TIME_VERSION.replace("/", "-") + ".json")


def load_prototype():
    spec = importlib.util.spec_from_file_location("frozen_prototype_timemodel", PROTOTYPE_TIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proto_epoch(proto, raw):
    try:
        return proto.parse_rfc3339_ms(raw)
    except proto.TimestampError:
        return None


def new_epoch(raw):
    try:
        return ti.parse_rfc3339(raw).epoch_ns // ti.NS_PER_MS
    except ti.TimeError:
        return None


class PrototypeDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proto = load_prototype()
        cls.doc = json.loads(VECTORS.read_bytes().decode("utf-8"))

    def test_agrees_on_epoch_milliseconds_for_years_1_to_9999(self):
        for v in self.doc["parse_valid"]:
            if v["raw"].startswith("0000"):
                continue
            with self.subTest(v["id"]):
                self.assertEqual(proto_epoch(self.proto, v["raw"]), v["epoch_ms"])

    def test_agrees_on_rejecting_malformed_calendar_and_offset_errors(self):
        differs = {"trailing-newline", "non-ascii-digits", "fullwidth-digits"}
        for v in self.doc["parse_invalid"]:
            if v["id"] in differs:
                continue
            with self.subTest(v["id"]):
                self.assertIsNone(proto_epoch(self.proto, v["raw"]))

    def test_d1_year_zero_accepted_only_by_new_contract(self):
        raw = "0000-01-01T00:00:00Z"
        self.assertIsNone(proto_epoch(self.proto, raw))
        self.assertEqual(new_epoch(raw), -62167219200000)

    def test_d2_prototype_accepts_trailing_newline(self):
        raw = "2026-11-03T08:15:30Z\n"
        self.assertEqual(proto_epoch(self.proto, raw), 1793693730000)
        self.assertIsNone(new_epoch(raw))

    def test_d3_prototype_accepts_non_ascii_digits(self):
        raw = "٢٠٢٦-11-03T08:15:30Z"
        self.assertEqual(proto_epoch(self.proto, raw), 1793693730000)
        self.assertIsNone(new_epoch(raw))

    def test_d4_leap_second_retained_with_distinct_status(self):
        raw = "2016-12-31T23:59:60Z"
        old = self.proto.build_time({"type": "event_time", "raw": raw, "clock_domain": "ref"}, {})
        self.assertEqual(old.parse_status, "error")
        new = ti.source_timestamp(raw, timestamp_kind="event_time", clock_domain_id="ref")
        self.assertEqual((new.parse_status, new.raw), (ti.LEAP_SECOND, raw))

    def test_d5_text_precision_cannot_be_narrowed_by_declaration(self):
        raw = "2026-11-03T08:15:30Z"
        old = self.proto.build_time({"type": "event_time", "raw": raw, "clock_domain": "ref", "precision_ms": 1}, {})
        self.assertEqual((old.local_lower_ms, old.local_upper_ms), (1793693730000, 1793693730000))
        new = ti.source_timestamp(raw, timestamp_kind="event_time", clock_domain_id="ref",
                                  declared_precision_ns=1_000_000)
        self.assertEqual((new.local_lower_ms, new.local_upper_ms), (1793693730000, 1793693730999))

    def test_d6_same_domain_order_requires_declared_continuity(self):
        # 0.2-provisional: unknown continuity fails closed (was reference_overlap in 0.1).
        clocks = {"node": {"status": "declared", "precision_ms": 1, "offset_ms": 0, "offset_uncertainty_ms": 500}}
        entries = [{"type": "event_time", "raw": raw, "clock_domain": "node"}
                   for raw in ("2026-11-03T08:15:30.000Z", "2026-11-03T08:15:30.100Z")]
        old = [self.proto.build_time(e, clocks) for e in entries]
        self.assertEqual(self.proto.compare(*old), ("before", "same_domain"))
        domain = ti.clock_domain("node", ti.DECLARED, 0, 500, ti.FIXTURE_DECLARED, ti.UNKNOWN)
        new = [ti.source_timestamp(e["raw"], timestamp_kind="event_time", clock_domain_id="node")
               for e in entries]
        self.assertEqual(ti.compare(*new, {"node": domain}), ti.Ordering(ti.UNORDERED, ti.CONTINUITY_UNKNOWN))

    def test_d7_declared_clock_step_blocks_ordering(self):
        self.assertFalse(hasattr(self.proto, "STEP_DECLARED"))
        domain = ti.clock_domain("node", ti.DECLARED, 0, 0, ti.FIXTURE_DECLARED, ti.STEP_DECLARED)
        a, b = (ti.source_timestamp(raw, timestamp_kind="event_time", clock_domain_id="node")
                for raw in ("2026-11-03T08:00:00Z", "2026-11-03T09:00:00Z"))
        self.assertEqual(ti.compare(a, b, {"node": domain}), ti.Ordering(ti.UNORDERED, ti.CLOCK_STEP))

    def test_prototype_file_is_unchanged_by_loading(self):
        before = PROTOTYPE_TIME.read_bytes()
        load_prototype()
        self.assertEqual(PROTOTYPE_TIME.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
