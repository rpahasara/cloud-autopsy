import unittest

from ca_spike.timemodel import TimestampError, build_time, compare, parse_rfc3339_ms

DECLARED = {"status": "declared", "offset_ms": 0, "offset_uncertainty_ms": 0, "precision_ms": 1,
            "provenance": "fixture-declared"}


def t(raw, domain, domains):
    return build_time({"type": "event", "raw": raw, "clock_domain": domain}, domains)


class ParseTests(unittest.TestCase):
    def test_offsets_and_fractions(self):
        base = parse_rfc3339_ms("2026-10-15T08:10:00Z")
        self.assertEqual(parse_rfc3339_ms("2026-10-15T10:10:00.5+02:00"), base + 500)
        self.assertEqual(parse_rfc3339_ms("2026-10-15T08:10:00.123999Z"), base + 123)

    def test_rejects_ambiguous_or_invalid_text(self):
        for raw in ("2026-10-15 08:12:22", "2026-10-15T08:12:22", "2026-02-30T00:00:00Z",
                    "2026-10-15T08:12:60Z", 1760000000, "2026-10-15T08:12:22+25:00"):
            with self.assertRaises(TimestampError, msg=raw):
                parse_rfc3339_ms(raw)


class IntervalTests(unittest.TestCase):
    def test_precision_and_declared_offset_produce_interval(self):
        domains = {"k8s": dict(DECLARED, precision_ms=1000),
                   "node": dict(DECLARED, offset_ms=3000, offset_uncertainty_ms=1000)}
        k = t("2026-10-15T08:10:00Z", "k8s", domains)
        self.assertEqual(k.upper_ms - k.lower_ms, 999)
        n = t("2026-10-15T08:10:05.000Z", "node", domains)
        self.assertEqual(n.lower_ms, parse_rfc3339_ms("2026-10-15T08:10:01Z"))
        self.assertEqual(n.upper_ms, parse_rfc3339_ms("2026-10-15T08:10:03Z"))
        self.assertEqual(n.raw, "2026-10-15T08:10:05.000Z")  # original text retained
        self.assertEqual(compare(k, n), ("before", "reference_interval"))

    def test_precedence_is_strict_and_overlap_is_unordered(self):
        domains = {"a": dict(DECLARED, precision_ms=1000), "b": DECLARED}
        a = t("2026-10-15T08:10:00Z", "a", domains)  # [..00.000, ..00.999]
        self.assertEqual(compare(a, t("2026-10-15T08:10:00.999Z", "b", domains))[0], "unordered")
        self.assertEqual(compare(a, t("2026-10-15T08:10:01.000Z", "b", domains))[0], "before")

    def test_unknown_clock_is_unordered_across_domains_but_ordered_within(self):
        domains = {"x": {"status": "unknown", "precision_ms": 1}, "ref": DECLARED}
        x1 = t("2026-10-15T08:00:00Z", "x", domains)
        x2 = t("2026-10-15T09:00:00Z", "x", domains)
        r = t("2026-10-16T00:00:00Z", "ref", domains)
        self.assertIsNone(x1.lower_ms)
        self.assertEqual(compare(x1, r), ("unordered", "unbounded_clock"))
        self.assertEqual(compare(x1, x2), ("before", "same_domain"))

    def test_identical_tick_is_a_tie_and_parse_error_is_unordered(self):
        domains = {"k8s": dict(DECLARED, precision_ms=1000)}
        a = t("2026-10-15T08:11:00Z", "k8s", domains)
        self.assertEqual(compare(a, t("2026-10-15T08:11:00Z", "k8s", domains))[0], "unordered")
        bad = t("2026-10-15 08:11:00", "k8s", domains)
        self.assertEqual(bad.parse_status, "error")
        self.assertIsNone(bad.parsed_utc)
        self.assertEqual(compare(a, bad), ("unordered", "unparseable_timestamp"))


if __name__ == "__main__":
    unittest.main()
