"""CA-P2-005c: the engine on contract profile 4 (observation kinds 0.4, pod logs from the Kubernetes API).

All evidence is synthetic. The logs here stand in for what the CA-P2-004g collector will record: a
``kubernetes_api`` ``log_line`` with the sequence envelope, bound to its pod's UID, with an ``observed``
bracket on the session clock. These tests show the engine's handling of such records; they are not
evidence that real collection resolves (that is CA-P2-007a's job, measured on the kind cluster).

- Rule profile 2 accepts kinds 0.4; with separated brackets the existing ``rollout_limit_reduction``
  mechanism resolves, unchanged.
- Under rule profile 1 the same evidence abstains (the runtime timestamps are on an unknown clock).
- A gap on the Kubernetes API source now limits log-needing mechanisms, because under 0.4 that source
  kind produces ``log_line`` (kind-to-source mapping from the pinned registry).
- A Kubernetes API log naming another pod UID than the pod of that name makes the name ambiguous.
- Profile 3 and earlier keep their old mapping (the six pinned digests are asserted elsewhere).
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import test_ordering_rules as T
from cloud_autopsy.app import bundle as B
from cloud_autopsy.app import create as C
from cloud_autopsy.contracts import acquisition as acq
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import timeinterval as ti
from cloud_autopsy.engine import TIMELINE_RULES_VERSION_V2

V4 = ev.KIND_REGISTRY_VERSION_V4
RUNTIME = "k8s-container-runtime"
POD_UID = "uid-pod-a"  # the uid T.pod() gives scope "a"


def k8s_log(seq=12, observed=("2026-11-12T10:03:00.000000000Z", 1_000_000_000), domain=T.COL, uid=POD_UID,
            template="POOL_EXHAUSTED", revision="2"):
    name = f"checkout-api-new{revision}-a"
    times = [T.stamp("event", "2026-11-12T10:03:00.5Z", RUNTIME, None)]
    if observed:
        times.append(T.stamp("observed", observed[0], domain, observed[1]))
    return T.obs("log_line", f"k8s:pods/log/ca-demo/{name}/checkout-api#0a1b2c3d.{seq}", uid, f"0a1b2c3d.{seq}",
                 "Pod", name, times,
                 {"pod": name, "template": template, "fields": {"pool": "checkout-db", "in_use": "8", "max": "4"},
                  "container": "checkout-api", "boot": "0a1b2c3d", "seq": seq})


class Fixture4(T.Fixture):
    """Profile 4: the Kubernetes API sources also answer ``k8s.pods.log``; no loki sources."""

    def __init__(self, rule_profile=2, domains=(T.COL, T.SRV, RUNTIME), **kw):
        super().__init__(rule_profile, kinds=V4, domains=domains, **kw)
        self.batch_version = acq.BATCH_VERSION_V2
        for source in self.registry_record["sources"]:
            if source["source_kind"] == "kubernetes_api":
                source["query_ids"] = sorted(source["query_ids"] + ["k8s.pods.log"])
        self.registry_record["sources"] = [s for s in self.registry_record["sources"] if s["source_kind"] != "loki"]
        self.registry = T.SourceRegistry.from_record(self.registry_record)
        self.acquisitions = [(f"k8s-{s}", q) for s in T.SCOPES for q in ("k8s.deployments", "k8s.pods", "k8s.pods.log")]
        self.plan_record.update(registry_digest=self.registry.digest, expected_acquisitions=[
            {"source_id": s, "query_id": q, "mandatory": True} for s, q in self.acquisitions])
        self.plan = T.pl.RunPlan.from_record(self.plan_record, self.registry)
        self.clocks = [ti.clock_domain(d, ti.UNKNOWN, continuity=ti.CONTINUOUS if d == T.COL else ti.UNKNOWN).to_record()
                       for d in sorted(set(domains))]


def spec4(roll=None, pods=None, logs=None):
    return {("k8s-a", "k8s.deployments"): [roll or T.rollout()], ("k8s-a", "k8s.pods"): [pods or T.pod()],
            ("k8s-a", "k8s.pods.log"): logs if logs is not None else [k8s_log()]}


class Base4(unittest.TestCase):
    def run_case(self, observations, rule_profile=2, partial=(), **fixture):
        fx = Fixture4(rule_profile, **fixture)
        tmp = Path(tempfile.mkdtemp(prefix="ca-pod-log-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        B.write(tmp / "bundle", "ca-ordering-tests", fx.registry_record, fx.plan_record, fx.clocks,
                fx.batches(observations, partial))
        return C.investigate_offline(B.load(tmp / "bundle"))

    def outcome(self, observations, rule_profile=2, **kw):
        return self.run_case(observations, rule_profile, **kw).result["outcome"]


class PodLogsOnProfile4(Base4):
    def test_separated_brackets_resolve_with_the_existing_mechanism(self):
        inv = self.run_case(spec4())
        outcome = inv.result["outcome"]
        self.assertEqual((outcome["status"], outcome["mechanism"]), ("resolved", "rollout_limit_reduction"))
        self.assertEqual(inv.result["timeline"]["rule_version"], TIMELINE_RULES_VERSION_V2)
        kinds = {e["observation_kind"] for e in inv.result["timeline"]["entries"]}
        self.assertIn("log_line", kinds)

    def test_rule_profile_1_abstains_on_the_same_evidence(self):
        outcome = self.outcome(spec4(), 1)
        self.assertEqual(outcome["status"], "abstained")
        self.assertIn("ordering_unknown", outcome["reasons"])

    def test_overlapping_brackets_stay_unordered(self):
        log = k8s_log(observed=("2026-11-12T10:01:59.000000000Z", 5_000_000_000))
        outcome = self.outcome(spec4(logs=[log]))
        self.assertEqual(outcome["status"], "abstained")
        self.assertIn("ordering_unknown", outcome["reasons"])

    def test_a_log_without_an_observed_bracket_is_never_ordered(self):
        outcome = self.outcome(spec4(logs=[k8s_log(observed=None)]))
        self.assertEqual(outcome["status"], "abstained")

    def test_a_gap_on_the_pod_log_query_limits_the_mechanism(self):
        outcome = self.outcome(spec4(), partial=[("k8s-a", "k8s.pods.log")])
        self.assertEqual(outcome["status"], "abstained")
        self.assertIn("limiting_evidence_gaps", outcome["reasons"])

    def test_a_log_bound_to_another_pod_uid_makes_the_name_ambiguous(self):
        for name, logs in (("other uid", [k8s_log(uid="uid-pod-replacement")]),
                           ("one of two uids", [k8s_log(), k8s_log(seq=13, uid="uid-pod-replacement")])):
            with self.subTest(case=name):
                inv = self.run_case(spec4(logs=logs))
                outcome = inv.result["outcome"]
                self.assertEqual(outcome["status"], "abstained")
                self.assertIn("pod_identity_ambiguous", outcome["reasons"])
                hyp = next(h for h in inv.result["hypotheses"] if h["mechanism"] == "rollout_limit_reduction"
                           and h["change_evidence_id"])
                self.assertNotEqual(hyp["status"], "supported")

    def test_false_cause_traps_do_not_resolve(self):
        for name, roll in (("image-only rollout", T.rollout(field_changes=False)),
                           ("limit raised", T.rollout(after="60"))):
            with self.subTest(case=name):
                self.assertEqual(self.outcome(spec4(roll=roll))["status"], "abstained")

    def test_a_symptom_before_the_rollout_contradicts_it(self):
        early = k8s_log(observed=("2026-11-12T10:01:00.000000000Z", 1_000_000_000))
        outcome = self.outcome(spec4(logs=[early, k8s_log(seq=40)]))
        self.assertEqual(outcome["status"], "abstained")
        self.assertIn("contradicting_evidence_present", outcome["reasons"])

    def test_no_symptom_abstains(self):
        outcome = self.outcome(spec4(logs=[k8s_log(template="HEARTBEAT")]))
        self.assertIn("no_symptom_observed", outcome["reasons"])

    def test_brackets_from_two_sessions_are_refused(self):
        with self.assertRaises(Exception) as ctx:
            self.run_case(spec4(logs=[k8s_log(domain=T.COL2)]), domains=(T.COL, T.COL2, T.SRV, RUNTIME))
        self.assertIn("observed_clock_domains_mixed", repr(ctx.exception) + repr(ctx.exception.__cause__))


class KindToSourceMapping(unittest.TestCase):
    """The mapping comes from the pinned registry: before 0.4 a Kubernetes API source never produces
    ``log_line``, so its gaps limit log-needing mechanisms only through ``pod`` and the rollout, as before."""

    def context(self, kinds):
        from types import SimpleNamespace
        from cloud_autopsy.engine import mechanisms
        fx = T.Fixture(1, kinds=kinds) if kinds != V4 else Fixture4(1)
        inp = SimpleNamespace(clock_domains={}, members=(), plan=fx.plan, registry=fx.registry)
        return mechanisms._Context(inp)

    def test_before_0_4_logs_come_from_loki_only(self):
        for kinds in (ev.KIND_REGISTRY_VERSION, ev.KIND_REGISTRY_VERSION_V2, ev.KIND_REGISTRY_VERSION_V3):
            with self.subTest(kinds=kinds):
                ctx = self.context(kinds)
                self.assertNotIn("log_line", ctx.source_kinds["k8s-a"])
                self.assertIn("log_line", ctx.source_kinds["loki-a"])

    def test_under_0_4_the_kubernetes_api_produces_logs(self):
        self.assertIn("log_line", self.context(V4).source_kinds["k8s-a"])


if __name__ == "__main__":
    unittest.main()
