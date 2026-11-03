"""Fixed time vectors for ca-time-interval/0.1-provisional (expected values computed independently)."""

import json
import unittest

import _support
from cloud_autopsy.contracts import errors, timeinterval as ti
from cloud_autopsy.contracts.errors import TimeError

VECTORS = _support.PACKAGE / "contracts" / "vectors" / "ca-time-interval-0.1-provisional.json"
DERIVED = ("epoch_ms", "zone_offset_minutes", "local_offset_unknown", "text_precision_ns",
           "effective_precision_ns", "local_lower_ms", "local_upper_ms")


def load():
    return json.loads(VECTORS.read_bytes().decode("utf-8"))


def domains_from(doc):
    return {key: ti.clock_domain(key, **spec) for key, spec in doc["domains"].items()}


def stamp(domain, raw):
    return ti.source_timestamp(raw, timestamp_kind="event_time", clock_domain_id=domain)


class TimeVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load()
        cls.domains = domains_from(cls.doc)

    def test_vector_file_targets_this_contract(self):
        self.assertEqual(self.doc["contract"], ti.TIME_VERSION)
        ids = [v["id"] for key in ("parse_valid", "parse_invalid", "compare") for v in self.doc[key]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_valid_timestamps(self):
        for v in self.doc["parse_valid"]:
            with self.subTest(v["id"]):
                ts = ti.source_timestamp(v["raw"], timestamp_kind="event_time", clock_domain_id="ref",
                                         declared_precision_ns=v.get("declared_precision_ns"))
                self.assertEqual(ts.parse_status, ti.PARSED)
                self.assertIsNone(ts.parse_error)
                self.assertEqual(ts.raw, v["raw"])
                for name in DERIVED:
                    self.assertEqual(getattr(ts, name), v[name], name)
                    self.assertIs(type(getattr(ts, name)), type(v[name]), name)
                self.assertLessEqual(ts.local_lower_ms, ts.local_upper_ms)

    def test_invalid_timestamps_raise_stable_codes_and_are_retained(self):
        for v in self.doc["parse_invalid"]:
            with self.subTest(v["id"]):
                self.assertIn(v["error"], errors.TIME_CODES)
                with self.assertRaises(TimeError) as ctx:
                    ti.parse_rfc3339(v["raw"])
                self.assertEqual(ctx.exception.code, v["error"])
                ts = stamp("ref", v["raw"])
                expected_status = ti.LEAP_SECOND if v["error"] == errors.LEAP_SECOND_UNSUPPORTED else ti.INVALID
                self.assertEqual((ts.parse_status, ts.parse_error, ts.raw), (expected_status, v["error"], v["raw"]))
                self.assertEqual({getattr(ts, n) for n in DERIVED}, {None})

    def test_comparisons_and_their_inverses(self):
        inverse = {ti.BEFORE: ti.AFTER, ti.AFTER: ti.BEFORE, ti.UNORDERED: ti.UNORDERED}
        for v in self.doc["compare"]:
            with self.subTest(v["id"]):
                a, b = stamp(*v["a"]), stamp(*v["b"])
                self.assertEqual(ti.compare(a, b, self.domains), ti.Ordering(v["order"], v["basis"]))
                self.assertEqual(ti.compare(b, a, self.domains), ti.Ordering(inverse[v["order"]], v["basis"]))


if __name__ == "__main__":
    unittest.main()
