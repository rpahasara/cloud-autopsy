"""End-to-end investigation flow for one synthetic variant.

``persist_and_seal``  plan -> run -> idempotent batch ingestion (any delivery order, with
                      duplicates and retries) -> two-phase seal, as the least-privileged roles.
``investigate_run``   load the sealed run and its own frozen clock declaration as ``ca_engine``
                      -> verify -> timeline -> ledger -> result -> verify the result (citations
                      and byte-identical replay). Callers cannot supply clock assumptions.
``record_result``     store the result once as ``ca_result_writer`` (CA-P2-006a).
``replay_stored``     load a stored result as ``ca_engine`` and re-verify it completely.
``offline_result``    the same engine on an in-memory seal of the same batches, with no
                      database, used to show the database path adds and loses nothing.
"""

import random

from ..contracts import acquisition as acq
from ..contracts import frozen_input as fi
from ..db import ingest, results, seal
from ..engine import inputs, result
from ..synthetic import scenario_001 as scenario


def deliveries(variant, seed=None):
    """The variant's batches in delivery order. With a seed: shuffled, with duplicates and retries."""
    records = scenario.batches(variant)
    if seed is None:
        return records
    rng = random.Random(seed)
    delivered = [dict(r) for r in records]
    for record in rng.sample(records, k=min(2, len(records))):
        delivered.append({**record, "delivery": {"attempt": rng.randint(2, 5)}})  # redelivery after a retry
    rng.shuffle(delivered)
    return delivered


def persist_and_seal(roles, variant, seed=None):
    plan = scenario.plan(variant)
    registry = scenario.registry()
    ingest.register_registry(roles["ca_planner"], registry)
    ingest.register_plan(roles["ca_planner"], plan)
    run_id = ingest.create_run(roles["ca_planner"], plan, scenario_id=f"scenario-001-{variant}")
    results.declare_clocks(roles["ca_planner"], run_id, plan, registry, scenario.clock_domain_records(variant))
    outcomes = [ingest.ingest_batch(roles["ca_ingest"], run_id, record, plan, registry).outcome
                for record in deliveries(variant, seed)]
    frozen = seal.seal_run(roles["ca_sealer"], run_id, plan, registry)
    return run_id, frozen.digest, outcomes


def investigate_run(engine_db, run_id):
    investigation = results.investigate(engine_db, run_id)
    return investigation.result, investigation.result_bytes


def record_result(engine_db, writer_db, run_id):
    """Investigate as ``ca_engine`` and store the bytes once as ``ca_result_writer``."""
    investigation = results.investigate(engine_db, run_id)
    outcome = results.store_result(writer_db, run_id, investigation.investigation_id, investigation.result_bytes)
    return outcome, investigation


def replay_stored(engine_db, run_id):
    return results.load_verified_result(engine_db, run_id)


def offline_result(variant, seed=None):
    plan, registry = scenario.plan(variant), scenario.registry()
    records = deliveries(variant, seed)
    frozen = fi.seal(plan, registry, records)
    members = {(m["evidence_id"], m["content_digest"]) for m in fi.collection_items(frozen, "evidence")}
    evidence = {}
    for record in records:
        for item in acq.decode_batch(record, plan, registry).evidence:
            if (item.evidence_id, item.content_digest) in members:
                evidence[item.evidence_id] = item.to_record()
    inp = inputs.build_input(frozen, plan, registry, list(evidence.values()), scenario.clock_domain_records(variant))
    _, result_bytes = result.build(inp)
    return result.verify_result(result_bytes, inp), result_bytes
