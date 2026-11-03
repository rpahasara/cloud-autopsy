"""Unit tests for timestamp records, clock domains, ordering rules and error hygiene."""

import itertools
import random
import unittest

import _support  # noqa: F401
from cloud_autopsy.contracts import canonical, errors, timeinterval as ti
from cloud_autopsy.contracts.errors import ContractError, RecordError, TimeError, VersionError

T = "2026-11-03T08:15:30"


def stamp(raw, domain="ref", **kw):
    return ti.source_timestamp(raw, timestamp_kind="event_time", clock_domain_id=domain, **kw)


def declared(domain_id, offset=0, uncertainty=0, continuity=ti.CONTINUOUS):
    return ti.clock_domain(domain_id, ti.DECLARED, offset, uncertainty, ti.FIXTURE_DECLARED, continuity)


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ContractError as exc:
        return exc.code
    return None


class ParseTests(unittest.TestCase):
    def test_non_string_input(self):
        for value in (None, 1793693730000, b"2026-11-03T08:15:30Z", 1.5):
            with self.subTest(value=value):
                self.assertEqual(code_of(ti.parse_rfc3339, value), errors.TIMESTAMP_NOT_STRING)

    def test_every_fraction_length_sets_text_precision(self):
        for digits in range(1, 10):
            with self.subTest(digits=digits):
                parsed = ti.parse_rfc3339(f"{T}.{'0' * digits}Z")
                self.assertEqual(parsed.text_precision_ns, 10 ** (9 - digits))

    def test_offsets_shift_to_the_same_instant(self):
        instants = {ti.parse_rfc3339(text).epoch_ns for text in (
            "2026-11-03T08:15:30Z", "2026-11-03T08:15:30+00:00", "2026-11-03T08:15:30-00:00",
            "2026-11-03T09:45:30+01:30", "2026-11-02T08:16:30-23:59", "2026-11-04T08:14:30+23:59")}
        self.assertEqual(len(instants), 1)

    def test_offsets_cross_year_boundaries(self):
        a = ti.parse_rfc3339("2026-01-01T00:30:00+01:00")
        b = ti.parse_rfc3339("2025-12-31T23:30:00Z")
        self.assertEqual(a.epoch_ns, b.epoch_ns)

    def test_calendar_matches_independent_ordinal_count(self):
        # Days between consecutive month starts must equal the month length, across 0000-9999.
        rng = random.Random(7)
        years = [0, 1, 4, 100, 400, 1582, 1900, 1969, 1970, 2000, 2024, 2100, 9999] + \
            [rng.randint(0, 9999) for _ in range(40)]
        for year in years:
            for month in range(1, 13):
                start = ti.parse_rfc3339(f"{year:04d}-{month:02d}-01T00:00:00Z").epoch_ns
                last = ti.parse_rfc3339(
                    f"{year:04d}-{month:02d}-{ti._days_in_month(year, month):02d}T00:00:00Z").epoch_ns
                with self.subTest(year=year, month=month):
                    self.assertEqual((last - start) // (86_400 * ti.NS_PER_S),
                                     ti._days_in_month(year, month) - 1)

    def test_extreme_records_stay_canonical(self):
        for raw in ("0000-01-01T00:00:00+23:59", "9999-12-31T23:59:59.999999999-23:59"):
            with self.subTest(raw=raw):
                record = stamp(raw, declared_precision_ns=ti.MAX_PRECISION_NS).to_record()
                self.assertEqual(canonical.loads(canonical.canonical_bytes(record)), record)

    def test_lone_surrogate_raw_cannot_be_retained(self):
        self.assertEqual(code_of(stamp, T + "\ud800Z"), errors.TIMESTAMP_MALFORMED)

    def test_raw_retention_ceiling(self):
        retained = stamp("x" * ti.MAX_RAW_CHARS)
        self.assertEqual((retained.parse_status, retained.parse_error),
                         (ti.INVALID, errors.TIMESTAMP_TOO_LONG))
        self.assertEqual(code_of(stamp, "x" * (ti.MAX_RAW_CHARS + 1)), errors.TIMESTAMP_TOO_LONG)


class PrecisionTests(unittest.TestCase):
    def test_declared_precision_bounds(self):
        for bad in (0, -1, ti.MAX_PRECISION_NS + 1, True, 1.0, "1000"):
            with self.subTest(bad=bad):
                self.assertEqual(code_of(stamp, T + "Z", declared_precision_ns=bad), errors.PRECISION_INVALID)

    def test_interval_always_contains_text_instant_and_is_widened_outward(self):
        rng = random.Random(11)
        for _ in range(500):
            digits = rng.randint(0, 9)
            fraction = "".join(rng.choice("0123456789") for _ in range(digits))
            raw = f"{T}.{fraction}Z" if digits else f"{T}Z"
            precision = rng.choice([None, 1, 7, 300_000, 1_000_000, 1_500_000, 999_999_999, 10 ** 9 + 3])
            ts = stamp(raw, declared_precision_ns=precision)
            parsed = ti.parse_rfc3339(raw)
            with self.subTest(raw=raw, precision=precision):
                self.assertLessEqual(ts.local_lower_ms * ti.NS_PER_MS, parsed.epoch_ns)
                end = parsed.epoch_ns + ts.effective_precision_ns
                self.assertGreaterEqual((ts.local_upper_ms + 1) * ti.NS_PER_MS, end)
                self.assertLess(ts.local_upper_ms * ti.NS_PER_MS, end)  # never wider than needed


class ClockDomainTests(unittest.TestCase):
    def test_declared_domain_validation(self):
        cases = [
            (dict(status="measured"), errors.RECORD_FIELD_INVALID),
            (dict(continuity="assumed"), errors.RECORD_FIELD_INVALID),
            (dict(offset_provenance="measured"), errors.RECORD_FIELD_INVALID),
            (dict(offset_provenance=None), errors.RECORD_FIELD_INVALID),
            (dict(offset_ms=None), errors.CLOCK_OFFSET_OUT_OF_RANGE),
            (dict(offset_ms=1.5), errors.CLOCK_OFFSET_OUT_OF_RANGE),
            (dict(offset_ms=True), errors.CLOCK_OFFSET_OUT_OF_RANGE),
            (dict(offset_ms=ti.MAX_CLOCK_OFFSET_MS + 1), errors.CLOCK_OFFSET_OUT_OF_RANGE),
            (dict(offset_uncertainty_ms=-1), errors.CLOCK_OFFSET_OUT_OF_RANGE),
            (dict(offset_uncertainty_ms=ti.MAX_OFFSET_UNCERTAINTY_MS + 1), errors.CLOCK_OFFSET_OUT_OF_RANGE),
            (dict(clock_domain_id="Node A"), errors.RECORD_FIELD_INVALID),
        ]
        base = dict(clock_domain_id="node-a", status=ti.DECLARED, offset_ms=0, offset_uncertainty_ms=0,
                    offset_provenance=ti.FIXTURE_DECLARED, continuity=ti.CONTINUOUS)
        for change, code in cases:
            with self.subTest(change=change):
                self.assertEqual(code_of(ti.clock_domain, **{**base, **change}), code)
        edge = ti.clock_domain(**{**base, "offset_ms": -ti.MAX_CLOCK_OFFSET_MS,
                                  "offset_uncertainty_ms": ti.MAX_OFFSET_UNCERTAINTY_MS})
        self.assertEqual((edge.offset_ms, edge.offset_uncertainty_ms),
                         (-ti.MAX_CLOCK_OFFSET_MS, ti.MAX_OFFSET_UNCERTAINTY_MS))

    def test_unknown_clock_cannot_declare_offset(self):
        for change in (dict(offset_ms=0), dict(offset_uncertainty_ms=0), dict(offset_provenance=ti.FIXTURE_DECLARED)):
            with self.subTest(change=change):
                self.assertEqual(code_of(ti.clock_domain, "c", ti.UNKNOWN, **change), errors.RECORD_FIELD_INVALID)

    def test_domain_record_round_trip_and_strict_decode(self):
        domain = declared("node-a", offset=-1500, uncertainty=None, continuity=ti.STEP_DECLARED)
        record = canonical.loads(canonical.canonical_bytes(domain.to_record()))
        self.assertEqual(ti.ClockDomain.from_record(record), domain)
        self.assertEqual(code_of(ti.ClockDomain.from_record, {**record, "extra": 1}), errors.RECORD_FIELD_UNKNOWN)
        missing = dict(record)
        del missing["continuity"]
        self.assertEqual(code_of(ti.ClockDomain.from_record, missing), errors.RECORD_FIELD_MISSING)
        self.assertEqual(code_of(ti.ClockDomain.from_record, [record]), errors.RECORD_NOT_OBJECT)
        with self.assertRaises(VersionError):
            ti.ClockDomain.from_record({**record, "contract_version": "ca-time-interval/0.2-provisional"})


class TimestampRecordTests(unittest.TestCase):
    def test_round_trip_through_canonical_bytes(self):
        for raw in (T + ".123456789+05:30", "2016-12-31T23:59:60Z", "not a time", T + "Z"):
            with self.subTest(raw=raw):
                ts = stamp(raw, declared_precision_ns=5_000_000)
                decoded = canonical.loads(canonical.canonical_bytes(ts.to_record()))
                self.assertEqual(ti.SourceTimestamp.from_record(decoded), ts)

    def test_forged_derived_fields_are_rejected(self):
        record = stamp(T + ".500Z").to_record()
        forgeries = [
            {"local_lower_ms": record["local_lower_ms"] - 1},
            {"local_upper_ms": record["local_upper_ms"] + 5000},
            {"epoch_ms": 0},
            {"parse_status": ti.INVALID},
            {"effective_precision_ns": 1},
            {"local_offset_unknown": 0},  # same value, wrong type
            {"zone_offset_minutes": False},
        ]
        for change in forgeries:
            with self.subTest(change=change):
                self.assertEqual(code_of(ti.SourceTimestamp.from_record, {**record, **change}),
                                 errors.RECORD_INCONSISTENT)

    def test_record_has_no_ingestion_or_resource_version_fields(self):
        names = set(stamp(T + "Z").to_record())
        for forbidden in ("ingested_at", "ingestion_order", "resource_version", "resourceVersion",
                          "evidence_id", "sequence"):
            self.assertNotIn(forbidden, names)


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.domains = {"ref": declared("ref"), "a": declared("a", 250, 50), "b": declared("b", -400, 75),
                        "loose": declared("loose", 0, 0, ti.UNKNOWN)}

    def test_ordering_is_antisymmetric_and_never_uses_argument_or_id_order(self):
        rng = random.Random(3)
        stamps = []
        for _ in range(60):
            domain = rng.choice(sorted(self.domains))
            millis = rng.randint(0, 3000)
            raw = f"2026-11-03T08:15:{30 + millis // 1000:02d}.{millis % 1000:03d}Z"
            stamps.append(stamp(raw, domain, declared_precision_ns=rng.choice([None, 2_000_000])))
        for x, y in itertools.product(stamps, repeat=2):
            forward, backward = ti.compare(x, y, self.domains), ti.compare(y, x, self.domains)
            self.assertEqual(forward.basis, backward.basis)
            self.assertEqual({forward.order, backward.order} - {ti.UNORDERED},
                             set() if forward.order == ti.UNORDERED else {ti.BEFORE, ti.AFTER})

    def test_before_is_transitive(self):
        rng = random.Random(5)
        stamps = [stamp(f"2026-11-03T08:15:{rng.randint(0, 59):02d}.{rng.randint(0, 999):03d}Z",
                        rng.choice(sorted(self.domains))) for _ in range(40)]
        for x, y, z in itertools.product(stamps, repeat=3):
            if ti.compare(x, y, self.domains).order == ti.BEFORE == ti.compare(y, z, self.domains).order:
                self.assertEqual(ti.compare(x, z, self.domains).order, ti.BEFORE)

    def test_identical_intervals_in_different_evidence_stay_unordered(self):
        first, second = stamp(T + ".100Z"), stamp(T + ".100Z")
        for x, y in ((first, second), (second, first)):
            self.assertEqual(ti.compare(x, y, self.domains), ti.Ordering(ti.UNORDERED, ti.SAME_DOMAIN_OVERLAP))

    def test_domain_mapping_must_match_record_ids(self):
        bad = {"ref": declared("other")}
        self.assertEqual(code_of(ti.compare, stamp(T + "Z"), stamp(T + "Z"), bad), errors.RECORD_INCONSISTENT)
        self.assertEqual(code_of(ti.compare, stamp(T + "Z"), {"raw": T}, self.domains),
                         errors.RECORD_FIELD_INVALID)

    def test_reference_interval_values(self):
        ts = stamp(T + ".500Z", "a")
        lower = ts.local_lower_ms - 250 - 50
        self.assertEqual(ti.reference_interval(ts, self.domains["a"]), (lower, lower + 100))
        self.assertIsNone(ti.reference_interval(ts, self.domains["ref"]))  # wrong domain
        self.assertIsNone(ti.reference_interval(stamp("bad", "a"), self.domains["a"]))

    def test_ordering_record_is_versioned(self):
        record = ti.compare(stamp(T + "Z"), stamp(T + ".5Z"), self.domains).to_record()
        self.assertEqual(record["contract_version"], ti.TIME_VERSION)
        canonical.canonical_bytes(record)


class ErrorHygieneTests(unittest.TestCase):
    CANARY = "CANARY-SECRET-5150"

    def test_errors_never_contain_source_text(self):
        attempts = [
            lambda: ti.parse_rfc3339(self.CANARY),
            lambda: ti.parse_rfc3339(f"{T}.{self.CANARY}Z"),
            lambda: ti.parse_rfc3339(self.CANARY * 10),
            lambda: stamp(self.CANARY * 40),
            lambda: stamp(self.CANARY + "\ud800"),
            lambda: ti.source_timestamp(T + "Z", timestamp_kind=self.CANARY, clock_domain_id="ref"),
            lambda: ti.clock_domain(self.CANARY, ti.UNKNOWN),
            lambda: ti.SourceTimestamp.from_record({**stamp(T + "Z").to_record(), self.CANARY: 1}),
            lambda: ti.SourceTimestamp.from_record({**stamp(T + "Z").to_record(), "raw": self.CANARY}),
            lambda: ti.ClockDomain.from_record({"contract_version": self.CANARY}),
        ]
        for i, attempt in enumerate(attempts):
            with self.subTest(i=i):
                try:
                    attempt()
                except ContractError as exc:
                    self.assertNotIn(self.CANARY, str(exc))
                    self.assertNotIn("CANARY", repr(exc.args))
                else:
                    self.fail("expected a contract error")

    def test_retained_invalid_timestamp_keeps_raw_only_in_raw_field(self):
        record = stamp(self.CANARY).to_record()
        self.assertEqual([k for k, v in record.items() if v == self.CANARY], ["raw"])
        self.assertEqual(record["parse_error"], errors.TIMESTAMP_MALFORMED)

    def test_time_error_class_and_codes(self):
        self.assertTrue(issubclass(TimeError, ContractError) and issubclass(RecordError, ContractError))
        self.assertEqual(errors.TIME_CODES, {
            "timestamp_not_string", "timestamp_too_long", "timestamp_malformed", "fraction_too_long",
            "invalid_calendar_date", "invalid_time_of_day", "invalid_utc_offset", "leap_second_unsupported",
            "precision_invalid", "clock_offset_out_of_range"})
        self.assertEqual(errors.RECORD_CODES, {
            "record_not_object", "record_field_missing", "record_field_unknown", "record_field_invalid",
            "record_inconsistent"})


if __name__ == "__main__":
    unittest.main()
