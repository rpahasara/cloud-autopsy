"""End-to-end investigation flow for one synthetic variant.

``persist_and_seal``  plan -> run -> idempotent batch ingestion (any delivery order, with
                      duplicates and retries) -> two-phase seal, as the least-privileged roles.
``investigate_run``   load the sealed run and its own frozen clock declaration as ``ca_engine``
                      -> verify -> timeline -> ledger -> result -> verify the result (citations
                      and byte-identical replay). Callers cannot supply clock assumptions.
``record_result``     verify, then store the result once as ``ca_result_writer`` (CA-P2-006a).
``replay_stored``     load a stored result as ``ca_engine`` and re-verify it completely.
``offline_result``    the same engine on an in-memory seal of the same batches, with no
                      database, used to show the database path adds and loses nothing.
"""

import random

from ..db import ingest, results, seal
from ..synthetic import scenario_001 as scenario
from . import offline


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
    return persist_records(roles, scenario.plan(variant), scenario.registry(), scenario.clock_domain_records(variant),
                           deliveries(variant, seed), scenario_id=f"scenario-001-{variant}")


def persist_records(roles, plan, registry, clock_records, records, scenario_id, progress=None):
    """Register, create the run, freeze its clocks, ingest ``records`` in order and seal, each as its
    least-privileged role. ``progress`` (a dict), when given, receives ``run_id`` and the current
    ``stage`` as they happen, so a caller can report exactly where a failure left the run."""
    progress = {} if progress is None else progress
    progress["stage"] = "register"
    ingest.register_registry(roles["ca_planner"], registry)
    ingest.register_plan(roles["ca_planner"], plan)
    progress["stage"] = "create_run"
    run_id = ingest.create_run(roles["ca_planner"], plan, scenario_id=scenario_id)
    progress["run_id"] = run_id
    progress["stage"] = "declare_clocks"
    results.declare_clocks(roles["ca_planner"], run_id, plan, registry, clock_records)
    progress["stage"] = "ingest"
    outcomes = [ingest.ingest_batch(roles["ca_ingest"], run_id, record, plan, registry).outcome for record in records]
    progress["stage"] = "seal"
    frozen = seal.seal_run(roles["ca_sealer"], run_id, plan, registry)
    return run_id, frozen.digest, outcomes


def investigate_run(engine_db, run_id):
    investigation = results.investigate(engine_db, run_id)
    return investigation.result, investigation.result_bytes


def record_result(engine_db, writer_db, run_id):
    """Investigate as ``ca_engine``; store through the verifying write path as ``ca_result_writer``."""
    return results.record_investigation(engine_db, writer_db, run_id)


def replay_stored(engine_db, run_id):
    return results.load_verified_result(engine_db, run_id)


def offline_result(variant, seed=None):
    return offline_from_records(scenario.plan(variant), scenario.registry(), deliveries(variant, seed),
                                scenario.clock_domain_records(variant))


offline_from_records = offline.offline_from_records  # re-exported; the offline path needs no database
