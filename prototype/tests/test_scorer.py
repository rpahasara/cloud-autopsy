import unittest

from ca_eval.scorer import load_truth, ratio, score_run, summarize
from tests.helpers import ROOT, RunTestCase


class ScorerTests(RunTestCase):
    def setUp(self):
        super().setUp()
        self.truth, self.truth_digest = load_truth(ROOT, "ca-scenario-001")

    def score(self, variant, **kw):
        run, store, _ = self.run_variant(variant)
        return run, score_run(store, self.truth, self.truth_digest, **kw)

    def test_zero_denominator_is_not_evaluated(self):
        self.assertEqual(ratio(0, 0)["status"], "not_evaluated")
        self.assertEqual(ratio(0, 0)["value"], "not_evaluated")

    def test_engine_and_baseline_scored_against_same_truth(self):
        reports = {}
        refs = {}
        for v in "ABCDE":
            run, report = self.score(v, reference_bundle_digests=refs)
            refs.setdefault(v, run["bundle_digest"])
            reports[v] = report
            self.assertEqual(report["truth_digest"], self.truth_digest)
            self.assertFalse(report["gate_eligible"])
            self.assertEqual(report["security"]["policy_result"], "pass")
        self.assertEqual(reports["A"]["engine"]["causal_attribution"], "correct")
        self.assertEqual(reports["A"]["engine"]["false_cause"], "rejected")
        self.assertEqual(reports["A"]["baseline"]["false_cause"], "selected")
        self.assertEqual(reports["B"]["engine"]["causal_attribution"], "abstained")
        self.assertTrue(reports["B"]["engine"]["result_correct"])
        self.assertFalse(reports["B"]["baseline"]["result_correct"])
        self.assertEqual(reports["B"]["engine"]["required_evidence_recall"]["denominator"], 15)
        self.assertEqual(reports["D"]["clock"]["matched"]["value"], "6/6")
        self.assertTrue(reports["E"]["equivalence_to_reference"]["equivalent"])
        self.assertEqual(reports["C"]["engine"]["unsupported_claims"], 1)
        summary = summarize(list(reports.values()))
        self.assertEqual(summary["engine"]["false_cause_selected"]["value"], "0/5")
        self.assertEqual(summary["baseline"]["false_cause_selected"]["value"], "5/5")

    def test_structurally_valid_model_prose_counts_as_unsupported(self):
        scenario = self.scenario("A")
        run, store, bundle = self.run_scenario(scenario)
        from ca_spike.synthesis import CONTRACT_VERSION, run_synthesis
        p = next(p for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"] if p["result"] == "satisfied")
        response = {"contract_version": CONTRACT_VERSION, "bundle_digest": run["bundle_digest"], "limitations": [],
                    "claims": [{"claim_id": "x", "kind": "observed", "text": "The Deployment is the root cause.",
                                "evidence_ids": p["evidence_ids"], "assertion_keys": [p["assertion_key"]]}]}
        store.put("synthesis.json", run_synthesis("stub", {"behavior": "respond", "response": response},
                                                  bundle, run["bundle_digest"]))
        engine = score_run(store, self.truth, self.truth_digest)["engine"]
        self.assertEqual(engine["unverified_model_claims"], 1)
        self.assertEqual(engine["unsupported_claims"], 1)


class CounterexampleScoringTests(RunTestCase):
    def _score(self, fixture_id):
        from ca_spike.fixtures import load_scenario
        truth, digest = load_truth(ROOT, fixture_id)
        _, store, _ = self.run_scenario(load_scenario(ROOT / "fixtures" / fixture_id, "A"))
        return score_run(store, truth, digest)

    def test_deploy_cause_engine_correct_baseline_selects_configmap(self):
        report = self._score("cx-deploy-cause")
        self.assertEqual(report["engine"]["causal_attribution"], "correct")
        self.assertEqual(report["engine"]["false_cause"], "rejected")
        self.assertEqual(report["baseline"]["false_cause"], "selected")
        self.assertEqual(report["engine"]["required_evidence_recall"]["value"], "12/12")

    def test_benign_both_methods_abstain_without_selecting_a_non_cause(self):
        report = self._score("cx-benign")
        self.assertTrue(report["engine"]["result_correct"])
        self.assertTrue(report["engine"]["abstention_reason_correct"])
        self.assertEqual(report["engine"]["false_cause"], "rejected")
        self.assertTrue(report["baseline"]["result_correct"])  # the naive baseline also abstains here
        self.assertEqual(report["independence"], "developer-authored; not independent or held-out")


if __name__ == "__main__":
    unittest.main()
