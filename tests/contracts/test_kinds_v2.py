"""CA-P2-004d: observation kinds 0.2 (``k8s_event``, ``configmap_metadata``) and version separation.

- The vectors' expected IDs and digests were computed by an independent Node.js implementation.
- 0.1 is unchanged: the same kinds, the same default, byte-identical records.
- A 0.1 kind is byte-identical under a 0.1 or a 0.2 plan; a 0.2 kind is refused under 0.1.
- A record never claims a registry version other than the one that introduced its kind.
- Plans pin exactly one whole contract profile; anything else is refused.
"""

import copy
import json
import unittest
from pathlib import Path

import _evidence_support as S  # noqa: F401  (puts src on the path, as the other contract tests do)
from cloud_autopsy.contracts import CONTRACT_PROFILES, CONTRACT_VERSIONS, canonical
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import plan as pl
from cloud_autopsy.contracts.errors import ContractError
from cloud_autopsy.contracts.sources import SourceRegistry

VECTORS = json.loads((Path(ev.__file__).parent / "vectors" / "ca-observation-kinds-0.2-provisional.json")
                     .read_text(encoding="utf-8"))
V1, V2 = ev.KIND_REGISTRY_VERSION, ev.KIND_REGISTRY_VERSION_V2
REGISTRY = SourceRegistry.from_record(VECTORS["registry"])


def observe(name, version=V2, observation=None):
    entry = VECTORS["observations"][name]
    return ev.observe(observation or entry["observation"], source_id=entry["source_id"], registry=REGISTRY,
                      kind_registry_version=version)


def setp(doc, path, value):
    for key in path[:-1]:
        doc = doc[key]
    doc[path[-1]] = value


class VectorTests(unittest.TestCase):
    def test_expected_ids_and_digests_match_the_independent_implementation(self):
        for name, expected in VECTORS["expected"].items():
            with self.subTest(vector=name):
                e = observe(name)
                self.assertEqual((e.evidence_id, e.content_digest), (expected["evidence_id"], expected["content_digest"]))
                self.assertEqual(e.kind_registry_version, V2)
                self.assertEqual(ev.ObservedEvidence.from_record(e.to_record(), REGISTRY, V2), e)

    def test_relations(self):
        for rel in VECTORS["relations"]:
            with self.subTest(relation=rel["id"]):
                a, b = observe(rel["a"]), observe(rel["b"])
                self.assertEqual(a.evidence_id == b.evidence_id, rel["same_evidence_id"])
                self.assertEqual(a.content_digest == b.content_digest, rel["same_content_digest"])

    def test_invalid_records_are_refused_with_their_code(self):
        for case in VECTORS["invalid"]:
            with self.subTest(case=case["id"]):
                doc = copy.deepcopy(VECTORS["observations"][case["base"]]["observation"])
                for path, value in case["set"]:
                    setp(doc, path, value)
                with self.assertRaises(ContractError) as ctx:
                    observe(case["base"], observation=doc)
                self.assertEqual(ctx.exception.code, case["error"])

    def test_new_kinds_are_refused_under_0_1(self):
        for name in VECTORS["unsupported_under_0_1"]:
            with self.subTest(vector=name), self.assertRaises(ContractError) as ctx:
                observe(name, V1)
            self.assertEqual(ctx.exception.code, "observation_kind_unsupported")
            record = observe(name).to_record()
            with self.assertRaises(ContractError):  # a stored 0.2 record is never read under a 0.1 plan
                ev.ObservedEvidence.from_record(record, REGISTRY, V1)


class VersionSeparationTests(unittest.TestCase):
    def test_0_1_is_unchanged(self):
        self.assertEqual(CONTRACT_VERSIONS["observation-kinds"], V1)
        self.assertEqual(pl.required_contract_versions(), CONTRACT_VERSIONS)
        self.assertEqual(sorted(ev.KINDS), ["alert_firing", "configmap_change", "deployment_rollout", "log_line",
                                             "metric_sample", "pod", "replicaset"])
        self.assertEqual(set(ev.KIND_REGISTRIES[V2]) - set(ev.KINDS), {"k8s_event", "configmap_metadata"})
        for kind, spec in ev.KINDS.items():
            self.assertIs(ev.KIND_REGISTRIES[V2][kind], spec)  # 0.1 kinds are the same objects in 0.2
            self.assertEqual(spec.since, V1)

    def test_a_0_1_kind_is_byte_identical_under_either_registry(self):
        vectors = json.loads((Path(ev.__file__).parent / "vectors" / "ca-evidence-0.1-provisional.json").read_text())
        reg = SourceRegistry.from_record(vectors["registry"])
        for name, entry in vectors["observations"].items():
            with self.subTest(vector=name):
                old = ev.observe(entry["observation"], source_id=entry["source_id"], registry=reg)
                new = ev.observe(entry["observation"], source_id=entry["source_id"], registry=reg,
                                 kind_registry_version=V2)
                self.assertEqual(canonical.canonical_bytes(old.to_record()), canonical.canonical_bytes(new.to_record()))
                self.assertEqual(old.kind_registry_version, V1)
                self.assertEqual(ev.ObservedEvidence.from_record(old.to_record(), reg, V2), old)

    def test_a_record_cannot_claim_another_registry_version(self):
        record = observe("event").to_record()
        record["kind_registry_version"] = V1
        with self.assertRaises(ContractError):
            ev.ObservedEvidence.from_record(record, REGISTRY, V2)
        vectors = json.loads((Path(ev.__file__).parent / "vectors" / "ca-evidence-0.1-provisional.json").read_text())
        reg = SourceRegistry.from_record(vectors["registry"])
        entry = next(iter(vectors["observations"].values()))
        old = ev.observe(entry["observation"], source_id=entry["source_id"], registry=reg).to_record()
        old["kind_registry_version"] = V2  # an old record re-labelled as 0.2 is refused, not reinterpreted
        with self.assertRaises(ContractError):
            ev.ObservedEvidence.from_record(old, reg, V2)

    def test_unknown_registry_versions_are_refused(self):
        # 0.3 exists since CA-P2-004f; 0.4 is still unknown.
        with self.assertRaises(ContractError):
            observe("event", "ca-observation-kinds/0.4-provisional")
        with self.assertRaises(ContractError):
            pl.required_contract_versions("ca-observation-kinds/0.4-provisional")

    def test_plans_pin_exactly_one_whole_profile(self):
        # CA-P2-004f appended profile 3 (batch 0.2 and kinds 0.3); profiles 1 and 2 are unchanged.
        self.assertEqual(len(CONTRACT_PROFILES), 3)
        diff = {k for k in CONTRACT_PROFILES[0] if CONTRACT_PROFILES[0][k] != CONTRACT_PROFILES[1][k]}
        self.assertEqual(diff, {"observation-kinds"})
        diff3 = {k for k in CONTRACT_PROFILES[1] if CONTRACT_PROFILES[1][k] != CONTRACT_PROFILES[2][k]}
        self.assertEqual(diff3, {"observation-kinds", "acquisition-batch"})
        vectors = json.loads((Path(ev.__file__).parent / "vectors" / "ca-evidence-0.1-provisional.json").read_text())
        reg = SourceRegistry.from_record({**vectors["registry"], "sources": [
            {**vectors["registry"]["sources"][0], "query_ids": ["k8s.events"]}]})
        base = {"contract_version": pl.RUN_PLAN_VERSION, "plan_id": "p", "registry_id": reg.registry_id,
                "registry_digest": reg.digest, "window": {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T08:30:00Z"},
                "expected_acquisitions": [{"source_id": reg.sources[0].source_id, "query_id": "k8s.events",
                                           "mandatory": False}],
                "rule_versions": {}, "synthesis_mode": "disabled",
                "limits": {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 1, "max_batch_deliveries": 1,
                           "max_observations_per_batch": 1, "max_observations_total": 1, "max_batch_bytes": 1024,
                           "max_total_bytes": 1024}}
        for version in (V1, V2):
            plan = pl.RunPlan.from_record({**base, "contract_versions": pl.required_contract_versions(version)}, reg)
            self.assertEqual(plan.kind_registry_version, version)
        mixed = {**pl.required_contract_versions(V2), "evidence": "ca-evidence/0.2-provisional"}
        for bad in (mixed, {**CONTRACT_VERSIONS, "observation-kinds": "ca-observation-kinds/0.3-provisional"},
                    {k: v for k, v in CONTRACT_VERSIONS.items() if k != "observation-kinds"}):
            with self.subTest(bad=sorted(set(bad.items()) ^ set(CONTRACT_VERSIONS.items()))), \
                    self.assertRaises(ContractError):
                pl.RunPlan.from_record({**base, "contract_versions": bad}, reg)


if __name__ == "__main__":
    unittest.main()
