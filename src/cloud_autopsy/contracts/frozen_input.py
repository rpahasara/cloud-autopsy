"""Frozen-input manifest ``ca-frozen-input/0.1-provisional`` (CA-CON-003, CA-P2-002d).

``seal(plan, registry, batch_records)`` turns validated acquisition batches into one
deterministic manifest. Rules (provisional gap policy ``ca-gap-policy/0.1-provisional``):

* The registry must be the one the plan pins; otherwise ``registry_mismatch``.
* Batches are idempotent by (source, query, batch_key): an identical redelivery is dropped;
  a different batch under the same key is a batch conflict, and every variant of it is
  excluded (observations and coverage) and reported as an ``unverifiable`` gap.
* Verified coverage of an acquisition is the union of ``complete`` and ``empty`` batch
  coverage in its unbroken cursor chain (sequence 1, 2, ... with matching cursors). Anything
  of the plan window outside verified coverage is a gap: ``missing`` (no batch, or a coverage
  hole), ``failed`` (a failed or denied batch), ``truncated`` (a truncated batch) or
  ``unverifiable`` (partial batches, a broken cursor chain or a batch conflict). Failure or
  missing coverage is never reported as empty.
* Evidence goes through the CA-P2-002c ledger. Only authoritative identities are members;
  each conflicted identity is excluded and reported as an ``unverifiable`` gap listing its
  content digests.
* Any gap makes the manifest ``incomplete``, with sorted limitations. Nothing is dropped
  silently: exceeding a plan limit rejects the seal with ``limit_exceeded``.
* The manifest is order independent: reordering, duplicating or retrying identical batches
  gives byte-identical output. Delivery attempts, arrival order, duplicate counts, run IDs and
  wall-clock times are excluded and listed in ``excluded_from_digest``. Ground truth,
  credentials and raw payloads never enter it; evidence appears only as IDs and digests.
* ``availability_generation`` is 0 (availability at seal); lifecycle overlays are CA-P2-006.

This is a pure function. Atomic sealing against concurrent writers is CA-P2-003.
"""

import hashlib
from dataclasses import dataclass

from . import acquisition as acq
from . import canonical
from . import errors as E
from . import evidence as ev
from .errors import ManifestError, RecordError
from .plan import RunPlan
from .sources import SourceRegistry
from .versioning import check_envelope

FROZEN_INPUT_VERSION = "ca-frozen-input/0.1-provisional"
MANIFEST_ALGORITHM = "ca-frozen-input-sha256/0.1-provisional"
GAP_POLICY_VERSION = "ca-gap-policy/0.1-provisional"
COMPLETE, INCOMPLETE = "complete", "incomplete"
MISSING, FAILED, TRUNCATED, UNVERIFIABLE = "missing", "failed", "truncated", "unverifiable"
MANIFEST_FIELDS = frozenset({
    "contract_version", "manifest_algorithm", "plan_digest", "plan_id", "registry_id", "registry_digest",
    "contract_versions", "rule_versions", "gap_policy_version", "availability_generation", "window_ms", "status",
    "limitations", "acquisitions", "evidence", "gaps", "excluded_from_digest", "manifest_digest"})
EXCLUDED_FROM_DIGEST = ("batch.delivery.attempt", "batch arrival order", "duplicate batch deliveries",
                        "evidence ledger delivery counts", "run_id", "wall-clock and stage timings")


def _union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(i) for i in merged]


def _subtract(window, covered):
    holes, cursor = [], window[0]
    for start, end in covered:
        if start > cursor:
            holes.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window[1]:
        holes.append((cursor, window[1]))
    return holes


def _gap(gap_type, reasons, *, source_id=None, query_id=None, interval=None, mandatory=None, evidence_id=None,
         content_digests=(), batch_digests=()):
    gap = {"gap_type": gap_type, "reasons": sorted(set(reasons)), "source_id": source_id, "query_id": query_id,
           "interval_ms": None if interval is None else {"start": interval[0], "end": interval[1]},
           "mandatory": mandatory, "evidence_id": evidence_id, "content_digests": sorted(content_digests),
           "batch_digests": sorted(batch_digests)}
    return {"gap_id": canonical.digest(gap), **gap}


def _acquisition(plan, source_id, query_id, mandatory, batches, conflicts):
    """Summarize one planned acquisition; return (summary, gaps, member batches)."""
    gaps = [_gap(UNVERIFIABLE, ["batch_conflict"], source_id=source_id, query_id=query_id, mandatory=mandatory,
                 batch_digests=digests) for digests in conflicts]
    by_sequence = {}
    for batch in batches:
        by_sequence.setdefault(batch.sequence, []).append(batch)
    chain, previous_cursor = [], None
    for sequence in range(1, len(by_sequence) + 1):
        candidates = by_sequence.get(sequence, [])
        if len(candidates) != 1 or candidates[0].cursor_before != previous_cursor:
            break
        chain.append(candidates[0])
        previous_cursor = candidates[0].cursor_after
    reasons = set()
    if conflicts:
        reasons.add("batch_conflict")
    if len(chain) != len(batches):
        reasons.add("cursor_discontinuity")
    verified = _union(b.coverage_ms for b in chain if b.outcome in (acq.COMPLETE, acq.EMPTY))
    outcomes = {b.outcome for b in batches}
    for batch in batches:
        if batch.outcome in (acq.PARTIAL, acq.FAILED, acq.DENIED):
            reasons.add(batch.reason)
        if batch.truncated:
            reasons.add("truncated")
    holes = _subtract((plan.window_start_ms, plan.window_end_ms), verified)
    if not batches and conflicts:
        gap_type = UNVERIFIABLE
    elif not batches:
        gap_type, reasons = MISSING, {"no_acquisition"}
    elif outcomes & {acq.FAILED, acq.DENIED}:
        gap_type = FAILED
    elif any(b.truncated for b in batches):
        gap_type = TRUNCATED
    elif reasons:
        gap_type = UNVERIFIABLE
    else:
        gap_type, reasons = MISSING, {"coverage_gap"}
    gaps += [_gap(gap_type, reasons, source_id=source_id, query_id=query_id, interval=hole, mandatory=mandatory)
             for hole in holes]
    observed = sum(len(b.evidence) for b in batches)
    if not batches:
        status = "unverifiable" if conflicts else "missing"
    elif not holes and not conflicts:
        status = acq.COMPLETE if observed else acq.EMPTY
    elif verified or outcomes & {acq.COMPLETE, acq.EMPTY, acq.PARTIAL}:
        status = acq.PARTIAL
    else:
        status = acq.DENIED if outcomes == {acq.DENIED} else acq.FAILED
    summary = {"source_id": source_id, "query_id": query_id, "mandatory": mandatory, "status": status,
               "batch_digests": sorted(b.digest for b in batches), "observations_received": observed,
               "verified_coverage_ms": [{"start": s, "end": e} for s, e in verified]}
    return summary, gaps


def seal(plan, registry, batch_records):
    """Validate batches against the plan and produce a deterministic ``FrozenInput``."""
    if not isinstance(plan, RunPlan) or not isinstance(registry, SourceRegistry):
        raise RecordError(E.RECORD_FIELD_INVALID, "a RunPlan and SourceRegistry are required")
    if registry.registry_id != plan.registry_id or registry.digest != plan.registry_digest:
        raise ManifestError(E.REGISTRY_MISMATCH, "registry differs from the one pinned by the plan")
    if not isinstance(batch_records, (list, tuple)):
        raise RecordError(E.RECORD_FIELD_INVALID, "batches must be a list")

    variants = {}  # (source, query, batch_key) -> {digest: batch}
    for record in batch_records:
        batch = acq.decode_batch(record, plan, registry)
        variants.setdefault((batch.source_id, batch.query_id, batch.batch_key), {}).setdefault(batch.digest, batch)

    per_acquisition, conflicts, total_observations, total_bytes = {}, {}, 0, 0
    for (source_id, query_id, _), found in sorted(variants.items()):
        if len(found) > 1:
            conflicts.setdefault((source_id, query_id), []).append(sorted(found))
            continue
        (batch,) = found.values()
        per_acquisition.setdefault((source_id, query_id), []).append(batch)
        total_observations += len(batch.evidence)
        total_bytes += batch.canonical_size
    for batches in per_acquisition.values():
        if len(batches) > plan.limit("max_batches_per_acquisition"):
            raise ManifestError(E.LIMIT_EXCEEDED, "an acquisition exceeds limits.max_batches_per_acquisition")
    if total_observations > plan.limit("max_observations_total"):
        raise ManifestError(E.LIMIT_EXCEEDED, "observations exceed limits.max_observations_total")
    if total_bytes > plan.limit("max_total_bytes"):
        raise ManifestError(E.LIMIT_EXCEEDED, "batches exceed limits.max_total_bytes")

    acquisitions, gaps, ledger = [], [], ev.EvidenceLedger(registry)
    for source_id, query_id, mandatory in plan.expected_acquisitions:
        batches = sorted(per_acquisition.get((source_id, query_id), []), key=lambda b: (b.sequence, b.digest))
        summary, acquisition_gaps = _acquisition(plan, source_id, query_id, mandatory, batches,
                                                 conflicts.get((source_id, query_id), []))
        acquisitions.append(summary)
        gaps += acquisition_gaps
        for batch in batches:
            for item in batch.evidence:
                ledger.admit(item)

    members = []
    for entry in ledger.snapshot()["entries"]:
        if entry["state"] == ev.AUTHORITATIVE:
            members.append({"evidence_id": entry["evidence_id"], "content_digest": entry["content_digests"][0]})
        else:
            source_id = ledger.quarantined(entry["evidence_id"])[0].source_id
            gaps.append(_gap(UNVERIFIABLE, ["identity_conflict"], source_id=source_id,
                             evidence_id=entry["evidence_id"], content_digests=entry["content_digests"]))

    limitations = set()
    for gap in gaps:
        if gap["evidence_id"] is not None:
            limitations.add("identity_conflicts_excluded")
        elif gap["mandatory"]:
            limitations.add("mandatory_acquisition_incomplete")
        else:
            limitations.add("optional_acquisition_incomplete")

    body = {
        "contract_version": FROZEN_INPUT_VERSION, "manifest_algorithm": MANIFEST_ALGORITHM,
        "plan_digest": plan.digest, "plan_id": plan.plan_id, "registry_id": registry.registry_id,
        "registry_digest": registry.digest, "contract_versions": dict(plan.contract_versions),
        "rule_versions": dict(plan.rule_versions), "gap_policy_version": GAP_POLICY_VERSION,
        "availability_generation": 0,
        "window_ms": {"start": plan.window_start_ms, "end": plan.window_end_ms},
        "status": INCOMPLETE if gaps else COMPLETE, "limitations": sorted(limitations),
        "acquisitions": acquisitions, "evidence": members,
        "gaps": sorted(gaps, key=lambda g: g["gap_id"]),
        "excluded_from_digest": list(EXCLUDED_FROM_DIGEST),
    }
    try:
        return FrozenInput(canonical.canonical_bytes({**body, "manifest_digest": manifest_digest(body)}))
    except canonical.CanonicalError as exc:
        if exc.code == E.DOCUMENT_TOO_LARGE:  # provisional: no manifest chunking yet
            raise ManifestError(E.LIMIT_EXCEEDED, "manifest exceeds the canonical document ceiling") from None
        raise


def manifest_digest(body):
    return f"{MANIFEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"


@dataclass(frozen=True)
class FrozenInput:
    """Sealed manifest held as immutable canonical bytes; ``to_record`` returns a fresh copy."""

    canonical: bytes

    def to_record(self):
        return canonical.loads(self.canonical)

    @property
    def digest(self):
        return self.to_record()["manifest_digest"]

    @property
    def status(self):
        return self.to_record()["status"]


def verify(record, plan, registry):
    """Check a stored manifest's integrity and its plan and registry pins (no batches needed)."""
    if not isinstance(record, dict):
        raise RecordError(E.RECORD_NOT_OBJECT, "frozen input must be an object")
    check_envelope(record, FROZEN_INPUT_VERSION)
    if set(record) != MANIFEST_FIELDS:
        code = E.RECORD_FIELD_MISSING if MANIFEST_FIELDS - set(record) else E.RECORD_FIELD_UNKNOWN
        raise RecordError(code, "frozen input does not have exactly the manifest fields")
    body = {k: v for k, v in record.items() if k != "manifest_digest"}
    if record.get("manifest_digest") != manifest_digest(body):
        raise ManifestError(E.MANIFEST_DIGEST_MISMATCH, "manifest_digest does not match the manifest")
    if record["plan_digest"] != plan.digest:
        raise ManifestError(E.PLAN_MISMATCH, "manifest was sealed for a different plan")
    if record["registry_digest"] != registry.digest or registry.digest != plan.registry_digest:
        raise ManifestError(E.REGISTRY_MISMATCH, "manifest, plan and registry pins differ")
    return FrozenInput(canonical.canonical_bytes(record))


def verify_replay(record, plan, registry, batch_records):
    """Replay invariant: re-sealing the retained batches must reproduce the manifest exactly."""
    stored = verify(record, plan, registry)
    if seal(plan, registry, batch_records).canonical != stored.canonical:
        raise ManifestError(E.REPLAY_MISMATCH, "re-sealing the retained batches gives a different manifest")
    return stored
