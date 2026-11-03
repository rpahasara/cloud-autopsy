"""Paged frozen-input manifest ``ca-frozen-input/0.2-provisional`` (CA-CON-003, CA-P2-002d).

``seal(plan, registry, deliveries)`` turns acquisition batches into a small root manifest plus
bounded, content-addressed pages. Gap policy ``ca-gap-policy/0.2-provisional`` (provisional):

Bounded input. Deliveries are consumed lazily. Every delivered record, duplicates included,
counts toward ``max_batch_deliveries`` before it is decoded. Every distinct batch variant,
conflicting variants included, counts toward ``max_batches_per_acquisition``,
``max_observations_total`` and ``max_total_bytes`` as soon as it is seen. Exceeding a limit
rejects the seal with ``limit_exceeded``; nothing is dropped silently.

Acquisitions. Identical redeliveries of a batch (same source, query, batch_key and digest) are
idempotent. Different content under one batch_key is a batch conflict: every variant is
excluded from coverage and evidence. A batch is *clean* when it is ``complete`` or ``empty``,
untruncated and in the unbroken cursor chain (sequence 1, 2, ... with matching cursors).
Verified coverage is the union of clean batch coverage. An acquisition is ``complete`` or
``empty`` only when verified coverage spans the window and there is no unresolved batch
(partial, failed, denied, truncated or out of chain) and no conflict. Gaps have a subject:
  coverage  part of the window outside verified coverage (missing, failed, truncated or
            unverifiable, by the worst cause in that acquisition)
  batch     each unresolved batch, and each batch conflict (with the conflicting digests)
  identity  each evidence identity seen with more than one content digest
Any gap makes the manifest ``incomplete`` with sorted limitations.

Evidence. Authoritative identities are members with a coverage qualification: ``verified`` if
any delivering batch is clean, otherwise ``unverified`` (kept, never silently trusted, and
flagged by the ``unverified_evidence_included`` limitation). Coverage, evidence availability
(``availability_generation``) and membership are separate fields. Conflicted identities are
excluded from membership. Which batches delivered which content is recorded in the
``evidence_provenance`` collection.

Paging. Each collection (``batches``, ``coverage``, ``evidence``, ``evidence_provenance``,
``gaps``) is sorted by a unique key and split greedily into pages of at most
``PAGE_MAX_ITEMS`` items and ``PAGE_MAX_BYTES`` canonical bytes. The root commits, per
collection, the item count and the ordered pages (index, item count and the page digest
``ca-frozen-input-page-sha256/0.1-provisional``). Key ranges are not repeated in the root, which keeps
it under about 250 KB at the provisional ceilings; ordering across pages is checked from the pages. ``verify_root`` checks the
root alone; ``verify_full`` also requires exactly the committed pages, intact and in order;
``verify_replay`` re-seals the retained batches and requires identical bytes.

Determinism. Delivery order, duplicates, retries and delivery attempts do not change any byte.
Run IDs, wall-clock times and delivery counts are excluded and listed in
``excluded_from_digest``. Evidence appears only as IDs and digests: no payloads, credentials or
ground truth. This is a pure function; atomic sealing and storage belong to CA-P2-003.

Version history: 0.1-provisional (PR #19 at 3930740) was a single document limited to about
6,000 members, could report an acquisition complete while a partial, failed or out-of-chain
batch existed, admitted unverified evidence without qualification, and excluded conflicting
variants before applying total limits.
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

FROZEN_INPUT_VERSION = "ca-frozen-input/0.2-provisional"
MANIFEST_ALGORITHM = "ca-frozen-input-sha256/0.2-provisional"
PAGE_VERSION = "ca-frozen-input-page/0.1-provisional"
PAGE_ALGORITHM = "ca-frozen-input-page-sha256/0.1-provisional"
GAP_POLICY_VERSION = "ca-gap-policy/0.2-provisional"

# PROVISIONAL page bounds (unreviewed).
PAGE_MAX_ITEMS = 1_000
PAGE_MAX_BYTES = 262_144

COMPLETE, INCOMPLETE = "complete", "incomplete"
MISSING, FAILED, TRUNCATED, UNVERIFIABLE = "missing", "failed", "truncated", "unverifiable"
VERIFIED, UNVERIFIED = "verified", "unverified"
CHAINED, OUT_OF_CHAIN, CONFLICTING = "chained", "out_of_chain", "conflicting"
EXCLUDED_FROM_DIGEST = ("batch.delivery.attempt", "batch arrival order", "duplicate batch deliveries",
                        "delivery counts", "run_id", "wall-clock and stage timings")

COLLECTION_KEYS = {
    "batches": ("source_id", "query_id", "batch_key", "batch_digest"),
    "coverage": ("source_id", "query_id", "start"),
    "evidence": ("evidence_id",),
    "evidence_provenance": ("evidence_id", "content_digest", "batch_digest"),
    "gaps": ("gap_id",),
}
COLLECTION_FIELDS = {
    "batches": {"source_id", "query_id", "batch_key", "batch_digest", "sequence", "outcome", "reason", "truncated",
                "coverage_ms", "chain_status"},
    "coverage": {"source_id", "query_id", "start", "end"},
    "evidence": {"evidence_id", "content_digest", "coverage", "batch_count"},
    "evidence_provenance": {"evidence_id", "content_digest", "batch_digest"},
    "gaps": {"gap_id", "subject", "gap_type", "reasons", "source_id", "query_id", "interval_ms", "mandatory",
             "evidence_id", "variant_count", "batch_digests"},
}
ROOT_FIELDS = frozenset({
    "contract_version", "manifest_algorithm", "page_contract", "page_algorithm", "page_limits", "plan_digest",
    "plan_id", "registry_id", "registry_digest", "contract_versions", "rule_versions", "gap_policy_version",
    "availability_generation", "window_ms", "status", "limitations", "acquisitions", "collections",
    "excluded_from_digest", "manifest_digest"})
_PAGE_FIELDS = {"contract_version", "collection", "page_index", "items"}


def _key(collection, item):
    return [item[name] for name in COLLECTION_KEYS[collection]]


def _valid_key(collection, key):
    """Keys are lists of strings (coverage ``start`` is an integer) of the collection's arity."""
    names = COLLECTION_KEYS[collection]
    return isinstance(key, list) and len(key) == len(names) and all(
        (type(part) is int) if name == "start" else isinstance(part, str) for name, part in zip(names, key))


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


def _gap(subject, gap_type, reasons, *, source_id=None, query_id=None, interval=None, mandatory=None,
         evidence_id=None, variant_count=None, batch_digests=()):
    gap = {"subject": subject, "gap_type": gap_type, "reasons": sorted(set(reasons)), "source_id": source_id,
           "query_id": query_id,
           "interval_ms": None if interval is None else {"start": interval[0], "end": interval[1]},
           "mandatory": mandatory, "evidence_id": evidence_id, "variant_count": variant_count,
           "batch_digests": sorted(batch_digests)}
    return {"gap_id": canonical.digest(gap), **gap}


def _batch_problem(batch, in_chain):
    """(gap_type, reasons) for an unresolved batch, or None for a clean chained batch."""
    reasons = set()
    if batch.outcome in (acq.PARTIAL, acq.FAILED, acq.DENIED):
        reasons.add(batch.reason)
    if batch.truncated:
        reasons.add("truncated")
    if not in_chain:
        reasons.add("cursor_discontinuity")
    if not reasons:
        return None
    if batch.outcome in (acq.FAILED, acq.DENIED):
        return FAILED, reasons
    return (TRUNCATED if batch.truncated else UNVERIFIABLE), reasons


def _batch_item(source_id, query_id, batch, chain_status):
    return {"source_id": source_id, "query_id": query_id, "batch_key": batch.batch_key,
            "batch_digest": batch.digest, "sequence": batch.sequence, "outcome": batch.outcome,
            "reason": batch.reason, "truncated": batch.truncated,
            "coverage_ms": None if batch.coverage_ms is None else
            {"start": batch.coverage_ms[0], "end": batch.coverage_ms[1]},
            "chain_status": chain_status}


def _acquisition(plan, source_id, query_id, mandatory, batches, conflicts):
    """Summarize one planned acquisition. Returns (summary, gaps, batch items, coverage items, clean digests)."""
    gaps = [_gap("batch", UNVERIFIABLE, ["batch_conflict"], source_id=source_id, query_id=query_id,
                 mandatory=mandatory, batch_digests=digests) for digests in conflicts]
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
    chained = {b.digest for b in chain}

    clean, causes, items, problems = set(), set(), [], {}
    for batch in batches:
        problem = _batch_problem(batch, batch.digest in chained)
        if problem is None:
            clean.add(batch.digest)
        else:
            gap_type, reasons = problems[batch.digest] = problem
            causes.add(gap_type)
            gaps.append(_gap("batch", gap_type, reasons, source_id=source_id, query_id=query_id,
                             interval=batch.coverage_ms, mandatory=mandatory, batch_digests=[batch.digest]))
        items.append(_batch_item(source_id, query_id, batch, CHAINED if batch.digest in chained else OUT_OF_CHAIN))
    verified = _union(b.coverage_ms for b in batches if b.digest in clean)
    holes = _subtract((plan.window_start_ms, plan.window_end_ms), verified)
    if not batches:
        hole_type, hole_reasons = (UNVERIFIABLE, {"batch_conflict"}) if conflicts else (MISSING, {"no_acquisition"})
    else:
        hole_type = next((t for t in (FAILED, TRUNCATED, UNVERIFIABLE) if t in causes),
                         UNVERIFIABLE if conflicts else MISSING)
        hole_reasons = {r for _, reasons in problems.values() for r in reasons}
        if conflicts:
            hole_reasons.add("batch_conflict")
        if not hole_reasons:
            hole_reasons = {"coverage_gap"}
    gaps += [_gap("coverage", hole_type, hole_reasons, source_id=source_id, query_id=query_id, interval=hole,
                  mandatory=mandatory) for hole in holes]

    observed = sum(len(b.evidence) for b in batches)
    outcomes = {b.outcome for b in batches}
    if not batches:
        status = UNVERIFIABLE if conflicts else MISSING
    elif not holes and not conflicts and len(clean) == len(batches):
        status = acq.COMPLETE if observed else acq.EMPTY
    elif verified or outcomes & {acq.COMPLETE, acq.EMPTY, acq.PARTIAL}:
        status = acq.PARTIAL
    else:
        status = acq.DENIED if outcomes == {acq.DENIED} else acq.FAILED
    summary = {"source_id": source_id, "query_id": query_id, "mandatory": mandatory, "status": status,
               "batch_count": len(batches), "conflicting_batch_keys": len(conflicts),
               "observations_received": observed, "verified_ms": sum(e - s for s, e in verified),
               "gap_count": len(gaps)}
    coverage = [{"source_id": source_id, "query_id": query_id, "start": s, "end": e} for s, e in verified]
    return summary, gaps, items, coverage, clean


def _paginate(collection, items):
    """Split sorted items into bounded pages; return (commitment, [page bytes])."""
    items = sorted(items, key=lambda i: _key(collection, i))
    for previous, current in zip(items, items[1:]):
        if _key(collection, previous) == _key(collection, current):
            raise ManifestError(E.PAGE_INVALID, f"duplicate {collection} key")
    base = len(canonical.canonical_bytes({"contract_version": PAGE_VERSION, "collection": collection,
                                          "page_index": 1_000_000, "items": []}))
    pages, current, size = [], [], base
    for item in items:
        encoded = len(canonical.canonical_bytes(item))
        if base + encoded > PAGE_MAX_BYTES:
            raise ManifestError(E.LIMIT_EXCEEDED, f"one {collection} item exceeds the page byte bound")
        added = encoded + (1 if current else 0)
        if current and (len(current) == PAGE_MAX_ITEMS or size + added > PAGE_MAX_BYTES):
            pages.append(current)
            current, size, added = [], base, encoded
        current.append(item)
        size += added
    if current:
        pages.append(current)
    commitments, blobs = [], []
    for index, page_items in enumerate(pages):
        blob = canonical.canonical_bytes({"contract_version": PAGE_VERSION, "collection": collection,
                                          "page_index": index, "items": page_items})
        blobs.append(blob)
        commitments.append({"index": index, "item_count": len(page_items), "digest": page_digest(blob)})
    return {"item_count": len(items), "pages": commitments}, blobs


def page_digest(blob):
    return f"{PAGE_ALGORITHM}:{hashlib.sha256(blob).hexdigest()}"


def manifest_digest(body):
    return f"{MANIFEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"


def seal(plan, registry, deliveries):
    """Seal acquisition batches into a ``FrozenInput`` (root plus pages)."""
    if not isinstance(plan, RunPlan) or not isinstance(registry, SourceRegistry):
        raise RecordError(E.RECORD_FIELD_INVALID, "a RunPlan and SourceRegistry are required")
    if registry.registry_id != plan.registry_id or registry.digest != plan.registry_digest:
        raise ManifestError(E.REGISTRY_MISMATCH, "registry differs from the one pinned by the plan")
    try:
        stream = iter(deliveries)
    except TypeError:
        raise RecordError(E.RECORD_FIELD_INVALID, "deliveries must be iterable") from None

    variants, per_acquisition_variants = {}, {}
    delivered = total_observations = total_bytes = 0
    for record in stream:
        delivered += 1
        if delivered > plan.limit("max_batch_deliveries"):
            raise ManifestError(E.LIMIT_EXCEEDED, "deliveries exceed limits.max_batch_deliveries")
        batch = acq.decode_batch(record, plan, registry)
        found = variants.setdefault((batch.source_id, batch.query_id, batch.batch_key), {})
        if batch.digest in found:
            continue  # identical redelivery
        found[batch.digest] = batch
        acquisition = (batch.source_id, batch.query_id)
        per_acquisition_variants[acquisition] = per_acquisition_variants.get(acquisition, 0) + 1
        total_observations += len(batch.evidence)
        total_bytes += batch.canonical_size
        if per_acquisition_variants[acquisition] > plan.limit("max_batches_per_acquisition"):
            raise ManifestError(E.LIMIT_EXCEEDED, "an acquisition exceeds limits.max_batches_per_acquisition")
        if total_observations > plan.limit("max_observations_total"):
            raise ManifestError(E.LIMIT_EXCEEDED, "observations exceed limits.max_observations_total")
        if total_bytes > plan.limit("max_total_bytes"):
            raise ManifestError(E.LIMIT_EXCEEDED, "batches exceed limits.max_total_bytes")

    batches_by_acquisition, conflicts, batch_items = {}, {}, []
    for (source_id, query_id, _), found in sorted(variants.items()):
        if len(found) > 1:
            conflicts.setdefault((source_id, query_id), []).append(sorted(found))
            batch_items += [_batch_item(source_id, query_id, b, CONFLICTING) for b in found.values()]
            continue
        batches_by_acquisition.setdefault((source_id, query_id), []).extend(found.values())

    acquisitions, gaps, coverage_items = [], [], []
    ledger, provenance, verified_content = ev.EvidenceLedger(registry), set(), set()
    for source_id, query_id, mandatory in plan.expected_acquisitions:
        batches = sorted(batches_by_acquisition.get((source_id, query_id), []), key=lambda b: (b.sequence, b.digest))
        summary, acquisition_gaps, items, coverage, clean = _acquisition(
            plan, source_id, query_id, mandatory, batches, conflicts.get((source_id, query_id), []))
        acquisitions.append(summary)
        gaps += acquisition_gaps
        batch_items += items
        coverage_items += coverage
        for batch in batches:
            for item in batch.evidence:
                ledger.admit_constructed(item)
                provenance.add((item.evidence_id, item.content_digest, batch.digest))
                if batch.digest in clean:
                    verified_content.add((item.evidence_id, item.content_digest))

    provenance_count = {}
    for evidence_id, content_digest, _ in provenance:
        provenance_count[(evidence_id, content_digest)] = provenance_count.get((evidence_id, content_digest), 0) + 1
    members = []
    for entry in ledger.snapshot()["entries"]:
        evidence_id = entry["evidence_id"]
        if entry["state"] == ev.AUTHORITATIVE:
            content_digest = entry["content_digests"][0]
            members.append({"evidence_id": evidence_id, "content_digest": content_digest,
                            "coverage": VERIFIED if (evidence_id, content_digest) in verified_content else UNVERIFIED,
                            "batch_count": provenance_count[(evidence_id, content_digest)]})
        else:
            gaps.append(_gap("identity", UNVERIFIABLE, ["identity_conflict"],
                             source_id=ledger.quarantined(evidence_id)[0].source_id, evidence_id=evidence_id,
                             variant_count=len(entry["content_digests"])))

    limitations = set()
    for gap in gaps:
        if gap["subject"] == "identity":
            limitations.add("identity_conflicts_excluded")
        else:
            limitations.add("mandatory_acquisition_incomplete" if gap["mandatory"]
                            else "optional_acquisition_incomplete")
    if any(m["coverage"] == UNVERIFIED for m in members):
        limitations.add("unverified_evidence_included")

    sources = {"batches": batch_items, "coverage": coverage_items, "evidence": members,
               "evidence_provenance": [{"evidence_id": e, "content_digest": c, "batch_digest": b}
                                       for e, c, b in provenance],
               "gaps": gaps}
    collections, page_blobs = {}, []
    for name in sorted(COLLECTION_KEYS):
        collections[name], blobs = _paginate(name, sources[name])
        page_blobs += blobs

    body = {
        "contract_version": FROZEN_INPUT_VERSION, "manifest_algorithm": MANIFEST_ALGORITHM,
        "page_contract": PAGE_VERSION, "page_algorithm": PAGE_ALGORITHM,
        "page_limits": {"max_items": PAGE_MAX_ITEMS, "max_bytes": PAGE_MAX_BYTES},
        "plan_digest": plan.digest, "plan_id": plan.plan_id, "registry_id": registry.registry_id,
        "registry_digest": registry.digest, "contract_versions": dict(plan.contract_versions),
        "rule_versions": dict(plan.rule_versions), "gap_policy_version": GAP_POLICY_VERSION,
        "availability_generation": 0, "window_ms": {"start": plan.window_start_ms, "end": plan.window_end_ms},
        "status": INCOMPLETE if gaps else COMPLETE, "limitations": sorted(limitations),
        "acquisitions": acquisitions, "collections": collections,
        "excluded_from_digest": list(EXCLUDED_FROM_DIGEST),
    }
    try:
        root = canonical.canonical_bytes({**body, "manifest_digest": manifest_digest(body)})
    except canonical.CanonicalError as exc:
        if exc.code == E.DOCUMENT_TOO_LARGE:
            raise ManifestError(E.LIMIT_EXCEEDED, "root manifest exceeds the canonical document ceiling") from None
        raise
    return FrozenInput(root, tuple(page_blobs))


@dataclass(frozen=True)
class FrozenInput:
    """Sealed root and pages as immutable canonical bytes. Accessors return fresh copies."""

    root_bytes: bytes
    page_bytes: tuple  # canonical page blobs, ordered by collection name then page index

    def root(self):
        return canonical.loads(self.root_bytes)

    def pages(self):
        return [canonical.loads(blob) for blob in self.page_bytes]

    @property
    def digest(self):
        return self.root()["manifest_digest"]

    @property
    def status(self):
        return self.root()["status"]


def collection_items(frozen, collection):
    """All items of one collection, in committed order, from a sealed ``FrozenInput``."""
    return [item for page in frozen.pages() if page["collection"] == collection for item in page["items"]]


def _page_error(detail):
    return ManifestError(E.PAGE_INVALID, detail)


def verify_root(root, plan, registry, expected_digest=None):
    """Root-only integrity: exact fields, version, digest, pins and well-formed page commitments.

    It does not prove that any page exists or is intact; use ``verify_full`` for that. A root is
    self-certifying, so a fully re-forged manifest is internally consistent: pass the digest that
    was published or stored at seal time as ``expected_digest`` to bind verification to it.
    """
    if not isinstance(plan, RunPlan) or not isinstance(registry, SourceRegistry):
        raise RecordError(E.RECORD_FIELD_INVALID, "a RunPlan and SourceRegistry are required")
    if not isinstance(root, dict):
        raise RecordError(E.RECORD_NOT_OBJECT, "frozen input root must be an object")
    check_envelope(root, FROZEN_INPUT_VERSION)
    if set(root) != ROOT_FIELDS:
        code = E.RECORD_FIELD_MISSING if ROOT_FIELDS - set(root) else E.RECORD_FIELD_UNKNOWN
        raise RecordError(code, "frozen input root does not have exactly the root fields")
    body = {k: v for k, v in root.items() if k != "manifest_digest"}
    if root["manifest_digest"] != manifest_digest(body):
        raise ManifestError(E.MANIFEST_DIGEST_MISMATCH, "manifest_digest does not match the root")
    if expected_digest is not None and root["manifest_digest"] != expected_digest:
        raise ManifestError(E.MANIFEST_DIGEST_MISMATCH, "manifest is not the expected sealed manifest")
    if root["plan_digest"] != plan.digest:
        raise ManifestError(E.PLAN_MISMATCH, "manifest was sealed for a different plan")
    if root["registry_digest"] != registry.digest or registry.digest != plan.registry_digest:
        raise ManifestError(E.REGISTRY_MISMATCH, "manifest, plan and registry pins differ")
    if (root["page_contract"], root["page_algorithm"], root["page_limits"]) != (
            PAGE_VERSION, PAGE_ALGORITHM, {"max_items": PAGE_MAX_ITEMS, "max_bytes": PAGE_MAX_BYTES}):
        raise _page_error("page contract, algorithm or limits are not supported")
    collections = root["collections"]
    if not isinstance(collections, dict) or set(collections) != set(COLLECTION_KEYS):
        raise _page_error("collections must be exactly the supported collections")
    for name, commitment in collections.items():
        pages = commitment.get("pages") if isinstance(commitment, dict) else None
        if not isinstance(pages, list) or set(commitment) != {"item_count", "pages"}:
            raise _page_error(f"{name} commitment must have item_count and pages")
        total = 0
        for index, page in enumerate(pages):
            if not isinstance(page, dict) or set(page) != {"index", "item_count", "digest"} \
                    or page["index"] != index or type(page["item_count"]) is not int \
                    or not 1 <= page["item_count"] <= PAGE_MAX_ITEMS or not isinstance(page["digest"], str):
                raise _page_error(f"{name} page commitments must be indexed 0..n-1 with bounded counts")
            total += page["item_count"]
        if commitment["item_count"] != total:
            raise _page_error(f"{name} item_count does not equal the sum of its pages")
    return root


def verify_full(root, pages, plan, registry, expected_digest=None):
    """Root integrity plus every committed page present, intact, in order and complete.

    Supplying an identical page twice is tolerated (content addressing makes it the same page).
    """
    root = verify_root(root, plan, registry, expected_digest)
    supplied = {}
    for page in pages:
        if not isinstance(page, dict):
            raise RecordError(E.RECORD_NOT_OBJECT, "page must be an object")
        blob = canonical.canonical_bytes(page)
        supplied.setdefault(page_digest(blob), (page, len(blob)))
    committed, slots = {}, set()
    for name in sorted(root["collections"]):
        for commitment in root["collections"][name]["pages"]:
            committed[commitment["digest"]] = (name, commitment)
            slots.add((name, commitment["index"]))
    for digest in sorted(set(supplied) - set(committed)):
        page = supplied[digest][0]
        if (page.get("collection"), page.get("page_index")) in slots:
            raise ManifestError(E.PAGE_DIGEST_MISMATCH, "a supplied page differs from its committed digest")
        raise ManifestError(E.PAGE_UNEXPECTED, "a supplied page is not committed by the root")
    for digest, (name, _) in committed.items():
        if digest not in supplied:
            raise ManifestError(E.PAGE_MISSING, f"a committed {name} page is missing")
    for name in sorted(root["collections"]):
        previous_last = None
        for commitment in root["collections"][name]["pages"]:
            page, size = supplied[commitment["digest"]]
            first, last = _check_page(page, size, name, commitment)
            if previous_last is not None and not previous_last < first:
                raise _page_error(f"{name} pages must be ordered without overlapping or duplicate items")
            previous_last = last
    return root


def _check_page(page, size, name, commitment):
    check_envelope(page, PAGE_VERSION)
    if set(page) != _PAGE_FIELDS or page["collection"] != name or page["page_index"] != commitment["index"]:
        raise _page_error(f"{name} page header does not match its commitment")
    items = page["items"]
    if size > PAGE_MAX_BYTES or not isinstance(items, list) or len(items) != commitment["item_count"]:
        raise _page_error(f"{name} page size or item count does not match its commitment")
    keys = []
    for item in items:
        if not isinstance(item, dict) or set(item) != COLLECTION_FIELDS[name]:
            raise _page_error(f"{name} item does not have exactly the collection fields")
        keys.append(_key(name, item))
        if not _valid_key(name, keys[-1]):
            raise _page_error(f"{name} item key fields are malformed")
    if any(not a < b for a, b in zip(keys, keys[1:])):
        raise _page_error(f"{name} items must be strictly ordered without duplicates")
    return keys[0], keys[-1]


def verify_replay(root, pages, plan, registry, deliveries, expected_digest=None):
    """Full verification, then re-sealing the retained batches must reproduce every byte."""
    verify_full(root, pages, plan, registry, expected_digest)
    resealed = seal(plan, registry, deliveries)
    supplied = sorted(canonical.canonical_bytes(p) for p in pages)
    if resealed.root_bytes != canonical.canonical_bytes(root) or sorted(resealed.page_bytes) != supplied:
        raise ManifestError(E.REPLAY_MISMATCH, "re-sealing the retained batches gives a different manifest")
    return resealed
