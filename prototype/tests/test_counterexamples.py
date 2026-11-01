"""PR #13 counterexamples: a genuine Deployment-caused incident and a benign/no-incident case.

These are developer-authored fixtures and expectations, written before the engine changes
that evaluate them. They are regression tests, NOT independent or held-out evaluation, and
they cannot establish general causal discrimination.
"""

import copy

from ca_spike.fixtures import load_scenario
from tests.helpers import ROOT, RunTestCase, acquisition, hypothesis, prereq

DEPLOYMENT = {"kind": "Deployment", "namespace": "ca-demo", "name": "checkout-api"}


class CounterexampleCase(RunTestCase):
    fixture = None

    def scenario(self, variant="A"):
        return copy.deepcopy(load_scenario(ROOT / "fixtures" / self.fixture, variant))


class DeploymentCauseTests(CounterexampleCase):
    fixture = "cx-deploy-cause"

    def test_rollout_mechanism_is_supported_and_selected(self):
        run, _, bundle = self.run_variant("A")
        self.assertEqual(run["state"], "deterministic_complete")
        self.assertEqual(bundle["outcome"]["status"], "resolved")
        self.assertEqual(bundle["outcome"]["entity"], DEPLOYMENT)
        rollout = hypothesis(bundle, "deployment_rollout")
        self.assertEqual(rollout["status"], "supported")
        self.assertEqual({p["key"]: p["result"] for p in rollout["prerequisites"]}, {
            "rollout_observed": "satisfied", "changed_field_mapped": "satisfied",
            "consumed_by_symptomatic_pods": "satisfied", "symptom_after_consumption": "satisfied",
            "symptom_confined_to_new_revision": "satisfied"})

    def test_unmapped_configmap_change_closest_to_onset_is_not_supported(self):
        _, _, bundle = self.run_variant("A")
        cfg = hypothesis(bundle, "config_value_change")
        self.assertEqual(prereq(cfg, "mechanism_mapped")["reason"], "unmapped_config_key")
        self.assertNotEqual(cfg["status"], "supported")

    def test_baseline_picks_the_closer_configmap_change(self):
        _, store, _ = self.run_variant("A")
        baseline = store.get("baseline.json")
        self.assertEqual(baseline["outcome"]["mechanism"], "config_value_change")

    def test_symptom_on_old_revision_pod_contradicts_rollout(self):
        scenario = self.scenario()
        logs = acquisition(scenario, "loki.checkout-api")["observations"]
        old = copy.deepcopy(next(o for o in logs if o["attributes"]["template"] == "POOL_EXHAUSTED"))
        old.update(source_uid="uid-pod-6d4b5-a1", source_ref="loki:{namespace=ca-demo,pod=checkout-api-6d4b5-a1}#0009",
                   source_version="line-0009")
        old["entity"]["name"] = old["attributes"]["pod"] = "checkout-api-6d4b5-a1"
        old["times"][0].update(raw="2026-10-20T09:00:50.000Z", clock_domain="node-a")
        logs.append(old)
        _, _, bundle = self.run_scenario(scenario)
        self.assertEqual(hypothesis(bundle, "deployment_rollout")["status"], "contradicted")
        self.assertEqual(bundle["outcome"]["status"], "abstained")

    def test_rollout_without_consumption_evidence_is_unresolved(self):
        scenario = self.scenario()
        logs = acquisition(scenario, "loki.checkout-api")
        logs["observations"] = [o for o in logs["observations"] if o["attributes"]["fields"].get("value") != "4"]
        _, _, bundle = self.run_scenario(scenario)
        rollout = hypothesis(bundle, "deployment_rollout")
        self.assertEqual(prereq(rollout, "consumed_by_symptomatic_pods")["result"], "unsatisfied")
        self.assertEqual(bundle["outcome"]["status"], "abstained")


class BenignTests(CounterexampleCase):
    fixture = "cx-benign"

    def test_no_symptom_means_no_cause_is_selected(self):
        run, store, bundle = self.run_variant("A")
        self.assertEqual(run["state"], "deterministic_complete")
        self.assertEqual(bundle["outcome"]["status"], "abstained")
        self.assertIn("no_symptom_observed", bundle["outcome"]["reasons"])
        self.assertFalse([h for h in bundle["ledger"]["hypotheses"] if h["status"] == "supported"])
        self.assertEqual(prereq(hypothesis(bundle, "config_value_change"), "mechanism_mapped")["result"],
                         "contradicted")  # 50 -> 60 is an increase, not a reduction
        self.assertEqual(store.get("baseline.json")["outcome"]["status"], "abstained")
