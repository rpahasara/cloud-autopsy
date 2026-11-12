"""CA-P2-004f F5.1: the unchanged time contract represents an observed bracket conservatively.

A watch event's commit instant ``c`` is known only to satisfy ``L < c < U`` on the collector clock:
``L`` is the send time of the last consistent-read probe (or list request) whose resourceVersion is
below the event's, and ``U`` is the event's receipt time. The plan encodes this as an existing
``ca-time-interval/0.2-provisional`` source timestamp: ``raw`` = ``L`` in RFC 3339 with nine fraction
digits (UTC), ``declared_precision_ns`` = ``U - L``. The contract's established meaning, "the instant
lies in ``[raw, raw + effective precision)``", then contains ``(L, U)``. Its millisecond interval is
widened outward, never inward.

These tests use the contract exactly as it is: no new field, kind or version. They pin:
- exact lower and upper bounds, including fractional milliseconds and exact millisecond edges;
- containment and tightness over many deterministic brackets;
- ordering of overlapping, touching and separated brackets within one clock domain;
- fail-closed ordering after a clock discontinuity, unknown continuity or a different domain;
- the one-day precision limit (a wider bracket is refused, so it can never be recorded).
"""

import random
import unittest

import _support  # noqa: F401  (adds src to the path)
from cloud_autopsy.contracts import errors as E
from cloud_autopsy.contracts import timeinterval as ti

NS_PER_MS = 1_000_000
DOMAIN = "ca-collector-test"
BASE_NS = 1_793_664_000_000_000_000  # 2026-11-03T00:00:00Z, an arbitrary fixed instant


def rfc3339_ns(epoch_ns):
    """UTC RFC 3339 text with nine fraction digits for an epoch nanosecond value (test helper)."""
    seconds, frac = divmod(epoch_ns, 1_000_000_000)
    days, rem = divmod(seconds, 86_400)
    hour, rem = divmod(rem, 3600)
    minute, second = divmod(rem, 60)
    # civil-from-days (proleptic Gregorian), Howard Hinnant's algorithm
    z = days + 719_468
    era = z // 146_097
    doe = z - era * 146_097
    yoe = (doe - doe // 1460 + doe // 36_524 - doe // 146_096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    year += month <= 2
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{frac:09d}Z"


def observed(lower_ns, upper_ns, domain=DOMAIN):
    """Encode the bracket (lower, upper) as the plan specifies, with the unchanged contract."""
    return ti.source_timestamp(rfc3339_ns(lower_ns), timestamp_kind="observed", clock_domain_id=domain,
                               declared_precision_ns=upper_ns - lower_ns)


def collector_domain(continuity=ti.CONTINUOUS, domain=DOMAIN):
    return ti.clock_domain(domain, ti.UNKNOWN, continuity=continuity)


class ObservedBracketBounds(unittest.TestCase):
    def test_helper_round_trips_through_the_contract_parser(self):
        for ns in (BASE_NS, BASE_NS + 1, BASE_NS + 999_999_999, 951_782_400_123_456_789):  # incl. 2000-02-29
            self.assertEqual(ti.parse_rfc3339(rfc3339_ns(ns)).epoch_ns, ns)

    def test_fractional_millisecond_bounds_widen_outward(self):
        lower, upper = BASE_NS + 1000 * NS_PER_MS + 400_000, BASE_NS + 1002 * NS_PER_MS + 600_000
        ts = observed(lower, upper)
        self.assertEqual(ts.parse_status, ti.PARSED)
        self.assertEqual(ts.effective_precision_ns, upper - lower)  # nine digits: text precision 1 ns
        self.assertEqual(ts.local_lower_ms, (BASE_NS // NS_PER_MS) + 1000)
        self.assertEqual(ts.local_upper_ms, (BASE_NS // NS_PER_MS) + 1002)  # [1000 ms, 1003 ms) contains it

    def test_exact_millisecond_edges_are_not_widened(self):
        lower, upper = BASE_NS + 1000 * NS_PER_MS, BASE_NS + 1003 * NS_PER_MS
        ts = observed(lower, upper)
        self.assertEqual((ts.local_lower_ms, ts.local_upper_ms),
                         (BASE_NS // NS_PER_MS + 1000, BASE_NS // NS_PER_MS + 1002))

    def test_smallest_bracket_is_one_nanosecond_and_zero_width_is_refused(self):
        ts = observed(BASE_NS + 5, BASE_NS + 6)
        self.assertEqual((ts.local_lower_ms, ts.local_upper_ms), (BASE_NS // NS_PER_MS, BASE_NS // NS_PER_MS))
        with self.assertRaises(ti.TimeError) as caught:
            observed(BASE_NS + 5, BASE_NS + 5)
        self.assertEqual(caught.exception.code, E.PRECISION_INVALID)

    def test_brackets_wider_than_one_day_are_refused(self):
        observed(BASE_NS, BASE_NS + ti.MAX_PRECISION_NS)  # exactly one day is representable
        with self.assertRaises(ti.TimeError) as caught:
            observed(BASE_NS, BASE_NS + ti.MAX_PRECISION_NS + 1)
        self.assertEqual(caught.exception.code, E.PRECISION_INVALID)

    def test_containment_and_tightness_over_deterministic_brackets(self):
        rng = random.Random(4_004_006)
        for _ in range(5000):
            lower = BASE_NS + rng.randrange(0, 10**12)
            upper = lower + rng.choice((1, rng.randrange(1, NS_PER_MS), rng.randrange(1, 20_000 * NS_PER_MS)))
            ts = observed(lower, upper)
            lo_ns, hi_ns = ts.local_lower_ms * NS_PER_MS, (ts.local_upper_ms + 1) * NS_PER_MS
            self.assertLessEqual(lo_ns, lower)          # contains every instant in [lower, upper)
            self.assertGreaterEqual(hi_ns, upper)
            self.assertGreater(lo_ns, lower - NS_PER_MS)  # widened by less than 1 ms on each side
            self.assertLess(hi_ns, upper + NS_PER_MS)

    def test_record_round_trip_is_exact(self):
        ts = observed(BASE_NS + 123_456_789, BASE_NS + 15_000_000_001)
        self.assertEqual(ti.SourceTimestamp.from_record(ts.to_record()), ts)


class ObservedBracketOrdering(unittest.TestCase):
    domains = {DOMAIN: collector_domain()}

    def order(self, a, b, domains=None):
        return ti.compare(a, b, domains or self.domains)

    def test_separated_brackets_are_ordered_without_any_offset(self):
        a = observed(BASE_NS, BASE_NS + 5 * NS_PER_MS)
        b = observed(BASE_NS + 10 * NS_PER_MS, BASE_NS + 12 * NS_PER_MS)
        self.assertEqual(self.order(a, b), ti.Ordering(ti.BEFORE, ti.SAME_DOMAIN))
        self.assertEqual(self.order(b, a), ti.Ordering(ti.AFTER, ti.SAME_DOMAIN))

    def test_touching_on_a_millisecond_edge_is_ordered(self):
        a = observed(BASE_NS, BASE_NS + 5 * NS_PER_MS)            # [0, 5) ms
        b = observed(BASE_NS + 5 * NS_PER_MS, BASE_NS + 9 * NS_PER_MS)
        self.assertEqual(self.order(a, b).order, ti.BEFORE)

    def test_touching_inside_a_millisecond_stays_unordered(self):
        a = observed(BASE_NS, BASE_NS + 5 * NS_PER_MS + 300)       # ends inside ms 5
        b = observed(BASE_NS + 5 * NS_PER_MS + 300, BASE_NS + 9 * NS_PER_MS)
        self.assertEqual(self.order(a, b), ti.Ordering(ti.UNORDERED, ti.SAME_DOMAIN_OVERLAP))

    def test_overlapping_brackets_are_unordered(self):
        a = observed(BASE_NS, BASE_NS + 8 * NS_PER_MS)
        b = observed(BASE_NS + 4 * NS_PER_MS, BASE_NS + 12 * NS_PER_MS)
        self.assertEqual(self.order(a, b), ti.Ordering(ti.UNORDERED, ti.SAME_DOMAIN_OVERLAP))

    def test_a_clock_step_fails_closed(self):
        a = observed(BASE_NS, BASE_NS + NS_PER_MS)
        b = observed(BASE_NS + 60_000 * NS_PER_MS, BASE_NS + 60_001 * NS_PER_MS)
        stepped = {DOMAIN: collector_domain(ti.STEP_DECLARED)}
        self.assertEqual(self.order(a, b, stepped), ti.Ordering(ti.UNORDERED, ti.CLOCK_STEP))

    def test_unknown_continuity_fails_closed(self):
        a = observed(BASE_NS, BASE_NS + NS_PER_MS)
        b = observed(BASE_NS + 60_000 * NS_PER_MS, BASE_NS + 60_001 * NS_PER_MS)
        unknown = {DOMAIN: collector_domain(ti.UNKNOWN)}
        self.assertEqual(self.order(a, b, unknown), ti.Ordering(ti.UNORDERED, ti.CONTINUITY_UNKNOWN))

    def test_api_server_times_are_never_ordered_against_collector_times(self):
        collector = observed(BASE_NS, BASE_NS + NS_PER_MS)
        server = ti.source_timestamp(rfc3339_ns(BASE_NS + 3_600_000 * NS_PER_MS), timestamp_kind="event",
                                     clock_domain_id="k8s-api-server")
        domains = {DOMAIN: collector_domain(),
                   "k8s-api-server": ti.clock_domain("k8s-api-server", ti.UNKNOWN, continuity=ti.CONTINUOUS)}
        self.assertEqual(self.order(collector, server, domains), ti.Ordering(ti.UNORDERED, ti.UNKNOWN_CLOCK))


if __name__ == "__main__":
    unittest.main()
