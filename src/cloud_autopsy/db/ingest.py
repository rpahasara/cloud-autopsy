"""Planning and idempotent batch ingestion (transaction T1 in docs/phase2/ca-p2-003/transactions.md).

Every batch is validated by the contract (``decode_batch``) before any write transaction opens.
Ingestion for one run is serialized by ``ca.ingest_lock_run`` (a row lock taken through a
SECURITY DEFINER function), so plan limits are exact. All rows are append-only:
an identical redelivery adds only a delivery receipt, a different batch under the same key and
a different version of the same evidence identity are both stored, never overwritten. Conflicts
are classified later, per run, by views and by the seal.
"""

import uuid
from dataclasses import dataclass

from ..contracts import ADDITIONAL_CONTRACT_VERSIONS, CONTRACT_VERSIONS, canonical
from ..contracts import acquisition as acq
from ..contracts import frozen_input as fi
from .adapter import DbError, with_retry

ACCEPTED, DUPLICATE, CONFLICTING_VARIANT = "accepted", "duplicate", "conflicting_variant"


class RunNotCollecting(RuntimeError):
    pass


class LimitExceeded(RuntimeError):
    pass


class EnvironmentMismatch(RuntimeError):
    pass


def expected_contract_pins():
    return {**CONTRACT_VERSIONS, "frozen-input-page": fi.PAGE_VERSION, "frozen-input-page-digest": fi.PAGE_ALGORITHM}


def check_environment(db):
    """Refuse any database that is not marked synthetic or whose contract pins differ (I4, I12)."""
    row = db.one("SELECT classification FROM ca.data_classification")
    if row is None or row[0] != "synthetic":
        raise EnvironmentMismatch("database is not classified synthetic")
    pins = dict(db.run("SELECT contract_name, contract_version FROM ca.contract_pin"))
    if pins != expected_contract_pins():
        raise EnvironmentMismatch("database contract pins differ from this package's contract versions")
    # CA-P2-004d (migration 0006): the additionally supported versions must be exactly this package's.
    supported = {}
    for name, version in db.run("SELECT contract_name, contract_version FROM ca.contract_version_supported"):
        supported.setdefault(name, set()).add(version)
    if supported != {k: set(v) for k, v in ADDITIONAL_CONTRACT_VERSIONS.items()}:
        raise EnvironmentMismatch("database supported contract versions differ from this package's")


def register_registry(planner_db, registry):
    record = registry.to_record()
    with planner_db.transaction():
        planner_db.run(
            "INSERT INTO ca.registry_snapshot (registry_digest, registry_id, contract_version, record_bytes) "
            "VALUES (:d, :i, :v, :b) ON CONFLICT DO NOTHING",
            d=registry.digest, i=registry.registry_id, v=record["contract_version"],
            b=canonical.canonical_bytes(record))
        for source in registry.sources:
            planner_db.run(
                "INSERT INTO ca.source_binding (registry_digest, source_id, source_kind, cluster_id, namespace, "
                "binding_digest) VALUES (:d, :s, :k, :c, :n, :b) ON CONFLICT DO NOTHING",
                d=registry.digest, s=source.source_id, k=source.source_kind, c=source.cluster_id,
                n=source.namespace, b=source.binding_digest)


def register_plan(planner_db, plan):
    record = plan.to_record()
    with planner_db.transaction():
        planner_db.run(
            "INSERT INTO ca.run_plan (plan_digest, plan_id, registry_digest, contract_version, window_start_ms, "
            "window_end_ms, record_bytes) VALUES (:d, :p, :r, :v, :s, :e, :b) ON CONFLICT DO NOTHING",
            d=plan.digest, p=plan.plan_id, r=plan.registry_digest, v=record["contract_version"],
            s=plan.window_start_ms, e=plan.window_end_ms, b=canonical.canonical_bytes(record))
        for source_id, query_id, mandatory in plan.expected_acquisitions:
            planner_db.run(
                "INSERT INTO ca.plan_acquisition (plan_digest, source_id, query_id, mandatory) "
                "VALUES (:d, :s, :q, :m) ON CONFLICT DO NOTHING", d=plan.digest, s=source_id, q=query_id, m=mandatory)


def create_run(planner_db, plan, scenario_id="synthetic", parent_run_id=None, attempt=1, investigation_id=None):
    """Create an investigation (unless given) and a run in state ``collecting``; return the run ID."""
    run_id = str(uuid.uuid4())
    with planner_db.transaction():
        if investigation_id is None:
            investigation_id = str(uuid.uuid4())
            planner_db.run("INSERT INTO ca.investigation (investigation_id, scenario_id, plan_digest) "
                           "VALUES (CAST(:i AS uuid), :s, :p)", i=investigation_id, s=scenario_id, p=plan.digest)
        planner_db.run("INSERT INTO ca.run (run_id, investigation_id, attempt, parent_run_id, plan_digest) "
                       "VALUES (CAST(:r AS uuid), CAST(:i AS uuid), :a, CAST(:p AS uuid), :d)",
                       r=run_id, i=investigation_id, a=attempt, p=parent_run_id, d=plan.digest)
    return run_id


@dataclass(frozen=True)
class IngestResult:
    outcome: str
    batch_digest: str
    evidence_count: int


def ingest_batch(ingest_db, run_id, record, plan, registry):
    """Validate and store one delivered batch record. Retries only serialization failures."""
    batch = acq.decode_batch(record, plan, registry)  # contract validation before any write
    stored = {k: v for k, v in record.items() if k != "delivery"}
    stored_bytes = canonical.canonical_bytes(stored)
    attempt = record["delivery"]["attempt"]
    return with_retry(lambda: _ingest_once(ingest_db, run_id, plan, batch, stored_bytes, attempt))


def _ingest_once(db, run_id, plan, batch, stored_bytes, attempt):
    key = dict(r=run_id, s=batch.source_id, q=batch.query_id, k=batch.batch_key)
    with db.transaction():
        state = db.one("SELECT ca.ingest_lock_run(CAST(:r AS uuid))", r=run_id)
        if state is None or state[0] is None:
            raise RunNotCollecting("run does not exist")
        if state[0] != "collecting":
            raise RunNotCollecting(f"run is {state[0]}")
        run_plan = db.one("SELECT plan_digest FROM ca.run WHERE run_id = CAST(:r AS uuid)", r=run_id)
        if run_plan[0] != plan.digest:
            raise RunNotCollecting("batch plan differs from the run's plan")

        deliveries = db.one("SELECT count(*) FROM ca.batch_delivery WHERE run_id = CAST(:r AS uuid)", r=run_id)[0]
        if deliveries + 1 > plan.limit("max_batch_deliveries"):
            raise LimitExceeded("deliveries exceed limits.max_batch_deliveries")
        variants = db.run("SELECT batch_digest FROM ca.acquisition_batch WHERE run_id = CAST(:r AS uuid) "
                          "AND source_id = :s AND query_id = :q AND batch_key = :k", **key)
        digests = {row[0] for row in variants}
        if batch.digest in digests:
            outcome = DUPLICATE
        else:
            outcome = CONFLICTING_VARIANT if digests else ACCEPTED
            totals = db.one("SELECT count(*) FILTER (WHERE source_id = :s AND query_id = :q), "
                            "coalesce(sum(observation_count), 0), coalesce(sum(canonical_size), 0) "
                            "FROM ca.acquisition_batch WHERE run_id = CAST(:r AS uuid)",
                            r=run_id, s=batch.source_id, q=batch.query_id)
            if totals[0] + 1 > plan.limit("max_batches_per_acquisition"):
                raise LimitExceeded("an acquisition exceeds limits.max_batches_per_acquisition")
            if totals[1] + len(batch.evidence) > plan.limit("max_observations_total"):
                raise LimitExceeded("observations exceed limits.max_observations_total")
            if totals[2] + batch.canonical_size > plan.limit("max_total_bytes"):
                raise LimitExceeded("batches exceed limits.max_total_bytes")
            coverage = batch.coverage_ms or (None, None)
            db.run("INSERT INTO ca.acquisition_batch (run_id, plan_digest, source_id, query_id, batch_key, "
                   "batch_digest, contract_version, sequence, outcome, coverage_start_ms, coverage_end_ms, "
                   "truncated, observation_count, canonical_size, record_bytes) VALUES (CAST(:r AS uuid), :p, :s, "
                   ":q, :k, :d, :v, :n, :o, :cs, :ce, :t, :c, :z, :b)",
                   **key, p=plan.digest, d=batch.digest, v=acq.plan_batch_version(plan), n=batch.sequence,
                   o=batch.outcome, cs=coverage[0], ce=coverage[1], t=batch.truncated, c=len(batch.evidence),
                   z=batch.canonical_size, b=stored_bytes)
            for evidence in sorted(batch.evidence, key=lambda e: (e.evidence_id, e.content_digest)):
                _store_evidence(db, run_id, batch, evidence)
        db.run("INSERT INTO ca.batch_delivery (run_id, source_id, query_id, batch_key, batch_digest, delivery_no, "
               "attempt) VALUES (CAST(:r AS uuid), :s, :q, :k, :d, :n, :a)",
               **key, d=batch.digest, n=deliveries + 1, a=attempt)
    return IngestResult(outcome, batch.digest, len(batch.evidence))


def _store_evidence(db, run_id, batch, evidence):
    ident = dict(e=evidence.evidence_id, s=evidence.source_id, c=evidence.cluster_id, n=evidence.namespace,
                 k=evidence.observation_kind, u=evidence.source_uid, v=evidence.source_version,
                 x=evidence.evidence_class)
    db.run("INSERT INTO ca.evidence_identity (evidence_id, source_id, cluster_id, namespace, observation_kind, "
           "source_uid, source_version, evidence_class) VALUES (:e, :s, :c, :n, :k, :u, :v, :x) "
           "ON CONFLICT (evidence_id) DO NOTHING", **ident)
    existing = db.one("SELECT source_id, cluster_id, namespace, observation_kind, source_uid, source_version, "
                      "evidence_class FROM ca.evidence_identity WHERE evidence_id = :e", e=evidence.evidence_id)
    if tuple(existing) != (ident["s"], ident["c"], ident["n"], ident["k"], ident["u"], ident["v"], ident["x"]):
        raise DbError("23505", "evidence identity collision: stored identity columns differ")
    record_bytes = canonical.canonical_bytes(evidence.to_record())
    inserted = db.run("INSERT INTO ca.evidence_version (evidence_id, content_digest, contract_version, record_bytes) "
                      "VALUES (:e, :d, :v, :b) ON CONFLICT DO NOTHING RETURNING 1",
                      e=evidence.evidence_id, d=evidence.content_digest, v="ca-evidence/0.1-provisional", b=record_bytes)
    # Migration 0007: the record as delivered under this source binding (the first-stored row above
    # may carry another registry's binding digest; it is never rewritten).
    db.run("INSERT INTO ca.evidence_binding_record (evidence_id, content_digest, source_binding_digest, record_bytes) "
           "VALUES (:e, :d, :s, :b) ON CONFLICT DO NOTHING",
           e=evidence.evidence_id, d=evidence.content_digest, s=evidence.source_binding_digest, b=record_bytes)
    if inserted:
        for t in evidence.times:
            db.run("INSERT INTO ca.evidence_time (evidence_id, content_digest, timestamp_kind, clock_domain_id, "
                   "parse_status, epoch_ms, local_lower_ms, local_upper_ms, effective_precision_ns) "
                   "VALUES (:e, :d, :k, :c, :p, :m, :lo, :hi, :pr)",
                   e=evidence.evidence_id, d=evidence.content_digest, k=t.timestamp_kind, c=t.clock_domain_id,
                   p=t.parse_status, m=t.epoch_ms, lo=t.local_lower_ms, hi=t.local_upper_ms,
                   pr=t.effective_precision_ns)
    db.run("INSERT INTO ca.run_delivered_evidence (run_id, evidence_id, content_digest) "
           "VALUES (CAST(:r AS uuid), :e, :d) ON CONFLICT DO NOTHING",
           r=run_id, e=evidence.evidence_id, d=evidence.content_digest)
    db.run("INSERT INTO ca.batch_evidence (run_id, source_id, query_id, batch_key, batch_digest, evidence_id, "
           "content_digest) VALUES (CAST(:r AS uuid), :s, :q, :k, :b, :e, :d) ON CONFLICT DO NOTHING",
           r=run_id, s=batch.source_id, q=batch.query_id, k=batch.batch_key, b=batch.digest,
           e=evidence.evidence_id, d=evidence.content_digest)
