"""CA-P2-002e: observation kinds 0.4 (pod logs read through the Kubernetes API) and contract profile 4.

- 0.4 is 0.3 plus a widened ``log_line``: it may come from a ``kubernetes_api`` source, may carry an
  ``observed`` bracket, may omit ``message`` and may carry the sequence envelope (container, boot, seq).
- A Kubernetes API log line must carry the whole envelope and must never carry free text.
- A 0.1-shaped ``loki`` line keeps its 0.1 label and its bytes under a 0.4 plan; every 0.4-only shape is
  labelled 0.4 and refused under 0.1-0.3, including a forged relabel.
- Profile 4 pins kinds 0.4 with acquisition batch 0.3 (M11); profiles 1-3 are unchanged.
"""

import copy
import unittest

import _support  # noqa: F401  (adds src to the path)
from cloud_autopsy.contracts import ADDITIONAL_CONTRACT_VERSIONS, CONTRACT_PROFILES, acquisition as acq
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import plan as pl
from cloud_autopsy.contracts.errors import ContractError
from cloud_autopsy.contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry

V1, V2, V3, V4 = (ev.KIND_REGISTRY_VERSION, ev.KIND_REGISTRY_VERSION_V2, ev.KIND_REGISTRY_VERSION_V3,
                  ev.KIND_REGISTRY_VERSION_V4)
COLLECTOR, RUNTIME = "ca-collector-cs-0123456789abcdef", "k8s-container-runtime"
REGISTRY = SourceRegistry.from_record({
    "contract_version": SOURCE_REGISTRY_VERSION, "registry_id": "ca-kinds-v4-tests",
    "sources": [{"source_id": "k8s-api", "source_kind": "kubernetes_api", "cluster_id": "ca-kind-synthetic",
                 "namespace": "ca-incident", "clock_domain_ids": [COLLECTOR, RUNTIME],
                 "query_ids": ["k8s.pods", "k8s.pods.log"]},
                {"source_id": "loki", "source_kind": "loki", "cluster_id": "ca-kind-synthetic",
                 "namespace": "ca-incident", "clock_domain_ids": ["node-a"], "query_ids": ["loki.checkout-api"]},
                {"source_id": "prometheus", "source_kind": "prometheus", "cluster_id": "ca-kind-synthetic",
                 "namespace": "ca-incident", "clock_domain_ids": ["prom"], "query_ids": ["prom.alerts"]}]})


def k8s_line(seq=7, observed=("2026-11-13T10:00:05.000000000Z", 2_500_000_000), **changes):
    times = [{"timestamp_kind": "event", "raw": "2026-11-13T10:00:06.123456789Z", "clock_domain_id": RUNTIME,
              "declared_precision_ns": None}]
    if observed:
        times.append({"timestamp_kind": "observed", "raw": observed[0], "clock_domain_id": COLLECTOR,
                      "declared_precision_ns": observed[1]})
    attributes = {"pod": "checkout-api-7d9-abcde", "template": "POOL_EXHAUSTED",
                  "fields": {"pool": "checkout-db", "in_use": "8", "max": "4"},
                  "container": "checkout-api", "boot": "0a1b2c3d", "seq": seq}
    attributes.update(changes)
    for key in [k for k, v in attributes.items() if v is None]:
        del attributes[key]
    return {"contract_version": ev.OBSERVATION_VERSION,
            "source_ref": f"k8s:pods/log/ca-incident/checkout-api-7d9-abcde/checkout-api#0a1b2c3d.{seq}",
            "observation_kind": "log_line", "source_uid": "6f1c2a7e-0000-4000-8000-000000000001",
            "source_version": f"0a1b2c3d.{seq}", "entity": {"kind": "Pod", "namespace": "ca-incident",
                                                             "name": "checkout-api-7d9-abcde"},
            "times": times, "attributes": attributes}


def loki_line(**changes):
    attributes = {"pod": "api-1", "template": "POOL_EXHAUSTED", "fields": {"pool": "primary"},
                  "message": "pool exhausted"}
    attributes.update(changes)
    for key in [k for k, v in attributes.items() if v is None]:
        del attributes[key]
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": "loki:{namespace=ca-incident,pod=api-1}#0001",
            "observation_kind": "log_line", "source_uid": "uid-pod-api-1", "source_version": "line-0001",
            "entity": {"kind": "Pod", "namespace": "ca-incident", "name": "api-1"},
            "times": [{"timestamp_kind": "event", "raw": "2026-11-13T10:00:06Z", "clock_domain_id": "node-a",
                       "declared_precision_ns": None}], "attributes": attributes}


def observe(observation, version, source_id="k8s-api"):
    return ev.observe(observation, source_id=source_id, registry=REGISTRY, kind_registry_version=version)


class KindsV4(unittest.TestCase):
    def test_a_kubernetes_api_log_line_is_a_0_4_record(self):
        e = observe(k8s_line(), V4)
        self.assertEqual((e.observation_kind, e.kind_registry_version, e.evidence_class), ("log_line", V4, "LOG"))
        self.assertEqual({t.timestamp_kind for t in e.times}, {"event", "observed"})
        self.assertNotIn("message", e.attributes)
        self.assertEqual(ev.ObservedEvidence.from_record(e.to_record(), REGISTRY, V4), e)
        without_observed = observe(k8s_line(observed=None), V4)
        self.assertEqual(without_observed.kind_registry_version, V4)

    def test_it_is_refused_under_every_earlier_version_and_cannot_be_relabelled(self):
        record = observe(k8s_line(), V4).to_record()
        for version in (V1, V2, V3):
            with self.assertRaises(ContractError):
                observe(k8s_line(), version)
            with self.assertRaises(ContractError):
                ev.ObservedEvidence.from_record(record, REGISTRY, version)
        for label in (V1, V2, V3):
            forged = copy.deepcopy(record)
            forged["kind_registry_version"] = label
            with self.assertRaises(ContractError):
                ev.ObservedEvidence.from_record(forged, REGISTRY, V4)

    def test_free_text_is_never_accepted_from_the_kubernetes_api(self):
        with self.assertRaises(ContractError):
            observe(k8s_line(message="password=hunter2"), V4)

    def test_the_whole_envelope_is_required_from_the_kubernetes_api(self):
        for missing in ("container", "boot", "seq"):
            with self.assertRaises(ContractError, msg=missing):
                observe(k8s_line(**{missing: None}), V4)
        for bad in ({"boot": "0A1B2C3D"}, {"boot": "0a1b2c3"}, {"seq": 0}, {"seq": "7"}, {"seq": True},
                    {"container": "Checkout"}, {"fields": {"password": "x"}}, {"fields": {"in_use": "a\nb"}}):
            with self.assertRaises(ContractError, msg=str(bad)):
                observe(k8s_line(**bad), V4)

    def test_a_0_1_shaped_loki_line_keeps_its_label_and_bytes(self):
        under_v1, under_v4 = observe(loki_line(), V1, "loki"), observe(loki_line(), V4, "loki")
        self.assertEqual(under_v4.kind_registry_version, V1)
        self.assertEqual(under_v1.to_record(), under_v4.to_record())

    def test_loki_lines_still_need_their_message_and_a_partial_envelope_is_refused(self):
        with self.assertRaises(ContractError):
            observe(loki_line(message=None), V4, "loki")
        with self.assertRaises(ContractError):
            observe(loki_line(boot="0a1b2c3d"), V4, "loki")
        enveloped = observe(loki_line(container="api", boot="0a1b2c3d", seq=1), V4, "loki")
        self.assertEqual(enveloped.kind_registry_version, V4)

    def test_log_lines_still_cannot_come_from_prometheus(self):
        with self.assertRaises(ContractError):
            observe(k8s_line(), V4, "prometheus")

    def test_other_kinds_are_unchanged_under_0_4(self):
        for kind in ev.KINDS_ADDED_IN_V3:
            self.assertIs(ev.kinds_for(V4)[kind], ev.kinds_for(V3)[kind])
        for kind, spec in ev.kinds_for(V3).items():
            if kind != "log_line":
                self.assertIs(ev.kinds_for(V4)[kind], spec)
        self.assertIs(ev.kinds_for(V3)["log_line"], ev.KINDS["log_line"])  # 0.1-0.3 are untouched


class Profile4(unittest.TestCase):
    def test_profile_4_pins_kinds_0_4_with_batch_0_3(self):
        profile = pl.required_contract_versions(V4)
        self.assertEqual(profile, CONTRACT_PROFILES[3])
        self.assertEqual(profile["observation-kinds"], V4)
        self.assertEqual(profile["acquisition-batch"], acq.BATCH_VERSION_V3)  # M11
        drop = ("observation-kinds", "acquisition-batch")
        self.assertEqual({k: v for k, v in profile.items() if k not in drop},
                         {k: v for k, v in CONTRACT_PROFILES[2].items() if k not in drop})
        self.assertIn(acq.BATCH_VERSION_V3, ADDITIONAL_CONTRACT_VERSIONS["acquisition-batch"])
        self.assertIn(V4, ADDITIONAL_CONTRACT_VERSIONS["observation-kinds"])

    def test_profiles_1_to_3_are_unchanged(self):
        self.assertEqual([p["observation-kinds"] for p in CONTRACT_PROFILES[:3]], [V1, V2, V3])
        self.assertEqual(CONTRACT_PROFILES[2]["acquisition-batch"], acq.BATCH_VERSION_V2)


if __name__ == "__main__":
    unittest.main()
