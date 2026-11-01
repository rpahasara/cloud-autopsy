"""PR #13 re-review: the scorer must judge the exact causal change, not only its entity."""

import copy
import unittest

from ca_eval.scorer import load_truth, score_run, summarize
from tests.helpers import CM_REF, ROOT, RunTestCase, evidence_id

DEPLOY_REF = "k8s:deployment/ca-demo/checkout-api@rev2"
OTHER_CM_REF = "k8s:configmap/ca-demo/checkout-db-pool@1003"
OTHER_DEPLOY_REF = "k8s:deployment/ca-demo/checkout-api@rev3"


def _acq(scenario, query_id):
    return next(a for a in scenario["observations"]["acquisitions"] if a["query_id"] == query_id)


def _add_unrelated_changes(scenario):
    """Same-entity changes that are not the declared cause or non-cause (earlier, unmapped key/field)."""
    cm = _acq(scenario, "k8s.configmap-checkpoints")["observations"]
    extra = copy.deepcopy(cm[0])
    extra.update(source_ref=OTHER_CM_REF, source_version="1003")
    extra["times"][0]["raw"] = "2026-10-15T07:30:00Z"
    extra["attributes"].update(data_key="log.level", before_value="debug", after_value="info",
                               before_value_sha256="0" * 64, after_value_sha256="1" * 64,
                               previous_resource_version="1000")
    cm.append(extra)
    dep = _acq(scenario, "k8s.deployments")["observations"]
    extra = copy.deepcopy(dep[0])
    extra.update(source_ref=OTHER_DEPLOY_REF, source_version="2002")
    extra["times"] = [{"type": "event", "raw": "2026-10-15T07:40:00Z", "clock_domain": "k8s-apiserver"}]
    extra["attributes"].update(revision="3", previous_revision="2")
    dep.append(extra)
    return scenario


class _UnrelatedChangesCase(RunTestCase):
    """Run ca-scenario-001/A with unrelated same-entity changes; outputs can then be rewritten."""

    def setUp(self):
        super().setUp()
        self.truth, self.digest = load_truth(ROOT, "ca-scenario-001")
        _, self.store, self.bundle = self.run_scenario(_add_unrelated_changes(self.scenario("A")))

    def _rewrite(self, artifact, outcome_update):
        doc = self.store.get(artifact)
        target = doc["bundle"]["outcome"] if artifact == "bundle.json" else doc["outcome"]
        target.update(outcome_update)
        self.store.put(artifact, doc)


class ExactChangeIdentityTests(_UnrelatedChangesCase):
    def test_engine_unchanged_by_unrelated_same_entity_changes(self):
        report = score_run(self.store, self.truth, self.digest)
        self.assertEqual(report["engine"]["causal_attribution"], "correct")
        self.assertEqual(report["engine"]["selected_change"]["source_ref"], CM_REF)
        self.assertEqual(report["engine"]["selected_change"]["identity"], "resolved")

    def test_same_entity_but_different_change_is_not_correct(self):
        self._rewrite("bundle.json", {"change_evidence_id": evidence_id(self.store, OTHER_CM_REF)})
        engine = score_run(self.store, self.truth, self.digest)["engine"]
        self.assertEqual(engine["causal_attribution"], "incorrect")
        self.assertFalse(engine["result_correct"])
        self.assertEqual(engine["selected_change"]["source_ref"], OTHER_CM_REF)

    def test_false_cause_distinguishes_individual_rollouts(self):
        # Selecting rollout rev3 is wrong, but it is not the declared false cause rev2.
        self._rewrite("bundle.json", {"status": "resolved", "mechanism": "deployment_rollout",
                                      "entity": {"kind": "Deployment", "namespace": "ca-demo",
                                                 "name": "checkout-api"},
                                      "change_evidence_id": evidence_id(self.store, OTHER_DEPLOY_REF)})
        engine = score_run(self.store, self.truth, self.digest)["engine"]
        self.assertEqual(engine["causal_attribution"], "incorrect")
        # rev3 is not the declared false cause; the rev2 hypothesis stays contradicted in the ledger.
        self.assertEqual(engine["false_cause"], "rejected")
        self._rewrite("bundle.json", {"change_evidence_id": evidence_id(self.store, DEPLOY_REF)})
        engine = score_run(self.store, self.truth, self.digest)["engine"]
        self.assertEqual(engine["false_cause"], "selected")
        self.assertEqual(engine["selected_change"]["source_ref"], DEPLOY_REF)

    def test_rejected_false_cause_is_judged_on_that_change_hypothesis(self):
        engine = score_run(self.store, self.truth, self.digest)["engine"]
        self.assertEqual(engine["false_cause"], "rejected")
        # Mark only the rev2 hypothesis supported (outcome unchanged): no longer "rejected".
        doc = self.store.get("bundle.json")
        rev2 = evidence_id(self.store, DEPLOY_REF)
        for h in doc["bundle"]["ledger"]["hypotheses"]:
            if h["change_evidence_id"] == rev2:
                h["status"] = "supported"
        self.store.put("bundle.json", doc)
        engine = score_run(self.store, self.truth, self.digest)["engine"]
        self.assertEqual(engine["false_cause"], "not_selected")

    def test_missing_change_identity_is_explicit_and_never_correct(self):
        self._rewrite("bundle.json", {"change_evidence_id": None})
        engine = score_run(self.store, self.truth, self.digest)["engine"]
        self.assertEqual(engine["selected_change"]["identity"], "missing")
        self.assertEqual(engine["causal_attribution"], "identity_unverifiable")
        self.assertEqual(engine["false_cause"], "identity_unverifiable")
        self.assertFalse(engine["result_correct"])

    def test_change_identity_not_in_evidence_is_explicit(self):
        for bad in ("ev:CHANGE:" + "0" * 24, ["not", "hashable"], {"x": 1}):
            self._rewrite("bundle.json", {"change_evidence_id": bad})
            engine = score_run(self.store, self.truth, self.digest)["engine"]
            self.assertEqual(engine["causal_attribution"], "identity_unverifiable")
            self.assertFalse(engine["result_correct"])

    def test_change_identity_inconsistent_with_outcome_entity_is_not_correct(self):
        # The cited change is the causal ConfigMap change, but the outcome names the Deployment.
        self._rewrite("bundle.json", {"mechanism": "deployment_rollout",
                                      "entity": {"kind": "Deployment", "namespace": "ca-demo",
                                                 "name": "checkout-api"},
                                      "change_evidence_id": evidence_id(self.store, CM_REF)})
        engine = score_run(self.store, self.truth, self.digest)["engine"]
        self.assertEqual(engine["selected_change"]["identity"], "inconsistent_with_outcome")
        self.assertEqual(engine["causal_attribution"], "identity_unverifiable")
        self.assertEqual(engine["false_cause"], "identity_unverifiable")


class FalseCauseDenominatorTests(_UnrelatedChangesCase):
    """Re-review P2: an unverifiable change identity must not count as having avoided the false cause."""

    def test_summary_excludes_unverifiable_identity_from_false_cause_denominator(self):
        verified = score_run(self.store, self.truth, self.digest)
        self._rewrite("bundle.json", {"change_evidence_id": "ev:CHANGE:" + "0" * 24})
        unverifiable = score_run(self.store, self.truth, self.digest)
        self.assertEqual(unverifiable["engine"]["false_cause"], "identity_unverifiable")

        engine = summarize([unverifiable])["engine"]
        self.assertEqual(engine["false_cause_selected"]["value"], "not_evaluated")
        self.assertEqual(engine["false_cause_selected"]["denominator"], 0)
        self.assertEqual(engine["false_cause_identity_unverifiable"]["value"], "1/1")
        self.assertEqual(engine["false_cause_traps"], 1)

        engine = summarize([verified, unverifiable])["engine"]
        self.assertEqual(engine["false_cause_selected"]["value"], "0/1")
        self.assertEqual(engine["false_cause_identity_unverifiable"]["value"], "1/2")
        self.assertEqual(engine["false_cause_traps"], 2)


class BaselineChangeIdentityTests(RunTestCase):
    def setUp(self):
        super().setUp()
        self.truth, self.digest = load_truth(ROOT, "ca-scenario-001")
        _, self.store, _ = self.run_variant("A")

    def test_baseline_reports_the_change_it_selected(self):
        baseline = self.store.get("baseline.json")
        self.assertEqual(baseline["outcome"]["change_evidence_id"], evidence_id(self.store, DEPLOY_REF))
        report = score_run(self.store, self.truth, self.digest)["baseline"]
        self.assertEqual(report["selected_change"]["source_ref"], DEPLOY_REF)
        self.assertEqual(report["false_cause"], "selected")

    def test_baseline_output_without_change_identity_is_explicit(self):
        # A baseline record lacking change-level identity (e.g. ca-baseline-naive/0.1) is never
        # credited and never silently counted as having avoided the false cause.
        baseline = self.store.get("baseline.json")
        baseline["outcome"].pop("change_evidence_id", None)
        self.store.put("baseline.json", baseline)
        report = score_run(self.store, self.truth, self.digest)
        self.assertEqual(report["baseline"]["selected_change"]["identity"], "missing")
        self.assertEqual(report["baseline"]["causal_attribution"], "identity_unverifiable")
        self.assertEqual(report["baseline"]["false_cause"], "identity_unverifiable")
        self.assertFalse(report["baseline"]["result_correct"])
        summary = summarize([report])
        self.assertEqual(summary["baseline"]["change_identity_unverifiable"]["value"], "1/1")
        self.assertEqual(summary["engine"]["change_identity_unverifiable"]["value"], "0/1")


class CounterexampleExactIdentityTests(RunTestCase):
    def test_counterexamples_scored_on_exact_change(self):
        from ca_spike.fixtures import load_scenario
        for fixture_id, engine_ref, baseline_ref in (
                ("cx-deploy-cause", DEPLOY_REF, "k8s:configmap/ca-demo/checkout-db-pool@1003"),
                ("cx-benign", None, None)):
            truth, digest = load_truth(ROOT, fixture_id)
            _, store, _ = self.run_scenario(load_scenario(ROOT / "fixtures" / fixture_id, "A"))
            report = score_run(store, truth, digest)
            self.assertEqual(report["engine"]["selected_change"]["source_ref"], engine_ref, fixture_id)
            self.assertEqual(report["baseline"]["selected_change"]["source_ref"], baseline_ref, fixture_id)


if __name__ == "__main__":
    unittest.main()
