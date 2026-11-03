"""Acquisition batch contract ``ca-acquisition-batch/0.1-provisional`` (CA-CON-002, CA-P2-002d).

A batch is one source response for one planned (source, query) acquisition. It is bound to
the plan digest, identified within its acquisition by ``batch_key`` (the idempotency key) and
ordered by ``sequence`` with an opaque cursor chain (``cursor.before`` must equal the previous
batch's ``cursor.after``; the first batch starts from ``null``).

Outcomes (from the Phase 1C data model) and what each proves:
  complete  coverage verified, at least one observation, no truncation
  empty     coverage verified, zero observations: the declared query returned nothing within
            that coverage. It proves nothing outside it and nothing about other queries.
  partial   coverage declared but not verified (a reason is required; truncation may be set);
            its observations are kept, its interval is not counted as covered
  failed    no coverage and no observations; a failure reason is required
  denied    no coverage and no observations; reason ``authorization_denied``
A failure or missing coverage is never empty.

The batch digest covers every field except ``delivery`` (attempt number), which is volatile.
Observations are validated with the CA-P2-002c evidence contract against the source binding.
"""

import re
from dataclasses import dataclass

from . import canonical
from . import errors as E
from . import evidence as ev
from .errors import ManifestError, RecordError
from .plan import RunPlan, exact_ms
from .sources import IDENTIFIER, SourceRegistry
from .versioning import check_envelope

BATCH_VERSION = "ca-acquisition-batch/0.1-provisional"
COMPLETE, EMPTY, PARTIAL, FAILED, DENIED = "complete", "empty", "partial", "failed", "denied"
OUTCOMES = (COMPLETE, EMPTY, PARTIAL, FAILED, DENIED)
PARTIAL_REASONS = ("rate_limited", "timeout", "page_limit", "response_too_large", "continuity_lost")
FAILED_REASONS = ("rate_limited", "timeout", "source_unavailable", "invalid_response")
DENIED_REASONS = ("authorization_denied",)
TRUNCATION_REASONS = ("page_limit", "response_too_large")
CURSOR = re.compile(r"[A-Za-z0-9._:=+/-]{1,256}", re.ASCII)  # opaque, printable, bounded
MAX_DELIVERY_ATTEMPT = ev.MAX_DELIVERY_ATTEMPT
_FIELDS = ("plan_digest", "source_id", "query_id", "batch_key", "sequence", "outcome", "reason", "coverage",
           "cursor", "truncation", "observations", "delivery")


def _invalid(detail):
    return ManifestError(E.BATCH_INVALID, detail)


@dataclass(frozen=True)
class AcquisitionBatch:
    source_id: str
    query_id: str
    batch_key: str
    sequence: int
    outcome: str
    reason: object
    coverage_ms: object      # (start_ms, end_ms) half-open, or None
    cursor_before: object
    cursor_after: object
    truncated: bool
    evidence: tuple          # ev.ObservedEvidence
    digest: str
    canonical_size: int

    @property
    def acquisition(self):
        return self.source_id, self.query_id


def batch_digest(record):
    """Digest of a batch record without its volatile ``delivery`` field."""
    return canonical.digest({k: v for k, v in record.items() if k != "delivery"})


def decode_batch(record, plan, registry):
    """Strictly validate one batch record against its plan and registry."""
    if not isinstance(plan, RunPlan) or not isinstance(registry, SourceRegistry):
        raise RecordError(E.RECORD_FIELD_INVALID, "a RunPlan and SourceRegistry are required")
    if not isinstance(record, dict):
        raise RecordError(E.RECORD_NOT_OBJECT, "acquisition batch must be an object")
    try:
        size = len(canonical.canonical_bytes(record, canonical.Limits(max_bytes=plan.limit("max_batch_bytes"))))
    except canonical.CanonicalError as exc:
        if exc.code == E.DOCUMENT_TOO_LARGE:
            raise ManifestError(E.LIMIT_EXCEEDED, "batch exceeds limits.max_batch_bytes") from None
        raise
    check_envelope(record, BATCH_VERSION)
    missing = [f for f in _FIELDS if f not in record]
    if missing:
        raise RecordError(E.RECORD_FIELD_MISSING, f"AcquisitionBatch.{missing[0]} is required")
    if set(record) - set(_FIELDS) - {"contract_version"}:
        raise RecordError(E.RECORD_FIELD_UNKNOWN, "acquisition batch has an unknown field")
    if record["plan_digest"] != plan.digest:
        raise ManifestError(E.PLAN_MISMATCH, "batch is bound to a different plan")
    if not plan.expects(record["source_id"], record["query_id"]):
        raise ManifestError(E.SOURCE_SCOPE_MISMATCH, "batch is not for a planned acquisition")
    if not isinstance(record["batch_key"], str) or not IDENTIFIER.fullmatch(record["batch_key"]):
        raise _invalid("batch_key must be a lowercase identifier")
    sequence = record["sequence"]
    if type(sequence) is not int or not 1 <= sequence <= plan.limit("max_batches_per_acquisition"):
        raise _invalid("sequence must be an integer within limits.max_batches_per_acquisition")
    delivery = record["delivery"]
    if not isinstance(delivery, dict) or set(delivery) != {"attempt"} or type(delivery["attempt"]) is not int \
            or not 1 <= delivery["attempt"] <= MAX_DELIVERY_ATTEMPT:
        raise _invalid(f"delivery must be exactly an attempt in 1..{MAX_DELIVERY_ATTEMPT}")

    cursor = record["cursor"]
    if not isinstance(cursor, dict) or set(cursor) != {"before", "after"}:
        raise _invalid("cursor must have exactly before and after")
    for side in ("before", "after"):
        if cursor[side] is not None and (not isinstance(cursor[side], str) or not CURSOR.fullmatch(cursor[side])):
            raise _invalid(f"cursor.{side} must be null or an opaque printable token")
    if (sequence == 1) != (cursor["before"] is None):
        raise _invalid("only the first batch starts from a null cursor")

    truncation = record["truncation"]
    if not isinstance(truncation, dict) or set(truncation) != {"truncated", "reason", "omitted_count"} \
            or type(truncation["truncated"]) is not bool:
        raise _invalid("truncation must have truncated, reason and omitted_count")
    if truncation["truncated"]:
        if truncation["reason"] not in TRUNCATION_REASONS:
            raise _invalid("a truncated batch needs a truncation reason")
        omitted = truncation["omitted_count"]
        if omitted is not None and (type(omitted) is not int or omitted < 1):
            raise _invalid("omitted_count must be null (unknown) or a positive integer")
    elif truncation["reason"] is not None or truncation["omitted_count"] is not None:
        raise _invalid("an untruncated batch has no truncation reason or count")

    outcome, reason, observations = record["outcome"], record["reason"], record["observations"]
    if outcome not in OUTCOMES:
        raise _invalid("outcome is not a supported value")
    if not isinstance(observations, list) or len(observations) > plan.limit("max_observations_per_batch"):
        raise ManifestError(E.LIMIT_EXCEEDED, "observations exceed limits.max_observations_per_batch")
    coverage = record["coverage"]
    if outcome in (FAILED, DENIED):
        allowed = FAILED_REASONS if outcome == FAILED else DENIED_REASONS
        if reason not in allowed or coverage is not None or observations or truncation["truncated"]:
            raise _invalid(f"a {outcome} batch has a {outcome} reason, no coverage, observations or truncation")
        coverage_ms = None
    else:
        if not isinstance(coverage, dict) or set(coverage) != {"start", "end"}:
            raise _invalid("coverage must have exactly start and end")
        coverage_ms = (exact_ms(coverage["start"], "coverage.start"), exact_ms(coverage["end"], "coverage.end"))
        if not plan.window_start_ms <= coverage_ms[0] < coverage_ms[1] <= plan.window_end_ms:
            raise _invalid("coverage must be a non-empty interval inside the plan window")
        if outcome == PARTIAL:
            if reason not in PARTIAL_REASONS:
                raise _invalid("a partial batch needs a partial reason")
        elif reason is not None or truncation["truncated"]:
            raise _invalid(f"a {outcome} batch has no reason and is not truncated")
        if outcome == COMPLETE and not observations:
            raise _invalid("a complete batch has observations; use empty for none")
        if outcome == EMPTY and observations:
            raise _invalid("an empty batch has no observations")

    delivery_meta = {"query_id": record["query_id"], "batch_id": record["batch_key"], "attempt": delivery["attempt"]}
    evidence = tuple(ev.observe(obs, source_id=record["source_id"], registry=registry, delivery=delivery_meta)
                     for obs in observations)
    return AcquisitionBatch(record["source_id"], record["query_id"], record["batch_key"], sequence, outcome, reason,
                            coverage_ms, cursor["before"], cursor["after"], truncation["truncated"], evidence,
                            batch_digest(record), size)
