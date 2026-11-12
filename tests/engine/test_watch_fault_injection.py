"""CA-P2-004f engine-level fault injection under contract profile 3 (offline, synthetic fixtures).

The engine and mechanism catalog are unchanged. Collector data alone cannot resolve (no symptom
source, limit values withheld, and the engine orders only by ``event`` times, which for collector
evidence are on the unknown API-server clock). So these fixtures add, synthetically, a typed
limit-lowering rollout, a pod of its new ReplicaSet and a POOL_EXHAUSTED log line, all with ``event``
times in one declared-continuous collector clock domain, and profile-3 batches whose coverage carries
a watch_continuity basis.

The control case resolves. Every injected fault (a gap, an unproven tail, withheld changes, an
overlapping bracket, a clock step, a symptom before the change, a second rollout hidden in a gap)
must make the engine abstain: missing evidence never becomes a false causal conclusion.
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.app import bundle as B  # noqa: E402
from cloud_autopsy.app import create as C  # noqa: E402
from cloud_autopsy.contracts import acquisition as acq  # noqa: E402
from cloud_autopsy.contracts import evidence as ev  # noqa: E402
from cloud_autopsy.contracts import plan as pl  # noqa: E402
from cloud_autopsy.contracts import timeinterval as ti  # noqa: E402
from cloud_autopsy.contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry  # noqa: E402
from cloud_autopsy.engine import required_rule_versions  # noqa: E402

DOMAIN = "ca-collector"
NS = "ca-demo"
WINDOW = ("2026-11-12T10:00:00.000Z", "2026-11-12T10:10:00.000Z")
REGISTRY_RECORD = {
    "contract_version": SOURCE_REGISTRY_VERSION, "registry_id": "ca-watch-engine-faults",
    "sources": [
        {"source_id": "k8s-api", "source_kind": "kubernetes_api", "cluster_id": "ca-kind-synthetic", "namespace": NS,
         "clock_domain_ids": [DOMAIN], "query_ids": ["k8s.deployments", "k8s.pods"]},
        {"source_id": "loki", "source_kind": "loki", "cluster_id": "ca-kind-synthetic", "namespace": NS,
         "clock_domain_ids": [DOMAIN], "query_ids": ["loki.checkout-api"]}]}
ACQUISITIONS = {"deployments": ("k8s-api", "k8s.deployments"), "pods": ("k8s-api", "k8s.pods"),
                "logs": ("loki", "loki.checkout-api")}
LIMITS = {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 10, "max_batch_deliveries": 100,
          "max_observations_per_batch": 100, "max_observations_total": 1000, "max_batch_bytes": 1_048_576,
          "max_total_bytes": 10_000_000}


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _time(raw, precision_ns=1_000_000_000, kind="event"):
    return {"timestamp_kind": kind, "raw": raw, "clock_domain_id": DOMAIN, "declared_precision_ns": precision_ns}


def _obs(kind, ref, uid, version, entity_kind, name, times, attributes):
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": ref, "observation_kind": kind,
            "source_uid": uid, "source_version": version, "entity": {"kind": entity_kind, "namespace": NS, "name": name},
            "times": times, "attributes": attributes}


def rollout(at="2026-11-12T10:02:00Z", revision="2", precision_ns=1_000_000_000, uid="uid-deploy"):
    return _obs("deployment_rollout", f"k8s:deployment/{NS}/checkout-api@rev{revision}", uid, f"30{revision}",
                "Deployment", "checkout-api", [_time(at, precision_ns)],
                {"revision": revision, "previous_revision": str(int(revision) - 1),
                 "changed_fields": ["spec.template.spec.containers[checkout-api].env[POOL_MAX]"],
                 "image_before": "registry.invalid/checkout-api:1", "image_after": "registry.invalid/checkout-api:1",
                 "config_refs_before": [], "config_refs_after": [],
                 "old_replicaset": "checkout-api-old", "new_replicaset": f"checkout-api-new{revision}",
                 "field_changes": [{"field": "spec.template.spec.containers[checkout-api].env[POOL_MAX]",
                                    "config_key": "pool.maxConnections", "before_value": "50", "after_value": "4",
                                    "before_value_sha256": _sha("50"), "after_value_sha256": _sha("4")}]})


def pod(revision="2", at="2026-11-12T10:02:10Z"):
    return _obs("pod", f"k8s:pod/{NS}/checkout-api-new{revision}-a", f"uid-pod-{revision}", "4001", "Pod",
                f"checkout-api-new{revision}-a", [_time(at)],
                {"owner_replicaset": f"checkout-api-new{revision}", "node": "node-1", "restart_count": 0,
                 "configmap_volumes": []})


def symptom(at="2026-11-12T10:03:00Z", revision="2", precision_ns=1_000_000_000):
    name = f"checkout-api-new{revision}-a"
    return _obs("log_line", f"loki:{{namespace={NS},pod={name}}}#0001", f"uid-pod-{revision}", "line-0001", "Pod",
                name, [_time(at, precision_ns)],
                {"pod": name, "template": "POOL_EXHAUSTED",
                 "fields": {"pool": "primary", "in_use": "4", "max": "4", "wait_ms": "5000"},
                 "message": "connection pool exhausted"})


class Fixture:
    """Builds one profile-3 bundle: acquisitions -> list of (outcome, reason, start, end, observations)."""

    def __init__(self, step=False):
        self.registry = SourceRegistry.from_record(REGISTRY_RECORD)
        self.plan_record = {
            "contract_version": pl.RUN_PLAN_VERSION, "plan_id": "ca-watch-engine-faults",
            "registry_id": self.registry.registry_id, "registry_digest": self.registry.digest,
            "window": {"start": WINDOW[0], "end": WINDOW[1]},
            "expected_acquisitions": [{"source_id": s, "query_id": q, "mandatory": True}
                                      for s, q in ACQUISITIONS.values()],
            "contract_versions": pl.required_contract_versions(ev.KIND_REGISTRY_VERSION_V3),
            "rule_versions": required_rule_versions(), "synthesis_mode": "disabled", "limits": LIMITS}
        self.plan = pl.RunPlan.from_record(self.plan_record, self.registry)
        self.clocks = [ti.clock_domain(DOMAIN, ti.UNKNOWN, continuity=ti.STEP_DECLARED if step
                                       else ti.CONTINUOUS).to_record()]
        self.rv = 1000

    def batches(self, spec):
        records = []
        for name, pieces in spec.items():
            source_id, query_id = ACQUISITIONS[name]
            before = None
            for n, (outcome, reason, start, end, observations) in enumerate(pieces, 1):
                basis, after = None, f"{name}-{n}"
                if outcome in (acq.COMPLETE, acq.EMPTY):
                    self.rv += 10
                    basis = {"kind": acq.WATCH_CONTINUITY, "resource_type": f"fixture/{name}", "session_id": "s1",
                             "clock_domain_id": DOMAIN, "rv_comparison": "k8s-1.37-decimal",
                             "start_anchor": {"kind": "list_first_page_received", "at": start,
                                              "resource_version": str(self.rv)},
                             "end_anchor": {"kind": "probe_sent", "at": end, "resource_version": str(self.rv + 5),
                                            "proven_by_resource_version": str(self.rv + 6)}}
                    after = f"rv:{self.rv + 6}"
                records.append({"contract_version": acq.BATCH_VERSION_V2, "plan_digest": self.plan.digest,
                                "source_id": source_id, "query_id": query_id, "batch_key": f"{name}-{n}",
                                "sequence": n, "outcome": outcome, "reason": reason,
                                "coverage": {"start": start, "end": end}, "cursor": {"before": before, "after": after},
                                "truncation": {"truncated": False, "reason": None, "omitted_count": None},
                                "observations": observations, "coverage_basis": basis, "delivery": {"attempt": 1}})
                before = after
        return records


def whole(observations):
    return [(acq.COMPLETE if observations else acq.EMPTY, None, WINDOW[0], WINDOW[1], observations)]


def control_spec():
    return {"deployments": whole([rollout()]), "pods": whole([pod()]), "logs": whole([symptom()])}


class EngineFaultInjection(unittest.TestCase):
    def investigate(self, spec, step=False):
        fx = Fixture(step)
        tmp = Path(tempfile.mkdtemp(prefix="ca-watch-engine-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        B.write(tmp / "bundle", "ca-watch-engine-faults", REGISTRY_RECORD, fx.plan_record, fx.clocks, fx.batches(spec))
        return C.investigate_offline(B.load(tmp / "bundle")).result["outcome"]

    def assert_abstains(self, outcome, *reasons):
        self.assertEqual(outcome["status"], "abstained")
        self.assertIsNone(outcome["hypothesis_id"])
        for reason in reasons:
            self.assertIn(reason, outcome["reasons"])

    def test_the_control_case_resolves(self):
        outcome = self.investigate(control_spec())
        self.assertEqual((outcome["status"], outcome["mechanism"]), ("resolved", "rollout_limit_reduction"))

    def test_a_rollout_in_a_gap_abstains(self):
        spec = control_spec()
        spec["deployments"] = [(acq.EMPTY, None, WINDOW[0], "2026-11-12T10:01:30.000Z", []),
                               (acq.PARTIAL, "continuity_unproven", "2026-11-12T10:01:30.000Z", WINDOW[1], [rollout()])]
        self.assert_abstains(self.investigate(spec), "limiting_evidence_gaps")

    def test_a_relist_gap_without_the_rollout_abstains(self):
        spec = control_spec()
        spec["deployments"] = [(acq.EMPTY, None, WINDOW[0], "2026-11-12T10:01:00.000Z", []),
                               (acq.EMPTY, None, "2026-11-12T10:05:00.000Z", WINDOW[1], [])]
        self.assert_abstains(self.investigate(spec), "limiting_evidence_gaps")

    def test_withheld_changes_abstain(self):
        spec = control_spec()
        spec["deployments"] = [(acq.PARTIAL, "changes_withheld", WINDOW[0], WINDOW[1], [rollout()])]
        self.assert_abstains(self.investigate(spec), "limiting_evidence_gaps")

    def test_an_event_limit_tail_abstains(self):
        spec = control_spec()
        spec["pods"] = [(acq.EMPTY, None, WINDOW[0], "2026-11-12T10:02:05.000Z", []),
                        (acq.PARTIAL, "event_limit", "2026-11-12T10:02:05.000Z", WINDOW[1], [pod()])]
        self.assert_abstains(self.investigate(spec), "limiting_evidence_gaps")

    def test_overlapping_brackets_abstain(self):
        spec = control_spec()
        spec["deployments"] = whole([rollout(at="2026-11-12T10:02:00Z", precision_ns=90_000_000_000)])
        spec["logs"] = whole([symptom(at="2026-11-12T10:03:00Z")])
        self.assert_abstains(self.investigate(spec))

    def test_a_clock_step_abstains(self):
        self.assert_abstains(self.investigate(control_spec(), step=True))

    def test_a_symptom_before_the_rollout_abstains(self):
        spec = control_spec()
        spec["logs"] = whole([symptom(at="2026-11-12T10:01:00Z")])
        self.assert_abstains(self.investigate(spec), "contradicting_evidence_present")

    def test_a_second_rollout_hidden_in_a_gap_abstains(self):
        spec = control_spec()
        spec["deployments"] = [(acq.COMPLETE, None, WINDOW[0], "2026-11-12T10:04:00.000Z", [rollout()]),
                               (acq.PARTIAL, "continuity_unproven", "2026-11-12T10:04:00.000Z", WINDOW[1],
                                [rollout(at="2026-11-12T10:05:00Z", revision="3")])]
        self.assert_abstains(self.investigate(spec), "limiting_evidence_gaps")


if __name__ == "__main__":
    unittest.main()
