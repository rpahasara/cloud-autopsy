"""Timeline ``ca-timeline-rules/0.1-provisional``: every source timestamp, never a single authoritative time.

Each entry keeps the raw text, timestamp kind, clock domain, parse status, effective precision,
the local interval and, only when the domain declares a bounded offset and continuity, the
reference interval (``timeinterval.reference_interval``). Nothing is converted silently.

Entries are listed in a deterministic *display* order: entries with a reference interval by
(lower, upper), then the rest, then by evidence ID and timestamp kind. Display order is not
chronology. Chronology is stated only by ``adjacent_orderings``, which applies
``timeinterval.compare`` to each neighbouring pair and records ``before`` or ``unordered``
with its basis (overlap, unknown clock, possible clock step, unparsed text, ...). The
mechanism rules use the same ``compare`` directly; they never use display order.
"""

from ..contracts import timeinterval as ti
from . import TIMELINE_RULES_VERSION, TIMELINE_RULES_VERSION_V2

OBSERVED = "observed"

ORDERING_NOTE = ("Display order is deterministic but is not chronology; only 'before' orderings are "
                 "established, and 'unordered' records why an order is unknown.")


def _interval(lower, upper):
    return None if lower is None else {"lower": lower, "upper": upper}


def _clock_status(timestamp, domains):
    domain = domains.get(timestamp.clock_domain_id)
    if domain is None:
        return "undeclared", None
    return domain.status, ti.reference_interval(timestamp, domain)


def entries(inp):
    rows = []
    for member in inp.members:
        evidence = member.evidence
        for stamp in evidence.times:
            status, reference = _clock_status(stamp, inp.clock_domains)
            domain = inp.clock_domains.get(stamp.clock_domain_id)
            rows.append({
                "entry_id": f"{evidence.evidence_id}#{stamp.timestamp_kind}",
                "evidence_id": evidence.evidence_id,
                "evidence_coverage": member.coverage,
                "observation_kind": evidence.observation_kind,
                "entity": dict(evidence.entity),
                "source_id": evidence.source_id,
                "timestamp_kind": stamp.timestamp_kind,
                "raw": stamp.raw,
                "parse_status": stamp.parse_status,
                "clock_domain_id": stamp.clock_domain_id,
                "clock_status": status,
                "clock_continuity": None if domain is None else domain.continuity,
                "effective_precision_ns": stamp.effective_precision_ns,
                "local_ms": _interval(stamp.local_lower_ms, stamp.local_upper_ms),
                "reference_ms": None if reference is None else {"lower": reference[0], "upper": reference[1]},
            })
    rows.sort(key=_display_key)
    return rows


def _display_key(row):
    ref, local = row["reference_ms"], row["local_ms"]
    if ref is not None:
        return (0, ref["lower"], ref["upper"], row["evidence_id"], row["timestamp_kind"])
    if local is not None:
        return (1, local["lower"], local["upper"], row["evidence_id"], row["timestamp_kind"])
    return (2, 0, 0, row["evidence_id"], row["timestamp_kind"])


def build(inp):
    rows = entries(inp)
    stamps = {f"{m.evidence.evidence_id}#{t.timestamp_kind}": t for m in inp.members for t in m.evidence.times}
    adjacent = []
    for a, b in zip(rows, rows[1:]):
        ordering = ti.compare(stamps[a["entry_id"]], stamps[b["entry_id"]], inp.clock_domains)
        adjacent.append({"a": a["entry_id"], "b": b["entry_id"], "order": ordering.order, "basis": ordering.basis})
    return {"rule_version": inp.timeline_rules, "ordering_note": ORDERING_NOTE, "entries": rows,
            "adjacent_orderings": adjacent}


def event_order(a, b, domains, rules=TIMELINE_RULES_VERSION):
    """Order evidence ``a`` relative to ``b`` by their ordering stamps (``ordering_stamp``)."""
    return ti.compare(ordering_stamp(a, rules), ordering_stamp(b, rules), domains)


def ordering_stamp(evidence, rules=TIMELINE_RULES_VERSION):
    """The one stamp a piece of evidence is ordered by.

    Timeline rules 0.1: its ``event`` stamp (every kind has one).
    Timeline rules 0.2 (CA-P2-005b): its ``observed`` stamp when it has one, with no fallback to
    ``event`` (a watched change's ``event`` stamp is a server-clock time such as creationTimestamp,
    not the time of the change); otherwise its ``event`` stamp. Which stamp is used never depends on
    whether it can order; ``timeinterval.compare`` then decides, failing closed as always.
    resourceVersions are never an input."""
    if rules == TIMELINE_RULES_VERSION_V2:
        for stamp in evidence.times:
            if stamp.timestamp_kind == OBSERVED:
                return stamp
    elif rules != TIMELINE_RULES_VERSION:
        raise ValueError("unknown timeline rules")
    return _event(evidence)


def _event(evidence):
    for stamp in evidence.times:
        if stamp.timestamp_kind == "event":
            return stamp
    raise ValueError("evidence has no event timestamp")  # every observation kind requires one
