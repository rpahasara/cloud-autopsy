"""Cross-scope correlation regressions (PR #22 review finding; pure, no database).

Pods, ConfigMaps and ReplicaSets are namespaced Kubernetes objects: the same name in another
namespace or another cluster is a different object. Every causal join must stay inside the
registry-bound ``(cluster_id, namespace)`` of the evidence, and a log may be attributed to a
pod only when that pod's identity is unambiguous; otherwise the engine must not invent the
relationship. Each case runs with the evidence records in both orders, so a dictionary that
silently overwrites one object with another cannot pass by luck.

Expectations are developer-authored regression expectations, not independent evaluation.
"""

import unittest

import _cross_scope as X
import _support as S
from cloud_autopsy.engine import RESULT_DIGEST_ALGORITHM, mechanisms, result

A1, A2 = "checkout-api-6d4b5-a1", "checkout-api-6d4b5-a2"
CHANGE = X.scenario._configmap_change
IMAGE_ROLLOUT = X.scenario._rollout


def home_pods():
    return [X.pod(A1, "node-a"), X.pod(A2, "node-b")]


def chain_logs(namespace=None, symptom_times=("2026-10-15T08:10:51.500Z", "2026-10-15T08:11:05.200Z")):
    return [X.reload(A1, "node-a", 41, "2026-10-15T08:10:21.500Z", namespace),
            X.reload(A2, "node-b", 17, "2026-10-15T08:10:23.200Z", namespace),
            X.exhausted(A1, "node-a", 57, symptom_times[0], namespace),
            X.exhausted(A2, "node-b", 33, symptom_times[1], namespace)]


def foreign_pods(namespace, **kwargs):
    return [X.pod(A1, "node-a", namespace=namespace, **kwargs), X.pod(A2, "node-b", namespace=namespace, **kwargs)]


def investigate(batch_records, reverse):
    inp = X.build(batch_records, reverse_members=reverse)
    res, raw = result.build(inp)
    result.verify_result(raw, inp)
    return inp, res


def hypothesis(res, mechanism):
    found = [h for h in res["hypotheses"] if h["mechanism"] == mechanism and h["change_evidence_id"]]
    assert len(found) == 1, found
    return found[0]


def cited(h):
    ids = {e for p in h["prerequisites"] for e in p["evidence_ids"]}
    return ids | {e for c in h["contradictions"] for e in c["evidence_ids"]}


CASES = [(tag, namespace, reverse) for tag, (_, namespace) in X.SCOPES.items() for reverse in (False, True)]


class CrossScopeTests(unittest.TestCase):
    def assert_home_only(self, inp, h):
        self.assertEqual({X.scope_of(inp, e) for e in cited(h)}, {X.HOME})

    def test_foreign_logs_cannot_support_a_home_config_change(self):
        # Home: the change and two mounting pods, but those pods logged nothing. Another scope
        # has pods with the same names, mounting a same-named ConfigMap, that reload and fail.
        for tag, namespace, reverse in CASES:
            with self.subTest(scope=tag, reversed_records=reverse):
                records = X.records(configmaps=[CHANGE()], deployments=[IMAGE_ROLLOUT()], pods=home_pods(), logs=[],
                                    foreign={tag: (foreign_pods(namespace), chain_logs(namespace))})
                inp, res = investigate(records, reverse)
                config = hypothesis(res, "config_limit_reduction")
                self.assertEqual(config["status"], mechanisms.NOT_SUPPORTED)
                self.assertEqual(res["outcome"]["status"], "abstained")
                self.assert_home_only(inp, config)

    def test_foreign_same_named_pods_do_not_hide_the_real_ones(self):
        # Home: complete config-cause chain. Another scope: same-named pods that mount nothing.
        expected = result.build(S.build("config-cause"))[0]["outcome"]
        for tag, namespace, reverse in CASES:
            with self.subTest(scope=tag, reversed_records=reverse):
                records = X.records(configmaps=[CHANGE()], deployments=[IMAGE_ROLLOUT()], pods=home_pods(),
                                    logs=chain_logs(),
                                    foreign={tag: (foreign_pods(namespace, owner="checkout-api-7c9f8", configmaps=()),
                                                   [])})
                inp, res = investigate(records, reverse)
                self.assertEqual(res["outcome"]["status"], "resolved")
                self.assertEqual(res["outcome"]["mechanism"], "config_limit_reduction")
                self.assertEqual(res["outcome"]["evidence_ids"], expected["evidence_ids"])
                self.assert_home_only(inp, hypothesis(res, "config_limit_reduction"))

    def test_foreign_symptoms_do_not_contradict_a_home_change(self):
        # Home: complete chain. Another scope: same-named mounting pods failing before the change.
        for tag, namespace, reverse in CASES:
            with self.subTest(scope=tag, reversed_records=reverse):
                early = [X.exhausted(A1, "node-a", 12, "2026-10-15T08:05:01.500Z", namespace),
                         X.exhausted(A2, "node-b", 9, "2026-10-15T08:04:10.200Z", namespace)]
                records = X.records(configmaps=[CHANGE()], deployments=[IMAGE_ROLLOUT()], pods=home_pods(),
                                    logs=chain_logs(), foreign={tag: (foreign_pods(namespace), early)})
                inp, res = investigate(records, reverse)
                config = hypothesis(res, "config_limit_reduction")
                self.assertEqual(config["contradictions"], [])
                self.assertEqual(res["outcome"]["status"], "resolved")
                self.assert_home_only(inp, config)

    def test_foreign_replicaset_of_the_same_name_cannot_support_a_rollout(self):
        # Home: a rollout that lowers the limit; no home pod of the new ReplicaSet. Another
        # scope: pods owned by a same-named ReplicaSet that log the symptom after the rollout.
        new_rs = "checkout-api-7c9f8"
        for tag, namespace, reverse in CASES:
            with self.subTest(scope=tag, reversed_records=reverse):
                f_pods = [X.pod(f"{new_rs}-b1", "node-a", owner=new_rs, namespace=namespace)]
                f_logs = [X.exhausted(f"{new_rs}-b1", "node-a", 70, "2026-10-15T08:13:00.000Z", namespace)]
                records = X.records(configmaps=[], deployments=[X.lowering_rollout()], pods=home_pods(), logs=[],
                                    foreign={tag: (f_pods, f_logs)})
                inp, res = investigate(records, reverse)
                rollout = hypothesis(res, "rollout_limit_reduction")
                self.assertEqual(rollout["status"], mechanisms.NOT_SUPPORTED)
                self.assertEqual(res["outcome"]["status"], "abstained")
                self.assert_home_only(inp, rollout)

    def test_in_scope_rollout_control_is_still_supported(self):
        # Positive control for the case above: the same pod and log in the home scope.
        new_rs = "checkout-api-7c9f8"
        for reverse in (False, True):
            with self.subTest(reversed_records=reverse):
                records = X.records(configmaps=[], deployments=[X.lowering_rollout()],
                                    pods=home_pods() + [X.pod(f"{new_rs}-b1", "node-a", owner=new_rs)],
                                    logs=[X.exhausted(f"{new_rs}-b1", "node-a", 70, "2026-10-15T08:13:00.000Z")])
                _, res = investigate(records, reverse)
                self.assertEqual(res["outcome"]["status"], "resolved")
                self.assertEqual(res["outcome"]["mechanism"], "rollout_limit_reduction")

    def test_ambiguous_pod_identity_abstains_instead_of_guessing(self):
        # Two pod instances share one name in one scope (different source UIDs); logs carry only
        # the name, so the load and the symptom cannot be tied to one pod.
        previous = X.pod(A1, "node-a", uid="uid-pod-checkout-api-6d4b5-a1-previous")
        previous["source_ref"] += "#previous"
        logs = [log for log in chain_logs() if log["attributes"]["pod"] == A1]
        for reverse in (False, True):
            with self.subTest(reversed_records=reverse):
                control = X.records(configmaps=[CHANGE()], deployments=[IMAGE_ROLLOUT()],
                                    pods=[X.pod(A1, "node-a")], logs=logs)
                self.assertEqual(investigate(control, reverse)[1]["outcome"]["status"], "resolved")

                records = X.records(configmaps=[CHANGE()], deployments=[IMAGE_ROLLOUT()],
                                    pods=[X.pod(A1, "node-a"), previous], logs=logs)
                _, res = investigate(records, reverse)
                config = hypothesis(res, "config_limit_reduction")
                self.assertEqual(config["status"], mechanisms.UNRESOLVED)
                self.assertIn("pod_identity_ambiguous", {p["reason"] for p in config["prerequisites"]})
                self.assertEqual(res["outcome"]["status"], "abstained")
                self.assertIn("pod_identity_ambiguous", res["outcome"]["reasons"])


# Result digests of the six scenario-001 variants as produced before the scope fix (commit
# dc26aa8). The fix must not change a single byte of any of them: same outcomes, citations,
# contradictions, gaps and clock-uncertainty orderings.
PRE_FIX_DIGESTS = {
    "config-cause": "bb9dd800be371798efaa67535ec5e30fd2d16fc26562b8e7b0d1269929a7dbdf",
    "configmap-unavailable": "62fda618cb68f1214e40314d90a2d19fdb9b3f704637bb01e06a40d8b1183c12",
    "configmap-conflict": "46eb56718f5bf009473964086e555fbab777acd09173fe44e5d0ba61678115af",
    "clock-unknown": "cf432725ee9f8dbb4bae2b516e91294908004e1e5630035589bf4ec7072cc0b3",
    "symptom-before-change": "0d3df824154903d32f439d47229481f25360abd7b82c33bd0d3546e880791faa",
    "no-symptom": "a63d17c126833833ac4da8cba902f4dbbb0646338000876cdd6fafaf3bdad1c4",
}


class PreservationTests(unittest.TestCase):
    def test_single_scope_variants_are_byte_identical_to_before_the_fix(self):
        self.assertEqual(set(PRE_FIX_DIGESTS), set(X.scenario.VARIANTS))
        for variant, digest in PRE_FIX_DIGESTS.items():
            with self.subTest(variant=variant):
                res, _ = result.build(S.build(variant))
                self.assertEqual(res["result_digest"], f"{RESULT_DIGEST_ALGORITHM}:{digest}")


if __name__ == "__main__":
    unittest.main()
