"""Regression: unknown clock continuity must never establish temporal ordering (PR #17 review, P1).

At 93203c8, ``compare`` only disabled the same-domain shortcut for ``continuity: unknown`` and
then ordered the timestamps through reference intervals, so widely separated timestamps were
reported as ``before``/``after``. CA-DEC-003: unknown or unbounded clock uncertainty remains
unordered; a declared offset bound is only meaningful while the clock is known to be continuous.
"""

import unittest

import _support  # noqa: F401
from cloud_autopsy.contracts import timeinterval as ti

CONTINUITY_UNKNOWN = ti.CONTINUITY_UNKNOWN


def stamp(raw, domain):
    return ti.source_timestamp(raw, timestamp_kind="event_time", clock_domain_id=domain)


def domain(domain_id, continuity, status=ti.DECLARED, offset=0, uncertainty=0):
    if status == ti.UNKNOWN:
        return ti.clock_domain(domain_id, ti.UNKNOWN, continuity=continuity)
    return ti.clock_domain(domain_id, status, offset, uncertainty, ti.FIXTURE_DECLARED, continuity)


class UnknownContinuityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.domains = {
            "loose": domain("loose", ti.UNKNOWN, offset=-800, uncertainty=100),
            "loose2": domain("loose2", ti.UNKNOWN, offset=250, uncertainty=0),
            "ref": domain("ref", ti.CONTINUOUS),
            "stepped": domain("stepped", ti.STEP_DECLARED),
            "unknown-status-loose": domain("unknown-status-loose", ti.UNKNOWN, status=ti.UNKNOWN),
            "unknown-status-continuous": domain("unknown-status-continuous", ti.CONTINUOUS, status=ti.UNKNOWN),
        }
        self.early = "2026-11-01T00:00:00Z"
        self.late = "2026-11-03T08:15:30Z"

    def assert_unordered_both_ways(self, a, b, basis):
        self.assertEqual(ti.compare(a, b, self.domains), ti.Ordering(ti.UNORDERED, basis))
        self.assertEqual(ti.compare(b, a, self.domains), ti.Ordering(ti.UNORDERED, basis))

    def test_same_domain_widely_separated_is_unordered(self):
        self.assert_unordered_both_ways(stamp(self.early, "loose"), stamp(self.late, "loose"), CONTINUITY_UNKNOWN)

    def test_cross_domain_unknown_continuity_against_continuous_reference(self):
        self.assert_unordered_both_ways(stamp(self.early, "loose"), stamp(self.late, "ref"), CONTINUITY_UNKNOWN)

    def test_cross_domain_both_unknown_continuity(self):
        self.assert_unordered_both_ways(stamp(self.early, "loose"), stamp(self.late, "loose2"), CONTINUITY_UNKNOWN)

    def test_unknown_continuity_on_unknown_status_clock(self):
        self.assert_unordered_both_ways(stamp(self.early, "unknown-status-loose"),
                                        stamp(self.late, "unknown-status-loose"), CONTINUITY_UNKNOWN)

    def test_reference_interval_is_withheld_without_established_continuity(self):
        self.assertIsNone(ti.reference_interval(stamp(self.late, "loose"), self.domains["loose"]))

    def test_declared_step_still_takes_precedence(self):
        self.assert_unordered_both_ways(stamp(self.early, "stepped"), stamp(self.late, "loose"), ti.CLOCK_STEP)

    def test_established_continuity_is_preserved(self):
        # Same-domain ordering with an unknown absolute offset stays valid when continuity is declared.
        a, b = stamp(self.early, "unknown-status-continuous"), stamp(self.late, "unknown-status-continuous")
        self.assertEqual(ti.compare(a, b, self.domains), ti.Ordering(ti.BEFORE, ti.SAME_DOMAIN))
        self.assertEqual(ti.compare(b, a, self.domains), ti.Ordering(ti.AFTER, ti.SAME_DOMAIN))
        # Bounded reference intervals between continuous declared domains are unchanged.
        domains = {"ref": self.domains["ref"], "a": domain("a", ti.CONTINUOUS, offset=1500, uncertainty=200)}
        x, y = stamp("2026-11-03T08:15:31.699Z", "a"), stamp("2026-11-03T08:15:30.400Z", "ref")
        self.assertEqual(ti.compare(x, y, domains), ti.Ordering(ti.BEFORE, ti.REFERENCE_INTERVAL))


if __name__ == "__main__":
    unittest.main()
