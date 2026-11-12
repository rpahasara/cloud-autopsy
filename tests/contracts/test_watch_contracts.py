"""CA-P2-004f: resourceVersion comparison (F3), acquisition batch 0.2, observation kinds 0.3, profile 3.

- resourceVersions compare as arbitrary-size decimal strings (length, then lexicographic), with a
  separate 128-character input limit; checked against Python's ``int`` as a test oracle only.
- Batch 0.2: a complete or empty batch needs a coherent ``watch_continuity`` basis; anything else is
  refused. A plan pins one batch version: 0.1 batches under profile 3 and 0.2 batches under profiles
  1 and 2 are refused.
- Kinds 0.3: ``observed`` only under 0.3; a record carries the earliest version under which it is
  valid, so records without ``observed`` stay byte-identical; ``k8s_object_deleted`` only under 0.3.
"""

import copy
import random
import unittest

import _support  # noqa: F401  (adds src to the path)
from cloud_autopsy.contracts import CONTRACT_PROFILES, acquisition as acq
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import plan as pl
from cloud_autopsy.contracts import resourceversion as rv
from cloud_autopsy.contracts.errors import ContractError
from cloud_autopsy.contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry

V1, V2, V3 = ev.KIND_REGISTRY_VERSION, ev.KIND_REGISTRY_VERSION_V2, ev.KIND_REGISTRY_VERSION_V3
COLLECTOR, SERVER = "ca-collector-s1", "k8s-apiserver"
REGISTRY = SourceRegistry.from_record({
    "contract_version": SOURCE_REGISTRY_VERSION, "registry_id": "ca-watch-tests",
    "sources": [{"source_id": "k8s-api", "source_kind": "kubernetes_api", "cluster_id": "ca-kind-synthetic",
                 "namespace": "ca-demo", "clock_domain_ids": [COLLECTOR, SERVER],
                 "query_ids": ["k8s.deployments", "k8s.events", "k8s.pods", "k8s.replicasets"]}]})
LIMITS = {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 100, "max_batch_deliveries": 1000,
          "max_observations_per_batch": 100, "max_observations_total": 1000, "max_batch_bytes": 1_048_576,
          "max_total_bytes": 10_000_000}


def plan(kinds_version):
    return pl.RunPlan.from_record({
        "contract_version": pl.RUN_PLAN_VERSION, "plan_id": "watch-tests", "registry_id": REGISTRY.registry_id,
        "registry_digest": REGISTRY.digest, "window": {"start": "2026-11-12T10:00:00Z", "end": "2026-11-12T10:10:00Z"},
        "expected_acquisitions": [{"source_id": "k8s-api", "query_id": "k8s.pods", "mandatory": True}],
        "contract_versions": pl.required_contract_versions(kinds_version), "rule_versions": {},
        "synthesis_mode": "disabled", "limits": LIMITS}, REGISTRY)


P2, P3 = plan(V2), plan(V3)


def pod(observed=None, version="1205"):
    times = [{"timestamp_kind": "event", "raw": "2026-11-12T09:58:00Z", "clock_domain_id": SERVER,
              "declared_precision_ns": None}]
    if observed:
        times.append({"timestamp_kind": "observed", "raw": observed[0], "clock_domain_id": COLLECTOR,
                      "declared_precision_ns": observed[1]})
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": f"k8s:pod/ca-demo/api-1@{version}",
            "observation_kind": "pod", "source_uid": "uid-pod-1", "source_version": version,
            "entity": {"kind": "Pod", "namespace": "ca-demo", "name": "api-1"}, "times": times,
            "attributes": {"owner_replicaset": "api-7f", "node": "node-1", "restart_count": 2, "configmap_volumes": []}}


def deleted(kind="Pod", object_kind="Pod", with_time=True):
    bracket = {"raw": "2026-11-12T10:01:00.000000000Z", "clock_domain_id": COLLECTOR, "declared_precision_ns": 2_000_000}
    times = [{"timestamp_kind": "event", **bracket}, {"timestamp_kind": "observed", **bracket}] if with_time         else [{"timestamp_kind": "event", **bracket}]
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": "k8s:deleted/ca-demo/api-1@1300",
            "observation_kind": "k8s_object_deleted", "source_uid": "uid-pod-1", "source_version": "1300",
            "entity": {"kind": kind, "namespace": "ca-demo", "name": "api-1"}, "times": times,
            "attributes": {"object_kind": object_kind}}


def observe(observation, version):
    return ev.observe(observation, source_id="k8s-api", registry=REGISTRY, kind_registry_version=version)


def basis(start="2026-11-12T10:00:01.000Z", end="2026-11-12T10:00:31.000Z", start_rv="1200", probe_rv="1250",
          proven_by="1251"):
    return {"kind": "watch_continuity", "resource_type": "v1/pods", "session_id": "s1", "clock_domain_id": COLLECTOR,
            "rv_comparison": rv.RV_COMPARISON,
            "start_anchor": {"kind": "list_first_page_received", "at": start, "resource_version": start_rv},
            "end_anchor": {"kind": "probe_sent", "at": end, "resource_version": probe_rv,
                           "proven_by_resource_version": proven_by}}


def batch(outcome="complete", version=acq.BATCH_VERSION_V2, plan_=P3, observations=None, reason=None,
          coverage_basis="default", after="rv:1251", truncation=None):
    record = {"contract_version": version, "plan_digest": plan_.digest, "source_id": "k8s-api",
              "query_id": "k8s.pods", "batch_key": "pods-1", "sequence": 1, "outcome": outcome, "reason": reason,
              "coverage": {"start": "2026-11-12T10:00:01.000Z", "end": "2026-11-12T10:00:31.000Z"},
              "cursor": {"before": None, "after": after},
              "truncation": truncation or {"truncated": False, "reason": None, "omitted_count": None},
              "observations": [pod(("2026-11-12T10:00:05.000000000Z", 3_000_000))] if observations is None
              else observations, "delivery": {"attempt": 1}}
    if version == acq.BATCH_VERSION_V2:
        record["coverage_basis"] = basis() if coverage_basis == "default" else coverage_basis
    return record


def refused(test, record, plan_=P3):
    with test.assertRaises(ContractError):
        acq.decode_batch(record, plan_, REGISTRY)


class ResourceVersionComparison(unittest.TestCase):
    def test_valid_values(self):
        for value in ("1", "9", "10", "1205", "9" * 25, "1" + "0" * 44, "7" * rv.MAX_RV_CHARS):
            self.assertTrue(rv.is_valid(value), value[:8])

    def test_invalid_values_are_refused(self):
        for value, code in (("", "rv_missing"), (None, "rv_missing"), (12, "rv_missing"), ("0", "rv_not_decimal"),
                            ("012", "rv_not_decimal"), ("-5", "rv_not_decimal"), ("+5", "rv_not_decimal"),
                            (" 5", "rv_not_decimal"), ("5 ", "rv_not_decimal"), ("1e3", "rv_not_decimal"),
                            ("12.5", "rv_not_decimal"), ("\u0661\u0662", "rv_not_decimal"),
                            ("1" * (rv.MAX_RV_CHARS + 1), "rv_too_long")):
            with self.subTest(value=repr(value)[:12]), self.assertRaises(rv.ResourceVersionError) as ctx:
                rv.check(value)
            self.assertEqual(ctx.exception.code, code)

    def test_length_then_lexicographic_order(self):
        self.assertEqual(rv.compare("9", "10"), -1)
        self.assertEqual(rv.compare("10", "9"), 1)
        self.assertEqual(rv.compare("1205", "1205"), 0)
        self.assertEqual(rv.compare("1205", "1250"), -1)
        self.assertEqual(rv.compare("9" * 21, "1" + "0" * 21), -1)   # beyond 64 bits: no width assumption
        self.assertEqual(rv.compare("5" * 41, "5" * 40 + "6"), -1)
        self.assertTrue(rv.at_least("1251", "1250"))
        self.assertTrue(rv.at_least("1250", "1250"))
        self.assertFalse(rv.at_least("999", "1000"))

    def test_comparison_matches_arbitrary_precision_integers(self):
        rng = random.Random(4_004_020)
        for _ in range(20_000):
            a = str(rng.randrange(1, 10 ** rng.randrange(1, 60)))
            b = str(int(a) + rng.choice((-1, 0, 1, rng.randrange(-10 ** 30, 10 ** 30))) if rng.random() < 0.5
                    else rng.randrange(1, 10 ** rng.randrange(1, 60)))
            if not rv.is_valid(b):
                continue
            self.assertEqual(rv.compare(a, b), (int(a) > int(b)) - (int(a) < int(b)))

    def test_invalid_operands_are_refused_by_compare(self):
        for a, b in (("10", "010"), ("1" * 129, "1"), ("x", "1")):
            with self.assertRaises(rv.ResourceVersionError):
                rv.compare(a, b)


class BatchV2(unittest.TestCase):
    def test_a_coherent_complete_batch_decodes_with_its_basis(self):
        decoded = acq.decode_batch(batch(), P3, REGISTRY)
        self.assertEqual(decoded.outcome, acq.COMPLETE)
        self.assertEqual(decoded.coverage_basis, basis())
        self.assertEqual(decoded.evidence[0].kind_registry_version, V3)

    def test_an_empty_batch_also_needs_a_basis(self):
        acq.decode_batch(batch("empty", observations=[]), P3, REGISTRY)
        refused(self, batch("empty", observations=[], coverage_basis=None))

    def test_versions_are_pinned_by_the_plan(self):
        refused(self, batch(), P2)                                         # 0.2 batch under profile 2
        refused(self, {k: v for k, v in batch(version=acq.BATCH_VERSION).items()}, P3)  # 0.1 batch under profile 3
        old = batch(version=acq.BATCH_VERSION, plan_=P2, observations=[pod()], after="pods-c1")
        self.assertIsNone(acq.decode_batch(old, P2, REGISTRY).coverage_basis)  # 0.1 is unchanged

    def test_complete_or_empty_without_a_valid_basis_is_refused(self):
        refused(self, batch(coverage_basis=None))
        for path, value in ((("kind",), "declared"), (("rv_comparison",), "opaque"), (("session_id",), "S 1"),
                            (("resource_type",), "Pods!"), (("start_anchor", "kind"), "list_sent"),
                            (("end_anchor", "kind"), "bookmark"),
                            (("start_anchor", "at"), "2026-11-12T10:00:00.000Z"),     # wider than the anchors
                            (("end_anchor", "at"), "2026-11-12T10:00:40.000Z"),
                            (("start_anchor", "resource_version"), "1300"),        # start above the probe
                            (("end_anchor", "proven_by_resource_version"), "1249"),  # not reached
                            (("end_anchor", "resource_version"), "01250"),
                            (("start_anchor", "resource_version"), "1" * 129)):
            doc = basis()
            target = doc
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                refused(self, batch(coverage_basis=doc))
        extra = basis()
        extra["note"] = "x"
        refused(self, batch(coverage_basis=extra))

    def test_cursor_must_name_the_proving_resource_version(self):
        refused(self, batch(after="rv:1250"))
        refused(self, batch(after="pods-c1"))

    def test_partial_failed_and_denied_carry_no_basis(self):
        acq.decode_batch(batch("partial", reason="continuity_unproven", coverage_basis=None, after="pods-c1"), P3, REGISTRY)
        refused(self, batch("partial", reason="continuity_unproven", after="rv:1251"))
        failed = batch("failed", reason="source_unavailable", observations=[], coverage_basis=None, after="pods-c1")
        failed["coverage"] = None
        acq.decode_batch(failed, P3, REGISTRY)

    def test_new_partial_and_truncation_reasons_exist_only_in_0_2(self):
        for reason in ("continuity_unproven", "event_limit", "changes_withheld"):
            acq.decode_batch(batch("partial", reason=reason, coverage_basis=None, after="pods-c1"), P3, REGISTRY)
            refused(self, batch("partial", reason=reason, version=acq.BATCH_VERSION, plan_=P2,
                                observations=[pod()], after="pods-c1"), P2)
        limited = batch("partial", reason="event_limit", coverage_basis=None, after="pods-c1",
                        truncation={"truncated": True, "reason": "event_limit", "omitted_count": None})
        acq.decode_batch(limited, P3, REGISTRY)


class KindsV3(unittest.TestCase):
    def test_observed_is_allowed_only_under_0_3_and_labels_the_record_0_3(self):
        e = observe(pod(("2026-11-12T10:00:05.000000000Z", 3_000_000)), V3)
        self.assertEqual(e.kind_registry_version, V3)
        self.assertEqual(ev.ObservedEvidence.from_record(e.to_record(), REGISTRY, V3), e)
        for version in (V1, V2):
            with self.assertRaises(ContractError):
                observe(pod(("2026-11-12T10:00:05.000000000Z", 3_000_000)), version)
            with self.assertRaises(ContractError):  # a stored 0.3 record is never read under 0.1 or 0.2
                ev.ObservedEvidence.from_record(e.to_record(), REGISTRY, version)

    def test_records_without_observed_are_byte_identical_and_keep_their_label(self):
        under_v1, under_v3 = observe(pod(), V1), observe(pod(), V3)
        self.assertEqual(under_v3.kind_registry_version, V1)
        self.assertEqual(under_v1.to_record(), under_v3.to_record())

    def test_a_relabelled_record_is_refused(self):
        record = observe(pod(("2026-11-12T10:00:05.000000000Z", 3_000_000)), V3).to_record()
        forged = copy.deepcopy(record)
        forged["kind_registry_version"] = V1
        with self.assertRaises(ContractError):
            ev.ObservedEvidence.from_record(forged, REGISTRY, V3)

    def test_deletions_are_a_0_3_kind(self):
        for kind in ev.DELETED_OBJECT_KINDS:
            e = observe(deleted(kind, kind), V3)
            self.assertEqual((e.observation_kind, e.kind_registry_version), ("k8s_object_deleted", V3))
        for version in (V1, V2):
            with self.assertRaises(ContractError):
                observe(deleted(), version)
        for bad in (deleted("Pod", "Event"), deleted("Service", "Pod"), deleted(with_time=False)):
            with self.assertRaises(ContractError):
                observe(bad, V3)

    def test_profile_3_pins_batch_0_2_and_kinds_0_3(self):
        self.assertEqual(pl.required_contract_versions(V3), CONTRACT_PROFILES[2])
        self.assertEqual(acq.plan_batch_version(P3), acq.BATCH_VERSION_V2)
        self.assertEqual(acq.plan_batch_version(P2), acq.BATCH_VERSION)
        self.assertEqual(P3.kind_registry_version, V3)


if __name__ == "__main__":
    unittest.main()
