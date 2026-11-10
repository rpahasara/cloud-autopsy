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
import _semantic
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


# Six-variant preservation (CA-P2-005a review fix, then CA-P2-006a).
#
# SEMANTIC_VIEWS: digests of ``_semantic.view`` (timeline, hypotheses, citations, orderings,
# contradictions, gaps and outcome, with no version, plan, manifest or gap-ID digests) as
# produced by commit 3cba5d3 under ca-investigation-result/0.1-provisional, whose own result
# bytes were in turn identical to dc26aa8 (before the scope fix). CA-P2-006a moves the result to
# 0.2-provisional, which changes the bytes but must not change any conclusion.
SEMANTIC_VIEWS = {
    "config-cause": "28d02490352a0adc3cc8d09ee676eea05b65e2b45a9b45d94355a74d659cb247",
    "configmap-unavailable": "7e73c3bd1f20a361375c04b859934adcae07a1b7b51186808064ce256ea0f7dd",
    "configmap-conflict": "080278138f7e04185664821c47d8d022fa93b237123c3f60184251502f33f1d2",
    "clock-unknown": "4358007d8f3f89337422d9da5bc0c76950b71ab5bc64b6c2b5154fc67f738c1c",
    "symptom-before-change": "8903df118b124086f1da856d15ba7433c6fff62ef15507a9516cdd2a99a595aa",
    "no-symptom": "023f1e3fe655c5c2238a4356b5eee06127bddb632b233ba1482d3d786e9bed2b",
}
# RESULT_DIGESTS: the exact ca-investigation-result/0.2-provisional digests, pinned so any later
# byte change is deliberate.
RESULT_DIGESTS = {
    "config-cause": "c95ad8038fada020162fa4add60429e500eabe1ced7687bf9b50e8b0868f58a5",
    "configmap-unavailable": "080a1cd3f47a11d1ce853e641a2d37cdd712c9ac554faf0eb2d456ebc158ecac",
    "configmap-conflict": "c9277c489fdd345455671ce8be5ddd49ffc332eddc0fe7ae3afbba22bea6d9b4",
    "clock-unknown": "f9934a8b3a8ce443c3bb4207127e505550f753f09f582f58b772910c98be46e7",
    "symptom-before-change": "98229e03cb56d1cbcaa3862cf0b234075c9a207b3883bd11d8d8919d980e1ae4",
    "no-symptom": "58e15e48f5dfc9067742bffb3bd5cdd29d30f7fd886898d175b223af1004c980",
}


class PreservationTests(unittest.TestCase):
    def test_six_variant_conclusions_are_unchanged(self):
        self.assertEqual(set(SEMANTIC_VIEWS), set(X.scenario.VARIANTS))
        for variant, digest in SEMANTIC_VIEWS.items():
            with self.subTest(variant=variant):
                res, _ = result.build(S.build(variant))
                self.assertEqual(_semantic.view_digest(res).split(":")[1], digest)

    def test_six_variant_result_bytes_are_pinned(self):
        self.assertEqual(set(RESULT_DIGESTS), set(X.scenario.VARIANTS))
        for variant, digest in RESULT_DIGESTS.items():
            with self.subTest(variant=variant):
                res, _ = result.build(S.build(variant))
                self.assertEqual(res["result_digest"], f"{RESULT_DIGEST_ALGORITHM}:{digest}")


if __name__ == "__main__":
    unittest.main()
