"""Timestamp provenance and clock-interval contracts ``ca-time-interval/0.2-provisional`` (CA-P2-002b).

Every rule here is provisional until independent architecture review (CA-DEC-003, D8).

Timestamps. The raw source text is always retained. A timestamp parses only as strict
RFC 3339 ``YYYY-MM-DDTHH:MM:SS[.fraction](Z|+HH:MM|-HH:MM)``: ASCII digits, uppercase ``T``
and ``Z``, 1-9 fraction digits, years 0000-9999 in the proleptic Gregorian calendar, offset
hours 00-23 and minutes 00-59. ``-00:00`` (UTC instant, unknown local offset) is accepted
and flagged. A leap second (``:60``) is kept as raw text with no parsed instant: it is
never smeared or mapped to a neighbouring second.

Precision. The text itself implies a precision (1 s without a fraction, 10^-n s with n
fraction digits). A source may declare a coarser precision; the effective precision is the
coarser of the two. The source is assumed to truncate, so the instant lies in
``[t, t + precision)``. Intervals are inclusive integer epoch milliseconds ``[lower, upper]``
meaning ``[lower ms, upper + 1 ms)``; sub-millisecond bounds are widened outward, never
rounded inward.

Clock domains. Offset is ``source clock - reference clock``. A declared correction is
subtracted from the source interval and its uncertainty widens both bounds; the original
timestamp is unchanged. Only fixture-declared synthetic offsets are supported; measured
offsets are out of scope. Continuity is ``declared_continuous``, ``step_declared`` or
``unknown``.

Ordering. A precedes B only when A's upper bound is strictly below B's lower bound;
overlap is unordered. Both clock domains must declare continuity before any ordering is
established: a declared offset bound says nothing about a clock that may have stepped, so
``step_declared`` and ``unknown`` continuity both fail closed (``clock_step`` and
``continuity_unknown``), in the same domain and across domains. With continuity declared,
same-domain intervals are compared without offset (valid even when the absolute offset is
unknown), and cross-domain intervals through bounded declared offsets. An unparsed
timestamp, unknown or missing clock, or unbounded uncertainty also yields ``unordered``.
Basis precedence: unparsed_timestamp, unknown_clock (missing domain), clock_step,
continuity_unknown, same-domain, unknown_clock (status), unbounded_uncertainty, reference.
There is deliberately no tie-breaker: ingestion order, Kubernetes resourceVersion and
stable-ID sorting are not inputs and can never establish chronology.

Version history: 0.1-provisional (PR #17 at 93203c8) ordered timestamps whose domains had
unknown continuity through reference intervals. 0.2-provisional fails closed instead; the
exact-match version rule rejects 0.1 records rather than reinterpreting them.

All record values are integers, strings, booleans or null within the canonical profile.
Error messages carry fixed text and field names only, never source text.
"""

import re
from dataclasses import dataclass, fields

from . import errors as E
from .errors import RecordError, TimeError
from .versioning import check_envelope

TIME_VERSION = "ca-time-interval/0.2-provisional"

# PROVISIONAL ceilings (unreviewed).
MAX_TIMESTAMP_CHARS = 64      # longest text that is parsed
MAX_RAW_CHARS = 256           # longest raw text that is retained in a record
MAX_PRECISION_NS = 86_400_000_000_000          # one day
MAX_CLOCK_OFFSET_MS = 31_622_400_000           # 366 days
MAX_OFFSET_UNCERTAINTY_MS = 31_622_400_000     # 366 days

NS_PER_MS = 1_000_000
NS_PER_S = 1_000_000_000

PARSED = "parsed"
INVALID = "invalid"
LEAP_SECOND = "leap_second_unsupported"
PARSE_STATUSES = (PARSED, INVALID, LEAP_SECOND)

DECLARED = "declared"
UNKNOWN = "unknown"
CLOCK_STATUSES = (DECLARED, UNKNOWN)
FIXTURE_DECLARED = "fixture_declared"
CONTINUOUS = "declared_continuous"
STEP_DECLARED = "step_declared"
CONTINUITY_VALUES = (CONTINUOUS, STEP_DECLARED, UNKNOWN)

BEFORE, AFTER, UNORDERED = "before", "after", "unordered"
SAME_DOMAIN = "same_domain"
SAME_DOMAIN_OVERLAP = "same_domain_overlap"
REFERENCE_INTERVAL = "reference_interval"
REFERENCE_OVERLAP = "reference_overlap"
UNPARSED_TIMESTAMP = "unparsed_timestamp"
UNKNOWN_CLOCK = "unknown_clock"
UNBOUNDED_UNCERTAINTY = "unbounded_uncertainty"
CLOCK_STEP = "clock_step"
CONTINUITY_UNKNOWN = "continuity_unknown"
ORDERING_BASES = (SAME_DOMAIN, SAME_DOMAIN_OVERLAP, REFERENCE_INTERVAL, REFERENCE_OVERLAP,
                  UNPARSED_TIMESTAMP, UNKNOWN_CLOCK, UNBOUNDED_UNCERTAINTY, CLOCK_STEP, CONTINUITY_UNKNOWN)

_RFC3339 = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?"
    r"(Z|[+-][0-9]{2}:[0-9]{2})", re.ASCII)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}", re.ASCII)
_SURROGATE = re.compile("[\ud800-\udfff]")


@dataclass(frozen=True)
class ParsedTimestamp:
    epoch_ns: int
    text_precision_ns: int
    zone_offset_minutes: int
    local_offset_unknown: bool


def _days_in_month(year, month):
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _days_from_civil(year, month, day):
    """Days since 1970-01-01 in the proleptic Gregorian calendar (valid for year 0)."""
    year -= month <= 2
    era = year // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def parse_rfc3339(raw):
    """Parse strict RFC 3339 text to nanoseconds since the epoch; raise ``TimeError``."""
    if not isinstance(raw, str):
        raise TimeError(E.TIMESTAMP_NOT_STRING, "timestamp must be a string")
    if len(raw) > MAX_TIMESTAMP_CHARS:
        raise TimeError(E.TIMESTAMP_TOO_LONG, f"timestamp exceeds {MAX_TIMESTAMP_CHARS} characters")
    match = _RFC3339.fullmatch(raw)
    if not match:
        raise TimeError(E.TIMESTAMP_MALFORMED, "not an RFC 3339 date-time with explicit offset")
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction, zone = match.group(7), match.group(8)
    if fraction is not None and len(fraction) > 9:
        raise TimeError(E.FRACTION_TOO_LONG, "more than 9 fraction digits")
    if zone == "Z":
        offset_minutes = 0
    else:
        zone_hours, zone_minutes = int(zone[1:3]), int(zone[4:6])
        if zone_hours > 23 or zone_minutes > 59:
            raise TimeError(E.INVALID_UTC_OFFSET, "offset hours must be 00-23 and minutes 00-59")
        offset_minutes = (1 if zone[0] == "+" else -1) * (zone_hours * 60 + zone_minutes)
    if not 1 <= month <= 12 or not 1 <= day <= _days_in_month(year, month):
        raise TimeError(E.INVALID_CALENDAR_DATE, "month or day out of range for the calendar")
    if hour > 23 or minute > 59 or second > 60:
        raise TimeError(E.INVALID_TIME_OF_DAY, "hour, minute or second out of range")
    if second == 60:
        raise TimeError(E.LEAP_SECOND_UNSUPPORTED, "leap seconds have no supported instant")
    seconds = (_days_from_civil(year, month, day) * 86_400 + hour * 3_600 + minute * 60 + second
               - offset_minutes * 60)
    fraction_ns = int(fraction.ljust(9, "0")) if fraction else 0
    return ParsedTimestamp(
        epoch_ns=seconds * NS_PER_S + fraction_ns,
        text_precision_ns=10 ** (9 - len(fraction)) if fraction else NS_PER_S,
        zone_offset_minutes=offset_minutes,
        local_offset_unknown=zone == "-00:00")


def _identifier(value, name):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise RecordError(E.RECORD_FIELD_INVALID, f"{name} must be a lowercase identifier")
    return value


def _bounded_int(value, name, low, high, code=E.RECORD_FIELD_INVALID, error=RecordError):
    if type(value) is not int or not low <= value <= high:
        raise error(code, f"{name} must be an integer in {low}..{high}")
    return value


def _strict_fields(record, cls):
    """Check object shape and version; return the field dict without contract_version."""
    if not isinstance(record, dict):
        raise RecordError(E.RECORD_NOT_OBJECT, f"{cls.__name__} record must be an object")
    check_envelope(record, TIME_VERSION)
    names = {f.name for f in fields(cls)}
    present = set(record) - {"contract_version"}
    missing = sorted(names - present)
    if missing:
        raise RecordError(E.RECORD_FIELD_MISSING, f"{cls.__name__}.{missing[0]} is required")
    if present - names:  # unknown names are input text, so they are not echoed
        raise RecordError(E.RECORD_FIELD_UNKNOWN, f"{cls.__name__} has an unknown field")
    return {name: record[name] for name in names}


def _identical(record, expected):
    """Field-by-field equality that also requires identical types (so True never equals 1)."""
    return record.keys() == expected.keys() and all(
        type(record[k]) is type(expected[k]) and record[k] == expected[k] for k in expected)


def _to_record(obj):
    return {"contract_version": TIME_VERSION, **{f.name: getattr(obj, f.name) for f in fields(obj)}}


@dataclass(frozen=True)
class ClockDomain:
    """A declared synthetic clock domain. Construct only through ``clock_domain``."""

    clock_domain_id: str
    status: str
    offset_ms: object
    offset_uncertainty_ms: object
    offset_provenance: object
    continuity: str

    def to_record(self):
        return _to_record(self)

    @classmethod
    def from_record(cls, record):
        data = _strict_fields(record, cls)
        domain = clock_domain(**data)
        if not _identical({"contract_version": TIME_VERSION, **data}, domain.to_record()):
            raise RecordError(E.RECORD_INCONSISTENT, "clock domain fields have unexpected types")
        return domain


def clock_domain(clock_domain_id, status, offset_ms=None, offset_uncertainty_ms=None,
                 offset_provenance=None, continuity=UNKNOWN):
    """Validate a clock-domain declaration. ``offset_uncertainty_ms=None`` means unbounded."""
    _identifier(clock_domain_id, "clock_domain_id")
    if status not in CLOCK_STATUSES:
        raise RecordError(E.RECORD_FIELD_INVALID, "status must be declared or unknown")
    if continuity not in CONTINUITY_VALUES:
        raise RecordError(E.RECORD_FIELD_INVALID, "continuity is not a supported value")
    if status == DECLARED:
        if offset_provenance != FIXTURE_DECLARED:
            raise RecordError(E.RECORD_FIELD_INVALID, "only fixture_declared offsets are supported")
        _bounded_int(offset_ms, "offset_ms", -MAX_CLOCK_OFFSET_MS, MAX_CLOCK_OFFSET_MS,
                     E.CLOCK_OFFSET_OUT_OF_RANGE, TimeError)
        if offset_uncertainty_ms is not None:
            _bounded_int(offset_uncertainty_ms, "offset_uncertainty_ms", 0, MAX_OFFSET_UNCERTAINTY_MS,
                         E.CLOCK_OFFSET_OUT_OF_RANGE, TimeError)
    elif (offset_ms, offset_uncertainty_ms, offset_provenance) != (None, None, None):
        raise RecordError(E.RECORD_FIELD_INVALID, "an unknown clock cannot declare an offset")
    return ClockDomain(clock_domain_id, status, offset_ms, offset_uncertainty_ms, offset_provenance,
                       continuity)


@dataclass(frozen=True)
class SourceTimestamp:
    """One source timestamp with retained raw text. Construct only through ``source_timestamp``."""

    timestamp_kind: str
    clock_domain_id: str
    raw: str
    parse_status: str
    parse_error: object
    epoch_ms: object
    zone_offset_minutes: object
    local_offset_unknown: object
    text_precision_ns: object
    declared_precision_ns: object
    effective_precision_ns: object
    local_lower_ms: object
    local_upper_ms: object

    def to_record(self):
        return _to_record(self)

    @classmethod
    def from_record(cls, record):
        """Strictly decode a record and recompute every derived field from the raw text."""
        data = _strict_fields(record, cls)
        rebuilt = source_timestamp(data["raw"], timestamp_kind=data["timestamp_kind"],
                                   clock_domain_id=data["clock_domain_id"],
                                   declared_precision_ns=data["declared_precision_ns"])
        if not _identical({"contract_version": TIME_VERSION, **data}, rebuilt.to_record()):
            raise RecordError(E.RECORD_INCONSISTENT, "derived time fields do not match the raw text")
        return rebuilt


def source_timestamp(raw, *, timestamp_kind, clock_domain_id, declared_precision_ns=None):
    """Retain ``raw`` and derive its local interval; unparseable text is kept with a reason code.

    Raises only when the text cannot be retained (not a string, longer than
    ``MAX_RAW_CHARS`` or containing lone surrogates) or a metadata field is invalid.
    """
    _identifier(timestamp_kind, "timestamp_kind")
    _identifier(clock_domain_id, "clock_domain_id")
    if not isinstance(raw, str):
        raise TimeError(E.TIMESTAMP_NOT_STRING, "timestamp must be a string")
    if len(raw) > MAX_RAW_CHARS:
        raise TimeError(E.TIMESTAMP_TOO_LONG, f"raw timestamp exceeds {MAX_RAW_CHARS} characters")
    if _SURROGATE.search(raw):
        raise TimeError(E.TIMESTAMP_MALFORMED, "raw timestamp contains a lone surrogate")
    if declared_precision_ns is not None:
        _bounded_int(declared_precision_ns, "declared_precision_ns", 1, MAX_PRECISION_NS,
                     E.PRECISION_INVALID, TimeError)
    unparsed = dict(epoch_ms=None, zone_offset_minutes=None, local_offset_unknown=None,
                    text_precision_ns=None, effective_precision_ns=None,
                    local_lower_ms=None, local_upper_ms=None)
    try:
        parsed = parse_rfc3339(raw)
    except TimeError as exc:
        status = LEAP_SECOND if exc.code == E.LEAP_SECOND_UNSUPPORTED else INVALID
        return SourceTimestamp(timestamp_kind, clock_domain_id, raw, status, exc.code,
                               declared_precision_ns=declared_precision_ns, **unparsed)
    effective = max(parsed.text_precision_ns, declared_precision_ns or 0)
    end_ns = parsed.epoch_ns + effective
    return SourceTimestamp(
        timestamp_kind, clock_domain_id, raw, PARSED, None,
        epoch_ms=parsed.epoch_ns // NS_PER_MS,
        zone_offset_minutes=parsed.zone_offset_minutes,
        local_offset_unknown=parsed.local_offset_unknown,
        text_precision_ns=parsed.text_precision_ns,
        declared_precision_ns=declared_precision_ns,
        effective_precision_ns=effective,
        local_lower_ms=parsed.epoch_ns // NS_PER_MS,
        local_upper_ms=-(-end_ns // NS_PER_MS) - 1)


def reference_interval(timestamp, domain):
    """Return ``(lower, upper)`` on the reference clock, or ``None`` when no bound exists.

    A bound exists only for a parsed timestamp in a declared domain with bounded uncertainty
    and declared continuity; an offset bound cannot be trusted across a possible step.
    """
    if (timestamp.parse_status != PARSED or domain.clock_domain_id != timestamp.clock_domain_id
            or domain.status != DECLARED or domain.offset_uncertainty_ms is None
            or domain.continuity != CONTINUOUS):
        return None
    lower = timestamp.local_lower_ms - domain.offset_ms - domain.offset_uncertainty_ms
    upper = timestamp.local_upper_ms - domain.offset_ms + domain.offset_uncertainty_ms
    return lower, upper


@dataclass(frozen=True)
class Ordering:
    order: str
    basis: str

    def to_record(self):
        return _to_record(self)


def _order(a_low, a_high, b_low, b_high, ordered_basis, overlap_basis):
    if a_high < b_low:
        return Ordering(BEFORE, ordered_basis)
    if b_high < a_low:
        return Ordering(AFTER, ordered_basis)
    return Ordering(UNORDERED, overlap_basis)


def compare(a, b, domains):
    """Order timestamp ``a`` relative to ``b`` using only intervals and declared clock domains.

    ``domains`` maps clock-domain IDs to ``ClockDomain``. A missing domain is unknown.
    """
    if not isinstance(a, SourceTimestamp) or not isinstance(b, SourceTimestamp):
        raise RecordError(E.RECORD_FIELD_INVALID, "compare requires SourceTimestamp values")
    for key, domain in domains.items():
        if not isinstance(domain, ClockDomain) or domain.clock_domain_id != key:
            raise RecordError(E.RECORD_INCONSISTENT, "clock domain mapping key does not match its record")
    if a.parse_status != PARSED or b.parse_status != PARSED:
        return Ordering(UNORDERED, UNPARSED_TIMESTAMP)
    da, db = domains.get(a.clock_domain_id), domains.get(b.clock_domain_id)
    if da is None or db is None:
        return Ordering(UNORDERED, UNKNOWN_CLOCK)
    if STEP_DECLARED in (da.continuity, db.continuity):
        return Ordering(UNORDERED, CLOCK_STEP)
    if da.continuity != CONTINUOUS or db.continuity != CONTINUOUS:
        return Ordering(UNORDERED, CONTINUITY_UNKNOWN)
    if a.clock_domain_id == b.clock_domain_id:
        return _order(a.local_lower_ms, a.local_upper_ms, b.local_lower_ms, b.local_upper_ms,
                      SAME_DOMAIN, SAME_DOMAIN_OVERLAP)
    if UNKNOWN in (da.status, db.status):
        return Ordering(UNORDERED, UNKNOWN_CLOCK)
    ra, rb = reference_interval(a, da), reference_interval(b, db)
    if ra is None or rb is None:
        return Ordering(UNORDERED, UNBOUNDED_UNCERTAINTY)
    return _order(*ra, *rb, REFERENCE_INTERVAL, REFERENCE_OVERLAP)
