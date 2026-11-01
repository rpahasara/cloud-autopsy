"""Engine behaviour per variant. Expectations are written from the fixture specification;
these tests never read the evaluator ground-truth file."""

import os
import subprocess
import sys
import unittest

from tests.helpers import CM_REF, ROOT, FIXTURES, RunTestCase, acquisition, evidence_id, hypothesis, prereq

CM = {"kind": "ConfigMap", "namespace": "ca-demo", "name": "checkout-db-pool"}


class VariantTests(RunTestCase):
    def test_a_config_supported_and_rollout_contradicted(self):
        run, store, bundle = self.run_variant("A")
        self.assertEqual(run["state"], "deterministic_complete")
        self.assertEqual(bundle["outcome"]["status"], "resolved")
        self.assertEqual(bundle["outcome"]["entity"], CM)
        cfg = hypothesis(bundle, "config_value_change")
        self.assertEqual(cfg["status"], "supported")
        self.assertTrue(all(p["result"] == "satisfied" for p in cfg["prerequisites"]))
        rollout = hypothesis(bundle, "deployment_rollout")
        self.assertEqual(rollout["status"], "contradicted")
        self.assertEqual(prereq(rollout, "changed_field_mapped")["result"], "unsatisfied")
        self.assertIn("symptom_on_previous_revision_pod", {c["key"] for c in rollout["contradictions"]})
        # temporal correlation is retained but never treated as support
        self.assertTrue(rollout["correlations"])
        self.assertTrue(all("not mechanism support" in c["note"] for c in rollout["correlations"]))

    def test_a_consumption_is_by_content_through_hot_reload(self):
        _, store, bundle = self.run_variant("A")
        consumed = [r for r in bundle["relations"] if r["relation_type"] == "config_value_consumed"]
        self.assertEqual(sorted(r["attributes"]["mode"] for r in consumed), ["load", "load", "reload", "reload"])
        cm_id = evidence_id(store, CM_REF)
        self.assertTrue(all(r["inputs"][2] == cm_id for r in consumed))

    def test_b_missing_config_evidence_abstains_without_promoting_rollout(self):
        run, _, bundle = self.run_variant("B")
        self.assertEqual(bundle["outcome"]["status"], "abstained")
        self.assertIsNone(bundle["outcome"]["entity"])
        self.assertEqual(run["state"], "partial")
        gaps = [(g["query_id"], g["gap_type"], g["reason"]) for g in bundle["gaps"]]
        self.assertEqual(gaps, [("k8s.configmap-checkpoints", "failed", "connector_timeout")])
        cm_acq = next(a for a in bundle["acquisitions"] if a["query_id"] == "k8s.configmap-checkpoints")
        self.assertEqual(cm_acq["status"], "failed")  # distinguishable from a clean empty result
        cfg = hypothesis(bundle, "config_value_change")
        self.assertEqual(cfg["status"], "unresolved")
        self.assertEqual(prereq(cfg, "change_observed")["result"], "blocked_by_gap")
        self.assertNotEqual(hypothesis(bundle, "deployment_rollout")["status"], "supported")

    def test_clean_empty_acquisition_is_not_a_gap(self):
        scenario = self.scenario("A")
        acquisition(scenario, "k8s.configmap-checkpoints")["observations"] = []
        _, _, bundle = self.run_scenario(scenario)
        acq = next(a for a in bundle["acquisitions"] if a["query_id"] == "k8s.configmap-checkpoints")
        self.assertEqual(acq["status"], "empty")
        self.assertEqual(bundle["gaps"], [])
        self.assertEqual(bundle["outcome"]["status"], "abstained")
        self.assertEqual(prereq(hypothesis(bundle, "config_value_change"), "change_observed")["reason"],
                         "no_change_observed")

    def test_missing_consumption_evidence_blocks_support(self):
        scenario = self.scenario("A")
        logs = acquisition(scenario, "loki.checkout-api")
        logs["observations"] = [o for o in logs["observations"]
                                if o["attributes"]["template"] not in ("CONFIG_LOADED", "CONFIG_RELOADED")]
        _, _, bundle = self.run_scenario(scenario)
        self.assertEqual(bundle["outcome"]["status"], "abstained")
        self.assertEqual(hypothesis(bundle, "config_value_change")["status"], "unresolved")

    def test_subpath_mount_is_not_hot_reload_eligible(self):
        scenario = self.scenario("A")
        for pod in acquisition(scenario, "k8s.pods")["observations"]:
            for vol in pod["attributes"]["configmap_volumes"]:
                vol["sub_path"] = True
        _, _, bundle = self.run_scenario(scenario)
        modes = {r["attributes"]["mode"] for r in bundle["relations"] if r["relation_type"] == "config_value_consumed"}
        self.assertEqual(modes, {"load"})

    def test_c_malicious_log_is_inert(self):
        run, store, bundle = self.run_variant("C")
        mal_ref = "loki:{namespace=ca-demo,pod=checkout-api-6d4b5-a2}#0009"
        mal = next(e for e in store.get("evidence.json") if e["source_ref"] == mal_ref)
        self.assertEqual(mal["trust"], "untrusted-source-data")
        self.assertIn("kubectl delete", mal["attributes"]["message"])  # retained verbatim as data
        cited = [p for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"]
                 if mal["evidence_id"] in p["evidence_ids"]]
        self.assertEqual(cited, [])
        self.assertEqual(bundle["outcome"]["entity"], CM)
        synthesis = store.get("synthesis.json")
        self.assertEqual(synthesis["status"], "rejected")
        self.assertIn("prohibited_field:$.actions", synthesis["reasons"])
        self.assertEqual(synthesis["validated_claims"], [])
        self.assertEqual(run["state"], "partial")

    def test_d_clock_uncertainty_is_reported_not_invented(self):
        _, store, bundle = self.run_variant("D")
        table = {(o["a"], o["b"]): (o["order"], o["basis"]) for o in bundle["ordering"]}

        def order(a_ref, b_ref):
            a, b = evidence_id(store, a_ref), evidence_id(store, b_ref)
            if (a, b) in table:
                return table[(a, b)]
            o, basis = table[(b, a)]
            return {"before": "after", "after": "before"}.get(o, o), basis

        a1 = "loki:{namespace=ca-demo,pod=checkout-api-6d4b5-a1}#"
        a2 = "loki:{namespace=ca-demo,pod=checkout-api-6d4b5-a2}#"
        self.assertEqual(order(CM_REF, a1 + "0002"), ("unordered", "unbounded_clock"))
        self.assertEqual(order(CM_REF, a2 + "0002")[0], "before")
        self.assertEqual(order(a1 + "0002", a1 + "0003"), ("before", "same_domain"))
        self.assertEqual(order("k8s:deployment/ca-demo/checkout-api@rev2", "k8s:replicaset/ca-demo/checkout-api-7c9f8"),
                         ("unordered", "same_domain_overlap"))
        bad = next(r for r in bundle["timeline"]
                   if r["source_ref"] == "loki:{namespace=ca-demo,pod=checkout-api-7c9f8-b2}#0001")
        self.assertEqual((bad["parse_status"], bad["parsed_utc"], bad["raw"]), ("error", None, "2026-10-15 08:12:22"))
        self.assertEqual(bundle["outcome"]["entity"], CM)

    def test_e_synthesis_failure_preserves_deterministic_bundle(self):
        run_a, _, _ = self.run_variant("A")
        run_e, store, _ = self.run_variant("E")
        self.assertEqual(run_e["bundle_digest"], run_a["bundle_digest"])
        self.assertEqual(run_e["state"], "partial")
        self.assertIn("synthesis_rejected", run_e["partial_reasons"])
        self.assertIn("claim[0]:citation_not_in_bundle:1", store.get("synthesis.json")["reasons"])

    def test_synthesis_timeout_is_unavailable_and_bundle_unchanged(self):
        run_a, _, _ = self.run_variant("A")
        scenario = self.scenario("E")
        scenario["synthesis_stub"] = {"stub_version": "0.1", "behavior": "timeout"}
        run, store, _ = self.run_scenario(scenario)
        self.assertEqual(store.get("synthesis.json")["status"], "unavailable")
        self.assertEqual(run["bundle_digest"], run_a["bundle_digest"])


class DeterminismTests(RunTestCase):
    def test_permuted_and_duplicated_delivery_is_equivalent_for_all_variants(self):
        for v in "ABCDE":
            with self.subTest(variant=v):
                first, _, _ = self.run_variant(v)
                for seed in (1, 99, 20261101):
                    again, _, _ = self.run_variant(v, permute_seed=seed, duplicate_delivery=True)
                    self.assertEqual(again["bundle_digest"], first["bundle_digest"])
                    self.assertEqual(again["manifest_digest"], first["manifest_digest"])

    def test_identity_conflict_is_quarantined_independent_of_order(self):
        scenario = self.scenario("A")
        logs = acquisition(scenario, "loki.checkout-api")["observations"]
        clone = dict(logs[0], attributes=dict(logs[0]["attributes"], message="different content"))
        logs.append(clone)
        digests = set()
        for seed in (None, 3, 7):
            _, store, bundle = self.run_scenario(scenario, permute_seed=seed)
            digests.add(bundle["manifest_digest"])
            refs = {e["source_ref"] for e in store.get("evidence.json")}
            self.assertNotIn(logs[0]["source_ref"], refs)
            self.assertIn(("loki.checkout-api", "unverifiable", "identity_conflict"),
                          {(g["query_id"], g["gap_type"], g["reason"]) for g in bundle["gaps"]})
        self.assertEqual(len(digests), 1)

    def test_bundle_digest_independent_of_python_hash_seed(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import tempfile;"
                "from ca_spike.fixtures import load_scenario; from ca_spike.pipeline import run_investigation;"
                "from ca_spike.store import FileArtifactStore;"
                "print(run_investigation(load_scenario(sys.argv[2], 'D'),"
                " FileArtifactStore(tempfile.mkdtemp()))['bundle_digest'])")
        outputs = set()
        for seed in ("0", "1", "987654"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            res = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT), str(FIXTURES)], env=env,
                                 capture_output=True, text=True, check=True)
            outputs.add(res.stdout.strip())
        self.assertEqual(len(outputs), 1)


class BoundsTests(RunTestCase):
    def test_oversized_observation_is_rejected_explicitly_and_blocks_support(self):
        scenario = self.scenario("A")
        logs = acquisition(scenario, "loki.checkout-api")["observations"]
        logs.append(dict(logs[0], source_ref="loki:oversize", source_version="line-9999",
                         attributes=dict(logs[0]["attributes"], message="x" * 9000)))
        run, _, bundle = self.run_scenario(scenario)
        acq = next(a for a in bundle["acquisitions"] if a["query_id"] == "loki.checkout-api")
        self.assertEqual((acq["status"], acq["observations_rejected"]), ("truncated", 1))
        self.assertIn(("loki.checkout-api", "truncated"), {(g["query_id"], g["gap_type"]) for g in bundle["gaps"]})
        self.assertEqual(bundle["outcome"]["status"], "abstained")
        self.assertEqual(run["state"], "partial")


if __name__ == "__main__":
    unittest.main()
