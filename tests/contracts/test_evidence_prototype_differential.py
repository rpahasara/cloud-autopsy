"""Read-only differential against the frozen prototype evidence model (ca-evidence/0.1-spike at c21b50d).

Every development-fixture observation (base fixtures and variant additions) is fed to both
implementations. Agreements and each documented intentional difference are asserted. The
prototype is imported from its directory without modification; the product package never
imports it.
"""

import copy
import json
import sys
import unittest

import _support
from cloud_autopsy.contracts import evidence as ev, sources

PROTOTYPE = _support.REPO / "prototype"
FIXTURES = ("ca-scenario-001", "cx-benign", "cx-deploy-cause")
REGISTRY = sources.SourceRegistry.from_record({
    "contract_version": sources.SOURCE_REGISTRY_VERSION, "registry_id": "ca-dev-fixtures",
    "sources": [
        {"source_id": "k8s-api", "source_kind": "kubernetes_api", "cluster_id": "ca-kind-synthetic",
         "namespace": "ca-demo", "clock_domain_ids": ["k8s-apiserver"],
         "query_ids": ["k8s.configmap-checkpoints", "k8s.deployments", "k8s.pods", "k8s.replicasets"]},
        {"source_id": "loki", "source_kind": "loki", "cluster_id": "ca-kind-synthetic", "namespace": "ca-demo",
         "clock_domain_ids": ["node-a", "node-b"], "query_ids": ["loki.checkout-api"]},
        {"source_id": "prometheus", "source_kind": "prometheus", "cluster_id": "ca-kind-synthetic",
         "namespace": "ca-demo", "clock_domain_ids": ["prometheus"],
         "query_ids": ["prom.alerts", "prom.checkout-api"]},
    ]})


def load_prototype_model():
    sys.path.insert(0, str(PROTOTYPE))
    try:
        from ca_spike import model  # noqa: PLC0415  (frozen prototype, read-only)
    finally:
        sys.path.remove(str(PROTOTYPE))
    return model


def fixture_deliveries():
    """(fixture, source_id, query_id, prototype observation) for base fixtures and variant additions."""
    out = []
    for fx in FIXTURES:
        root = PROTOTYPE / "fixtures" / fx
        doc = json.loads((root / "observations.json").read_bytes())
        query_source = {a["query_id"]: a["source_id"] for a in doc["acquisitions"]}
        for acquisition in doc["acquisitions"]:
            for obs in acquisition.get("observations", []):
                out.append((fx, acquisition["source_id"], acquisition["query_id"], obs))
        for variant in sorted((root / "variants").glob("*.json")):
            for op in json.loads(variant.read_bytes()).get("ops", []):
                if op.get("op") == "add_observation":
                    out.append((f"{fx}/{variant.stem}", query_source[op["query_id"]], op["query_id"],
                                op["observation"]))
    return out


def to_contract(obs):
    return {"contract_version": ev.OBSERVATION_VERSION,
            **{k: copy.deepcopy(obs[k]) for k in ("source_ref", "observation_kind", "source_uid", "source_version",
                                                  "entity", "attributes")},
            "times": [{"timestamp_kind": t["type"], "raw": t["raw"], "clock_domain_id": t["clock_domain"],
                       "declared_precision_ns": None} for t in obs["times"]]}


class EvidencePrototypeDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_prototype_model()
        cls.deliveries = fixture_deliveries()
        cls.pairs = []
        for fx, source_id, query_id, obs in cls.deliveries:
            old = cls.model.normalize(obs, query_id, source_id, {})
            new = ev.observe(to_contract(obs), source_id=source_id, registry=REGISTRY,
                             delivery={"query_id": query_id, "batch_id": "dev", "attempt": 1})
            cls.pairs.append((fx, old, new))

    def test_every_development_observation_is_accepted(self):
        self.assertGreaterEqual(len(self.pairs), 74)
        self.assertEqual({new.observation_kind for _, _, new in self.pairs}, set(ev.KINDS))

    def test_identity_equivalence_classes_agree(self):
        by_old, by_new = {}, {}
        for i, (_, old, new) in enumerate(self.pairs):
            by_old.setdefault(old.evidence_id, set()).add(i)
            by_new.setdefault(new.evidence_id, set()).add(i)
        self.assertEqual(sorted(map(sorted, by_old.values())), sorted(map(sorted, by_new.values())))

    def test_d1_ids_are_new_format_and_prototype_ids_are_refused(self):
        for _, old, new in self.pairs:
            self.assertTrue(old.evidence_id.startswith("ev:"))
            self.assertEqual(len(old.evidence_id.rsplit(":", 1)[1]), 24)
            self.assertEqual(len(ev.parse_evidence_id(new.evidence_id)), 64)
            with self.assertRaises(ev.EvidenceError):
                ev.parse_evidence_id(old.evidence_id)

    def test_d2_content_digests_use_a_new_algorithm_label(self):
        for _, old, new in self.pairs:
            self.assertTrue(old.content_digest.startswith("sha256:"))
            self.assertTrue(new.content_digest.startswith(ev.CONTENT_ALGORITHM + ":"))

    def test_d3_cluster_binding_separates_identities(self):
        obs = next(o for _, s, _, o in self.deliveries if o["observation_kind"] == "configmap_change")
        identity = self.model.evidence_identity("k8s-api", obs["observation_kind"], obs["source_uid"],
                                                obs["source_version"])
        self.assertNotIn("cluster_id", identity)  # prototype identity cannot tell clusters apart
        record = REGISTRY.to_record()
        record["sources"][0]["cluster_id"] = "ca-kind-other"
        moved = sources.SourceRegistry.from_record(record)
        a = ev.observe(to_contract(obs), source_id="k8s-api", registry=REGISTRY)
        b = ev.observe(to_contract(obs), source_id="k8s-api", registry=moved)
        self.assertNotEqual(a.evidence_id, b.evidence_id)

    def test_d4_set_valued_lists_are_order_independent(self):
        obs = next(o for _, _, _, o in self.deliveries if o["observation_kind"] == "deployment_rollout")
        shuffled = copy.deepcopy(obs)
        shuffled["attributes"]["config_refs_after"] = list(reversed(obs["attributes"]["config_refs_after"])) + \
            ["zz-extra-config"]
        original = copy.deepcopy(obs)
        original["attributes"]["config_refs_after"] = ["zz-extra-config"] + obs["attributes"]["config_refs_after"]
        old_a = self.model.normalize(original, "k8s.deployments", "k8s-api", {})
        old_b = self.model.normalize(shuffled, "k8s.deployments", "k8s-api", {})
        self.assertNotEqual(old_a.content_digest, old_b.content_digest)
        new_a = ev.observe(to_contract(original), source_id="k8s-api", registry=REGISTRY)
        new_b = ev.observe(to_contract(shuffled), source_id="k8s-api", registry=REGISTRY)
        self.assertEqual(new_a.content_digest, new_b.content_digest)

    def test_d5_open_attributes_are_refused(self):
        obs = copy.deepcopy(next(o for _, _, _, o in self.deliveries if o["observation_kind"] == "replicaset"))
        obs["attributes"]["env"] = "DB_PASSWORD=synthetic"
        self.model.normalize(obs, "k8s.replicasets", "k8s-api", {})  # prototype accepts it
        with self.assertRaises(ev.EvidenceError):
            ev.observe(to_contract(obs), source_id="k8s-api", registry=REGISTRY)

    def test_d6_namespace_outside_binding_is_refused(self):
        obs = copy.deepcopy(next(o for _, _, _, o in self.deliveries if o["observation_kind"] == "pod"))
        obs["entity"]["namespace"] = "kube-system"
        self.model.normalize(obs, "k8s.pods", "k8s-api", {})  # prototype accepts it
        with self.assertRaises(ev.EvidenceError):
            ev.observe(to_contract(obs), source_id="k8s-api", registry=REGISTRY)

    def test_prototype_files_are_unchanged(self):
        self.assertTrue((PROTOTYPE / "ca_spike" / "model.py").read_bytes().startswith(b'"""Storage-independent'))


if __name__ == "__main__":
    unittest.main()
