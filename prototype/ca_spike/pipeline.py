"""Investigation run and retained-input replay."""

import uuid
from dataclasses import asdict
from time import perf_counter_ns

from .acquire import acquire
from .assemble import assemble, seal, versions
from .baseline import naive_temporal_correlation
from .canonical import CanonicalError, digest
from .model import (AcquisitionOutcome, EVIDENCE_CLASS, evidence_identity, make_evidence_id,
                    observation_payload)
from .store import ArtifactMissing
from .synthesis import run_synthesis


def fixture_info(scenario):
    manifest = scenario["fixture_manifest"]
    return {"fixture_id": manifest["fixture_id"], "fixture_version": manifest["fixture_version"],
            "fixture_manifest_digest": digest(manifest)}


def run_investigation(scenario, store, permute_seed=None, duplicate_delivery=False, extra_observations=None):
    """Execute one offline run and persist its artifacts. Returns a summary dict."""
    plan = scenario["plan"]
    observations = scenario["observations"]
    if extra_observations:
        observations = dict(observations, acquisitions=observations["acquisitions"] + extra_observations)
    clock_domains = observations["clock_domains"]
    timings = {}

    t0 = perf_counter_ns()
    outcomes, deliveries = acquire(observations, plan, permute_seed, duplicate_delivery)
    t1 = perf_counter_ns()
    sealed = seal(outcomes, deliveries, clock_domains, plan, fixture_info(scenario))
    t2 = perf_counter_ns()
    bundle, bundle_digest = assemble(sealed, plan)
    t3 = perf_counter_ns()
    baseline = naive_temporal_correlation(sealed["evidence"], plan)
    t4 = perf_counter_ns()
    synth_cfg = scenario["variant"]["synthesis"]
    synthesis = run_synthesis(synth_cfg["mode"], scenario.get("synthesis_stub"), bundle, bundle_digest)
    t5 = perf_counter_ns()
    timings.update(acquire_ns=t1 - t0, seal_ns=t2 - t1, assemble_ns=t3 - t2,
                   bundle_assembly_total_ns=t3 - t1, baseline_ns=t4 - t3, synthesis_ns=t5 - t4)

    run_state = bundle["deterministic_state"]
    partial_reasons = list(bundle["partial_reasons"])
    if synthesis["status"] in ("rejected", "unavailable"):
        run_state = "partial"
        partial_reasons.append(f"synthesis_{synthesis['status']}")

    store.put("inputs.json", {
        "clock_domains": clock_domains, "plan": plan, "fixture": fixture_info(scenario),
        "outcomes": [asdict(o) for o in outcomes],
        "deliveries": [{"query_id": q, "source_id": s, "observation": o} for q, s, o in deliveries],
    })
    store.put("manifest.json", {"manifest": sealed["manifest"], "manifest_digest": sealed["manifest_digest"]})
    store.put("evidence.json", [e.record() for e in sealed["evidence"]])
    store.put("bundle.json", {"bundle": bundle, "bundle_digest": bundle_digest})
    store.put("baseline.json", baseline)
    store.put("synthesis.json", synthesis)
    run = {
        "run_id": str(uuid.uuid4()),
        "variant": scenario["variant"]["variant"],
        "state": run_state,
        "stage_history": ["queued", "collecting", "sealed", "assembling", bundle["deterministic_state"]],
        "partial_reasons": partial_reasons,
        "synthesis_status": synthesis["status"],
        "manifest_digest": sealed["manifest_digest"],
        "bundle_digest": bundle_digest,
        "delivery": {"permute_seed": permute_seed, "duplicate_delivery": duplicate_delivery,
                     "deliveries": len(deliveries), "duplicates_dropped": sealed["duplicates_dropped"]},
        "workload": {"evidence_records": len(sealed["evidence"]),
                     "extra_observations": sum(len(a["observations"]) for a in extra_observations or [])},
        "stage_timings_ns": timings,
        "approval_status": "not_approved",
        "gate_eligible": False,
    }
    store.put("run.json", run)
    return run


def _verify_evidence_records(records, manifest):
    problems = []
    listed = {eid: cd for eid, cd in manifest["evidence"]}
    seen = set()
    for rec in records:
        eid = rec.get("evidence_id")
        seen.add(eid)
        payload = observation_payload({
            "source_ref": rec["source_ref"], "observation_kind": rec["observation_kind"],
            "source_uid": rec["source_uid"], "source_version": rec["source_version"], "entity": rec["entity"],
            "times": [{"type": t["type"], "raw": t["raw"], "clock_domain": t["clock_domain"]} for t in rec["times"]],
            "attributes": rec["attributes"]})
        expected_id = make_evidence_id(EVIDENCE_CLASS.get(rec["observation_kind"], "UNKNOWN"), evidence_identity(
            rec["source_id"], rec["observation_kind"], rec["source_uid"], rec["source_version"]))
        if eid not in listed:
            problems.append(f"evidence_not_in_manifest:{eid}")
        elif digest(payload) != listed[eid] or rec["content_digest"] != listed[eid]:
            problems.append(f"content_digest_mismatch:{eid}")
        if expected_id != eid:
            problems.append(f"identity_mismatch:{eid}")
    problems += [f"evidence_missing:{eid}" for eid in sorted(set(listed) - seen)]
    return problems


def replay(store):
    """Verify retained artifacts and recompute the bundle without any fresh acquisition."""
    try:
        inputs = store.get("inputs.json")
        stored_manifest = store.get("manifest.json")
        records = store.get("evidence.json")
        stored_bundle = store.get("bundle.json")
    except ArtifactMissing as exc:
        return {"state": "missing_unexplained", "details": [f"artifact_missing:{exc}"]}
    except CanonicalError as exc:
        return {"state": "integrity_mismatch", "details": [f"unparseable_artifact:{exc}"]}

    manifest = stored_manifest["manifest"]
    if manifest.get("versions") != versions():
        return {"state": "version_incompatible", "details": ["stored versions differ from current engine"]}
    problems = []
    if digest(manifest) != stored_manifest["manifest_digest"]:
        problems.append("manifest_digest_mismatch")
    if digest(stored_bundle["bundle"]) != stored_bundle["bundle_digest"]:
        problems.append("stored_bundle_digest_mismatch")
    problems += _verify_evidence_records(records, manifest)

    outcomes = [AcquisitionOutcome(**o) for o in inputs["outcomes"]]
    deliveries = [(d["query_id"], d["source_id"], d["observation"]) for d in inputs["deliveries"]]
    sealed = seal(outcomes, deliveries, inputs["clock_domains"], inputs["plan"], inputs["fixture"])
    if sealed["manifest_digest"] != stored_manifest["manifest_digest"]:
        problems.append("retained_inputs_do_not_match_manifest")
    if problems:
        return {"state": "integrity_mismatch", "details": problems}

    _, bundle_digest = assemble(sealed, inputs["plan"])
    if bundle_digest != stored_bundle["bundle_digest"]:
        return {"state": "not_equivalent", "details": [f"recomputed {bundle_digest}"]}
    return {"state": "equivalent", "details": [], "bundle_digest": bundle_digest,
            "manifest_digest": sealed["manifest_digest"]}
