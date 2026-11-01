"""Timestamp provenance, uncertainty intervals and ordering (ca-time/0.1-spike).

Offset is defined as ``source clock - reference clock``; a declared correction subtracts
it without replacing the original text. Intervals use inclusive millisecond bounds:
a timestamp truncated to precision P covers [t, t + P - 1]. A declared offset
uncertainty U widens that to [t - offset - U, t + P - 1 - offset + U]. A clock with
unknown status yields no reference-clock interval, so cross-domain order is unknown.

A precedes B only when A's upper bound is strictly below B's lower bound. Within one
clock domain, local intervals are compared without offset uncertainty (the shared
offset cancels); this assumes the domain clock did not step during the window.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timezone

TIME_RULE_VERSION = "ca-time/0.1-spike"

_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$")


class TimestampError(ValueError):
    pass


def parse_rfc3339_ms(raw):
    """Strictly parse an RFC 3339 timestamp to integer epoch milliseconds (floor)."""
    match = _RFC3339.match(raw) if isinstance(raw, str) else None
    if not match:
        raise TimestampError("not an RFC 3339 timestamp with explicit offset")
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    if second > 59:
        raise TimestampError("leap seconds are not representable")
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise TimestampError(str(exc)) from None
    epoch_s = calendar.timegm((year, month, day, hour, minute, second))
    frac = (match.group(7) or "").ljust(3, "0")[:3]
    zone = match.group(8)
    if zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        zh, zm = int(zone[1:3]), int(zone[4:6])
        if zh > 23 or zm > 59:
            raise TimestampError("invalid UTC offset")
        epoch_s -= sign * (zh * 3600 + zm * 60)
    return epoch_s * 1000 + int(frac)


def format_utc_ms(epoch_ms):
    seconds, millis = divmod(epoch_ms, 1000)
    base = datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{millis:03d}Z"


@dataclass(frozen=True)
class EvidenceTime:
    type: str
    raw: str
    clock_domain: str
    parse_status: str
    parse_error: str
    parsed_utc: str
    precision_ms: int
    clock_status: str
    offset_ms: int
    offset_uncertainty_ms: int
    offset_provenance: str
    local_lower_ms: int
    local_upper_ms: int
    lower_ms: int
    upper_ms: int


def build_time(entry, clock_domains):
    """Build an EvidenceTime from a fixture time entry and declared clock domains."""
    domain = entry["clock_domain"]
    clock = clock_domains.get(domain) or {"status": "unknown"}
    precision = entry.get("precision_ms", clock.get("precision_ms"))
    status = clock.get("status", "unknown")
    offset = clock.get("offset_ms") if status == "declared" else None
    uncertainty = clock.get("offset_uncertainty_ms") if status == "declared" else None
    raw = entry["raw"]
    try:
        epoch = parse_rfc3339_ms(raw)
        parse_status, parse_error = "ok", None
    except TimestampError as exc:
        epoch, parse_status, parse_error = None, "error", str(exc)

    local_lower = local_upper = lower = upper = None
    if epoch is not None and isinstance(precision, int) and precision >= 1:
        local_lower, local_upper = epoch, epoch + precision - 1
        if isinstance(offset, int) and isinstance(uncertainty, int) and uncertainty >= 0:
            lower = local_lower - offset - uncertainty
            upper = local_upper - offset + uncertainty
    return EvidenceTime(
        type=entry["type"], raw=raw, clock_domain=domain, parse_status=parse_status,
        parse_error=parse_error, parsed_utc=format_utc_ms(epoch) if epoch is not None else None,
        precision_ms=precision, clock_status=status, offset_ms=offset,
        offset_uncertainty_ms=uncertainty, offset_provenance=clock.get("provenance"),
        local_lower_ms=local_lower, local_upper_ms=local_upper, lower_ms=lower, upper_ms=upper)


def _cmp(a_lo, a_hi, b_lo, b_hi):
    if a_hi < b_lo:
        return "before"
    if b_hi < a_lo:
        return "after"
    return "unordered"


def compare(a, b):
    """Return (order, basis) for EvidenceTime a relative to b."""
    if a.parse_status != "ok" or b.parse_status != "ok":
        return "unordered", "unparseable_timestamp"
    if a.clock_domain == b.clock_domain and a.local_lower_ms is not None and b.local_lower_ms is not None:
        order = _cmp(a.local_lower_ms, a.local_upper_ms, b.local_lower_ms, b.local_upper_ms)
        return order, "same_domain" if order != "unordered" else "same_domain_overlap"
    if a.lower_ms is None or b.lower_ms is None:
        return "unordered", "unbounded_clock"
    order = _cmp(a.lower_ms, a.upper_ms, b.lower_ms, b.upper_ms)
    return order, "reference_interval" if order != "unordered" else "overlapping_intervals"


def invert(order):
    return {"before": "after", "after": "before"}.get(order, order)
