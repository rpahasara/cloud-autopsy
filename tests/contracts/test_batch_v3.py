"""CA-P2-002e (M11): acquisition batch 0.3 and the ``log_sequence_continuity`` coverage basis.

- A complete or empty log batch needs a coherent log basis: the Pod watch anchors it rests on, its session
  clock, and every container instance it claims (pod UID, container, boot, last seq, verified ending).
- Its observations must be log lines of listed instances within their proven sequence; nothing else.
- Under 0.3 a ``watch_continuity`` batch may hold no log line: log continuity never stands in for Pod or
  Deployment watch continuity, and watch continuity never covers logs.
- Batches 0.1 and 0.2 are unchanged: 0.2 refuses the log basis, and a plan pins exactly one version.
"""

import copy
import unittest

import _support  # noqa: F401  (adds src to the path)
from cloud_autopsy.contracts import acquisition as acq
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import plan as pl
from cloud_autopsy.contracts import resourceversion as rv
from cloud_autopsy.contracts.errors import ContractError
from cloud_autopsy.contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry

SESSION = "cs-0123456789abcdef"
COLLECTOR, RUNTIME, SERVER = f"ca-collector-{SESSION}", "k8s-container-runtime", "k8s-apiserver"
UID = "6f1c2a7e-0000-4000-8000-000000000001"
REGISTRY = SourceRegistry.from_record({
    "contract_version": SOURCE_REGISTRY_VERSION, "registry_id": "ca-batch-v3-tests",
    "sources": [{"source_id": "k8s-api", "source_kind": "kubernetes_api", "cluster_id": "ca-kind-synthetic",
                 "namespace": "ca-incident", "clock_domain_ids": sorted([COLLECTOR, RUNTIME, SERVER]),
                 "query_ids": ["k8s.pods", "k8s.pods.log"]}]})
LIMITS = {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 100, "max_batch_deliveries": 1000,
          "max_observations_per_batch": 100, "max_observations_total": 1000, "max_batch_bytes": 1_048_576,
          "max_total_bytes": 10_000_000}


def plan(kinds):
    return pl.RunPlan.from_record({
        "contract_version": pl.RUN_PLAN_VERSION, "plan_id": "batch-v3-tests", "registry_id": REGISTRY.registry_id,
        "registry_digest": REGISTRY.digest, "window": {"start": "2026-11-13T10:00:00Z", "end": "2026-11-13T10:10:00Z"},
        "expected_acquisitions": [{"source_id": "k8s-api", "query_id": q, "mandatory": True}
                                  for q in ("k8s.pods", "k8s.pods.log")],
        "contract_versions": pl.required_contract_versions(kinds), "rule_versions": {},
        "synthesis_mode": "disabled", "limits": LIMITS}, REGISTRY)


P3, P4 = plan(ev.KIND_REGISTRY_VERSION_V3), plan(ev.KIND_REGISTRY_VERSION_V4)


def line(seq=7, uid=UID, boot="0a1b2c3d", container="checkout-api"):
    return {"contract_version": ev.OBSERVATION_VERSION,
            "source_ref": f"k8s:pods/log/ca-incident/checkout-api-1/{container}#{boot}.{seq}",
            "observation_kind": "log_line", "source_uid": uid, "source_version": f"{boot}.{seq}",
            "entity": {"kind": "Pod", "namespace": "ca-incident", "name": "checkout-api-1"},
            "times": [{"timestamp_kind": "event", "raw": "2026-11-13T10:00:06.5Z", "clock_domain_id": RUNTIME,
                       "declared_precision_ns": None},
                      {"timestamp_kind": "observed", "raw": "2026-11-13T10:00:05.000000000Z",
                       "clock_domain_id": COLLECTOR, "declared_precision_ns": 2_000_000_000}],
            "attributes": {"pod": "checkout-api-1", "template": "POOL_EXHAUSTED",
                           "fields": {"pool": "checkout-db", "in_use": "8", "max": "4"},
                           "container": container, "boot": boot, "seq": seq}}


def pod():
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": "k8s:pod/ca-incident/checkout-api-1@1205",
            "observation_kind": "pod", "source_uid": UID, "source_version": "1205",
            "entity": {"kind": "Pod", "namespace": "ca-incident", "name": "checkout-api-1"},
            "times": [{"timestamp_kind": "event", "raw": "2026-11-13T09:58:00Z", "clock_domain_id": SERVER,
                       "declared_precision_ns": None}],
            "attributes": {"owner_replicaset": "api-7f", "node": "node-1", "restart_count": 0, "configmap_volumes": []}}


def instance(**changes):
    return {"pod_uid": UID, "container": "checkout-api", "boot": "0a1b2c3d", "last_seq": 40, "ending": "stopped",
            **changes}


def log_basis(instances=None, **changes):
    return {"kind": acq.LOG_SEQUENCE_CONTINUITY, "resource_type": acq.LOG_RESOURCE_TYPE, "session_id": SESSION,
            "clock_domain_id": COLLECTOR, "rv_comparison": rv.RV_COMPARISON,
            "start_anchor": {"kind": "list_first_page_received", "at": "2026-11-13T10:00:01.000Z",
                             "resource_version": "1200"},
            "end_anchor": {"kind": "probe_sent", "at": "2026-11-13T10:00:31.000Z", "resource_version": "1250",
                           "proven_by_resource_version": "1251"},
            "instances": [instance()] if instances is None else instances, **changes}


def batch(observations=None, basis="default", outcome="complete", version=acq.BATCH_VERSION_V3, plan_=P4,
          query="k8s.pods.log", reason=None, after="rv:1251"):
    record = {"contract_version": version, "plan_digest": plan_.digest, "source_id": "k8s-api", "query_id": query,
              "batch_key": "log-1", "sequence": 1, "outcome": outcome, "reason": reason,
              "coverage": {"start": "2026-11-13T10:00:01.000Z", "end": "2026-11-13T10:00:31.000Z"},
              "cursor": {"before": None, "after": after},
              "truncation": {"truncated": False, "reason": None, "omitted_count": None},
              "observations": [line()] if observations is None else observations, "delivery": {"attempt": 1},
              "coverage_basis": log_basis() if basis == "default" else basis}
    return record


class LogBasis(unittest.TestCase):
    def refused(self, record, plan_=P4):
        with self.assertRaises(ContractError):
            acq.decode_batch(record, plan_, REGISTRY)

    def test_a_coherent_log_batch_is_complete_and_an_empty_one_is_empty(self):
        decoded = acq.decode_batch(batch(), P4, REGISTRY)
        self.assertEqual((decoded.outcome, decoded.coverage_basis["kind"]), ("complete", acq.LOG_SEQUENCE_CONTINUITY))
        self.assertEqual(decoded.evidence[0].kind_registry_version, ev.KIND_REGISTRY_VERSION_V4)
        empty = acq.decode_batch(batch(observations=[], outcome="empty", basis=log_basis(instances=[])), P4, REGISTRY)
        self.assertEqual(empty.outcome, "empty")
        drained = batch(basis=log_basis(instances=[instance(ending="drained")]))
        self.assertEqual(acq.decode_batch(drained, P4, REGISTRY).outcome, "complete")

    def test_the_basis_shape_and_bindings_are_exact(self):
        for name, bad in (
                ("extra field", log_basis(extra=1)),
                ("missing instances", {k: v for k, v in log_basis().items() if k != "instances"}),
                ("other resource type", log_basis(resource_type="v1/pods")),
                ("another session's clock", log_basis(clock_domain_id="ca-collector-cs-ffffffffffffffff")),
                ("anchor kind", log_basis(start_anchor={"kind": "probe_sent", "at": "2026-11-13T10:00:01.000Z",
                                                         "resource_version": "1200"})),
                ("coverage not the anchors", log_basis(end_anchor={"kind": "probe_sent",
                                                                   "at": "2026-11-13T10:00:30.000Z",
                                                                   "resource_version": "1250",
                                                                   "proven_by_resource_version": "1251"})),
                ("unproven probe", log_basis(end_anchor={"kind": "probe_sent", "at": "2026-11-13T10:00:31.000Z",
                                                         "resource_version": "1250",
                                                         "proven_by_resource_version": "1249"})),
                ("rv comparison", log_basis(rv_comparison="lexicographic")),
                ("unknown ending", log_basis(instances=[instance(ending="eof")])),
                ("zero last_seq", log_basis(instances=[instance(last_seq=0)])),
                ("string last_seq", log_basis(instances=[instance(last_seq="40")])),
                ("bad boot", log_basis(instances=[instance(boot="0A1B2C3D")])),
                ("bad container", log_basis(instances=[instance(container="Checkout")])),
                ("instance extra field", log_basis(instances=[{**instance(), "first_seq": 1}])),
                ("duplicate instance", log_basis(instances=[instance(), instance()])),
                ("unsorted instances", log_basis(instances=[instance(boot="ffffffff"), instance()]))):
            with self.subTest(case=name):
                self.refused(batch(basis=bad))
        self.refused(batch(after="rv:1250"))

    def test_lines_must_belong_to_a_listed_instance_within_its_proven_sequence(self):
        for name, obs in (("another pod", line(uid="6f1c2a7e-0000-4000-8000-000000000002")),
                          ("another boot", line(boot="ffffffff")),
                          ("another container", line(container="sidecar")),
                          ("beyond last_seq", line(seq=41))):
            with self.subTest(case=name):
                self.refused(batch(observations=[obs]))
        self.refused(batch(observations=[line(), pod()]))   # a Pod record is never covered by log continuity

    def test_log_continuity_never_implies_watch_continuity(self):
        watch = {**{k: v for k, v in log_basis().items() if k != "instances"}, "kind": acq.WATCH_CONTINUITY,
                 "resource_type": "v1/pods"}
        self.assertEqual(acq.decode_batch(batch(observations=[pod()], basis=watch, query="k8s.pods"), P4,
                                          REGISTRY).outcome, "complete")
        self.refused(batch(observations=[line()], basis=watch))                  # logs under a watch basis
        self.refused(batch(observations=[pod()], basis=log_basis()))             # a pod under a log basis
        self.refused(batch(observations=[line()], basis=watch, query="k8s.pods"))

    def test_partial_failed_and_denied_carry_no_basis(self):
        self.assertEqual(acq.decode_batch(batch(outcome="partial", reason="continuity_unproven", basis=None),
                                          P4, REGISTRY).outcome, "partial")
        self.refused(batch(outcome="partial", reason="continuity_unproven"))     # a basis on a partial batch
        self.refused(batch(basis=None))                                          # complete without a basis

    def test_coverage_may_be_a_sub_interval_of_the_proven_anchors_but_never_beyond(self):
        """M12d: under 0.3 the claimed coverage lies inside the proof; the anchors still state the whole proof."""
        def with_coverage(start, end, basis=None, observations=None, query="k8s.pods.log"):
            record = batch(basis=basis or log_basis(), observations=observations, query=query)
            record["coverage"] = {"start": start, "end": end}
            return record
        inside = with_coverage("2026-11-13T10:00:05.000Z", "2026-11-13T10:00:25.000Z")
        decoded = acq.decode_batch(inside, P4, REGISTRY)
        self.assertEqual(decoded.coverage_ms[1] - decoded.coverage_ms[0], 20_000)
        self.assertEqual(decoded.coverage_basis["end_anchor"]["at"], "2026-11-13T10:00:31.000Z")  # proof intact
        for start, end in (("2026-11-13T10:00:00.999Z", "2026-11-13T10:00:25.000Z"),   # before the start anchor
                           ("2026-11-13T10:00:05.000Z", "2026-11-13T10:00:31.001Z"),   # beyond the end anchor
                           ("2026-11-13T10:00:00.000Z", "2026-11-13T10:00:40.000Z"),   # both
                           ("2026-11-13T10:00:05.000Z", "2026-11-13T10:00:05.000Z")):  # empty
            with self.subTest(start=start, end=end):
                self.refused(with_coverage(start, end))
        watch = {**{k: v for k, v in log_basis().items() if k != "instances"}, "kind": acq.WATCH_CONTINUITY,
                 "resource_type": "v1/pods"}
        self.assertEqual(acq.decode_batch(with_coverage("2026-11-13T10:00:02.000Z", "2026-11-13T10:00:30.000Z",
                                                        basis=watch, observations=[pod()], query="k8s.pods"),
                                          P4, REGISTRY).outcome, "complete")
        self.refused(with_coverage("2026-11-13T10:00:02.000Z", "2026-11-13T10:00:32.000Z", basis=watch,
                                   observations=[pod()], query="k8s.pods"))

    def test_batch_0_2_still_needs_coverage_exactly_equal_to_its_anchors(self):
        from test_watch_contracts import P3 as WP3, REGISTRY as WREG, basis as wbasis, batch as wbatch
        record = wbatch()
        acq.decode_batch(record, WP3, WREG)
        record["coverage"] = {"start": "2026-11-12T10:00:02.000Z", "end": "2026-11-12T10:00:30.000Z"}
        with self.assertRaises(ContractError):
            acq.decode_batch(record, WP3, WREG)
        self.assertEqual(wbasis()["kind"], "watch_continuity")

    def test_versions_do_not_mix(self):
        self.refused(batch(version=acq.BATCH_VERSION_V2))                        # a 0.2 batch under profile 4
        self.refused(batch(), P3)                                                # a 0.3 batch under profile 3
        record = copy.deepcopy(batch(version=acq.BATCH_VERSION_V2, plan_=P3))
        self.refused(record, P3)                                                 # 0.2 has no log basis kind


if __name__ == "__main__":
    unittest.main()
