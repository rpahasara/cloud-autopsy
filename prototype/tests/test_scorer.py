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


if __name__ == "__main__":
    unittest.main()
