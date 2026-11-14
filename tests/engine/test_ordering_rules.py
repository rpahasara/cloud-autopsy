"""CA-P2-005b acceptance tests T1-T12, T14: timeline rules 0.2 (``observed``-first ordering).

All evidence is synthetic. The positive control places a log source on the same collector clock as
the Kubernetes brackets: a **synthetic assumption** that makes ordering possible, not a capability
of the real collector (which reads no logs). It shows the rules work; it is not evidence that
collector-only investigations can resolve. Those still abstain (no symptom source, values withheld).

Each case runs under rule profile 1 (timeline 0.1, ``event`` ordering) and, where meaningful, rule
profile 2 (timeline 0.2), so a change of conclusion between the profiles is explicit.
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.app import bundle as B  # noqa: E402
from cloud_autopsy.app import create as C  # noqa: E402
from cloud_autopsy.contracts import acquisition as acq  # noqa: E402
from cloud_autopsy.contracts import canonical  # noqa: E402
from cloud_autopsy.contracts import evidence as ev  # noqa: E402
from cloud_autopsy.contracts import plan as pl  # noqa: E402
from cloud_autopsy.contracts import timeinterval as ti  # noqa: E402
from cloud_autopsy.contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry  # noqa: E402
from cloud_autopsy.engine import TIMELINE_RULES_VERSION, TIMELINE_RULES_VERSION_V2, required_rule_versions  # noqa: E402
from cloud_autopsy.engine import timeline  # noqa: E402

COL, COL2 = "ca-collector-cs-00000000000000a1", "ca-collector-cs-00000000000000b2"
SRV, NODE = "k8s-apiserver", "node-a"
WINDOW = ("2026-11-12T10:00:00.000Z", "2026-11-12T10:10:00.000Z")
SCOPES = {"a": ("ca-kind-synthetic", "ca-demo"), "b": ("ca-kind-synthetic", "ca-other"),
          "c": ("ca-kind-other", "ca-demo")}
LIMITS = {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 10, "max_batch_deliveries": 100,
          "max_observations_per_batch": 100, "max_observations_total": 1000, "max_batch_bytes": 1_048_576,
          "max_total_bytes": 10_000_000}


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def stamp(kind, raw, domain, precision_ns=1_000_000_000):
    return {"timestamp_kind": kind, "raw": raw, "clock_domain_id": domain, "declared_precision_ns": precision_ns}


def obs(kind, ref, uid, version, entity_kind, name, times, attributes, scope="a"):
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": ref, "observation_kind": kind,
            "source_uid": uid, "source_version": version,
            "entity": {"kind": entity_kind, "namespace": SCOPES[scope][1], "name": name},
            "times": times, "attributes": attributes}


def rollout(observed=("2026-11-12T10:02:00.000000000Z", 2_000_000_000), event="2026-11-12T10:02:00Z",
            observed_domain=COL, after="4", field_changes=True, version="3002", scope="a", revision="2"):
    times = [stamp("event", event, SRV)]
    if observed:
        times.append(stamp("observed", observed[0], observed_domain, observed[1]))
    changes = [{"field": "spec.template.spec.containers[checkout-api].env[POOL_MAX]",
                "config_key": "pool.maxConnections", "before_value": "50", "after_value": after,
                "before_value_sha256": _sha("50"), "after_value_sha256": _sha(after)}] if field_changes else []
    return obs("deployment_rollout", f"k8s:deployment/x/checkout-api@rev{revision}", f"uid-deploy-{scope}", version,
               "Deployment", "checkout-api", times,
               {"revision": revision, "previous_revision": "1",
                "changed_fields": ["spec.template.spec.containers[checkout-api].env[POOL_MAX]"],
                "image_before": "registry.invalid/a:1", "image_after": "registry.invalid/a:1" if field_changes
                else "registry.invalid/a:2", "config_refs_before": [], "config_refs_after": [],
                "old_replicaset": "checkout-api-old", "new_replicaset": f"checkout-api-new{revision}",
                "field_changes": changes}, scope)


def pod(scope="a", observed=("2026-11-12T10:02:05.000000000Z", 1_000_000_000), observed_domain=COL, revision="2"):
    times = [stamp("event", "2026-11-12T10:02:04Z", SRV)]
    if observed:
        times.append(stamp("observed", observed[0], observed_domain, observed[1]))
    return obs("pod", f"k8s:pod/x/checkout-api-new{revision}-a@4001", f"uid-pod-{scope}", "4001", "Pod",
               f"checkout-api-new{revision}-a", times,
               {"owner_replicaset": f"checkout-api-new{revision}", "node": "node-1", "restart_count": 0,
                "configmap_volumes": []}, scope)


def symptom(at="2026-11-12T10:03:00Z", domain=COL, scope="a", revision="2", precision_ns=1_000_000_000):
    name = f"checkout-api-new{revision}-a"
    return obs("log_line", f"loki:{{pod={name}}}#0001", f"uid-pod-{scope}", "line-0001", "Pod", name,
               [stamp("event", at, domain, precision_ns)],
               {"pod": name, "template": "POOL_EXHAUSTED",
                "fields": {"pool": "primary", "in_use": "4", "max": "4", "wait_ms": "5000"},
                "message": "connection pool exhausted"}, scope)


class Fixture:
    """A profile-3 (or, for T12, profile-2) bundle with sources in scopes a, b and c."""

    def __init__(self, rule_profile=1, kinds=ev.KIND_REGISTRY_VERSION_V3, clocks=None, domains=(COL, SRV),
                 log_domains=(COL,)):
        sources = []
        for s, (cluster, namespace) in SCOPES.items():
            sources.append({"source_id": f"k8s-{s}", "source_kind": "kubernetes_api", "cluster_id": cluster,
                            "namespace": namespace, "clock_domain_ids": sorted(domains),
                            "query_ids": ["k8s.deployments", "k8s.pods"]})
            sources.append({"source_id": f"loki-{s}", "source_kind": "loki", "cluster_id": cluster,
                            "namespace": namespace, "clock_domain_ids": sorted(log_domains),
                            "query_ids": ["loki.checkout-api"]})
        self.registry_record = {"contract_version": SOURCE_REGISTRY_VERSION, "registry_id": "ca-ordering-tests",
                                "sources": sources}
        self.registry = SourceRegistry.from_record(self.registry_record)
        self.kinds = kinds
        self.batch_version = acq.BATCH_VERSION_V2 if kinds == ev.KIND_REGISTRY_VERSION_V3 else acq.BATCH_VERSION
        self.acquisitions = [(f"{k}-{s}", q) for s in SCOPES for k, q in
                             (("k8s", "k8s.deployments"), ("k8s", "k8s.pods"), ("loki", "loki.checkout-api"))]
        self.plan_record = {
            "contract_version": pl.RUN_PLAN_VERSION, "plan_id": "ca-ordering-tests",
            "registry_id": self.registry.registry_id, "registry_digest": self.registry.digest,
            "window": {"start": WINDOW[0], "end": WINDOW[1]},
            "expected_acquisitions": [{"source_id": s, "query_id": q, "mandatory": True} for s, q in self.acquisitions],
            "contract_versions": pl.required_contract_versions(kinds),
            "rule_versions": required_rule_versions(rule_profile), "synthesis_mode": "disabled", "limits": LIMITS}
        self.plan = pl.RunPlan.from_record(self.plan_record, self.registry)
        all_domains = sorted(set(domains) | set(log_domains))
        clocks = clocks or {}
        self.clocks = [clocks.get(d) or ti.clock_domain(d, ti.UNKNOWN, continuity=ti.CONTINUOUS if d != SRV
                                                         else ti.UNKNOWN).to_record() for d in all_domains]
        self.rv = 1000

    def batches(self, observations, partial=()):
        """``observations``: {(source_id, query_id): [...]}; every planned acquisition gets one batch."""
        records = []
        for source_id, query_id in self.acquisitions:
            items = observations.get((source_id, query_id), [])
            outcome = acq.PARTIAL if (source_id, query_id) in partial else (acq.COMPLETE if items else acq.EMPTY)
            record = {"contract_version": self.batch_version, "plan_digest": self.plan.digest, "source_id": source_id,
                      "query_id": query_id, "batch_key": "b-1", "sequence": 1, "outcome": outcome,
                      "reason": "continuity_unproven" if outcome == acq.PARTIAL else None,
                      "coverage": {"start": WINDOW[0], "end": WINDOW[1]}, "cursor": {"before": None, "after": "c-1"},
                      "truncation": {"truncated": False, "reason": None, "omitted_count": None},
                      "observations": items, "delivery": {"attempt": 1}}
            if self.batch_version == acq.BATCH_VERSION_V2:
                basis = None
                if outcome in (acq.COMPLETE, acq.EMPTY):
                    self.rv += 10
                    basis = {"kind": acq.WATCH_CONTINUITY, "resource_type": f"fixture/{query_id}", "session_id": "s1",
                             "clock_domain_id": COL, "rv_comparison": "k8s-1.37-decimal",
                             "start_anchor": {"kind": "list_first_page_received", "at": WINDOW[0],
                                              "resource_version": str(self.rv)},
                             "end_anchor": {"kind": "probe_sent", "at": WINDOW[1], "resource_version": str(self.rv + 5),
                                            "proven_by_resource_version": str(self.rv + 6)}}
                    record["cursor"]["after"] = f"rv:{self.rv + 6}"
                record["coverage_basis"] = basis
            records.append(record)
        return records


def spec(roll=None, pods=None, logs=None, scope="a"):
    return {(f"k8s-{scope}", "k8s.deployments"): [roll or rollout()], (f"k8s-{scope}", "k8s.pods"): [pods or pod()],
            (f"loki-{scope}", "loki.checkout-api"): [logs or symptom()]}


class Base(unittest.TestCase):
    def run_case(self, observations, rule_profile, partial=(), **fixture):
        fx = Fixture(rule_profile, **fixture)
        tmp = Path(tempfile.mkdtemp(prefix="ca-ordering-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        B.write(tmp / "bundle", "ca-ordering-tests", fx.registry_record, fx.plan_record, fx.clocks,
                fx.batches(observations, partial))
        return C.investigate_offline(B.load(tmp / "bundle"))

    def outcome(self, observations, rule_profile, **kw):
        return self.run_case(observations, rule_profile, **kw).result["outcome"]

    def both(self, observations, **kw):
        return self.outcome(observations, 1, **kw), self.outcome(observations, 2, **kw)

    def hypothesis(self, inv, mechanism="rollout_limit_reduction"):
        return next(h for h in inv.result["hypotheses"] if h["mechanism"] == mechanism and h["change_evidence_id"])


class PositiveAndNegativeControls(Base):
    def test_t1_t9_separated_brackets_resolve_only_under_rules_0_2(self):
        """T1/T9. Rules 0.1 order by the rollout's server-clock ``event`` stamp (unknown clock): unordered.
        Rules 0.2 order by its collector bracket against a log on the same (synthetic) collector clock."""
        v1, v2 = self.both(spec())
        self.assertEqual(v1["status"], "abstained")
        self.assertIn("ordering_unknown", v1["reasons"])
        self.assertEqual((v2["status"], v2["mechanism"]), ("resolved", "rollout_limit_reduction"))
        inv = self.run_case(spec(), 2)
        symptom_prereq = next(p for p in self.hypothesis(inv)["prerequisites"]
                              if p["key"] == "symptom_on_new_revision_after_rollout")
        self.assertEqual({(o["order"], o["basis"]) for o in symptom_prereq["orderings"]}, {("before", "same_domain")})
        self.assertEqual(inv.result["timeline"]["rule_version"], TIMELINE_RULES_VERSION_V2)
        self.assertEqual(inv.result["rule_versions"]["timeline-rules"], TIMELINE_RULES_VERSION_V2)

    def test_t8_ordering_without_causation_never_resolves(self):
        for name, roll in (("image-only rollout", rollout(field_changes=False)),
                           ("limit not lowered", rollout(after="60"))):
            with self.subTest(case=name):
                inv = self.run_case(spec(roll=roll), 2)
                outcome = inv.result["outcome"]
                self.assertEqual(outcome["status"], "abstained")
                self.assertNotEqual(self.hypothesis(inv)["status"], "supported")
                prereq = next(p for p in self.hypothesis(inv)["prerequisites"]
                              if p["key"] == "symptom_on_new_revision_after_rollout")
                self.assertEqual(prereq["result"], "satisfied")  # the order is established; causation is not

    def test_no_symptom_still_abstains(self):
        observations = spec()
        observations[("loki-a", "loki.checkout-api")] = []
        self.assertIn("no_symptom_observed", self.outcome(observations, 2)["reasons"])


class Brackets(Base):
    def test_t2_overlapping_and_touching_brackets_stay_unordered(self):
        for name, roll, log in (
                ("overlap", rollout(observed=("2026-11-12T10:02:30.000000000Z", 60_000_000_000)), symptom()),
                ("touch inside a millisecond", rollout(observed=("2026-11-12T10:02:59.999000000Z", 500_000)),
                 symptom(at="2026-11-12T10:02:59.999500000Z", precision_ns=100_000))):
            with self.subTest(case=name):
                outcome = self.outcome(spec(roll=roll, logs=log), 2)
                self.assertEqual(outcome["status"], "abstained")
                self.assertIn("ordering_unknown", outcome["reasons"])

    def test_t3_records_without_observed_keep_event_ordering(self):
        roll = rollout(observed=None)
        self.assertEqual(timeline.ordering_stamp(self._evidence(roll), TIMELINE_RULES_VERSION_V2).timestamp_kind, "event")
        v1, v2 = self.both(spec(roll=roll, pods=pod(observed=None)))
        self.assertEqual(v1, v2)  # without observed brackets both profiles conclude the same
        self.assertEqual(v2["status"], "abstained")

    def test_t4_a_stepped_collector_clock_fails_closed_without_fallback(self):
        """The server clock is declared (fixture) so ``event`` ordering would resolve under rules 0.1; under
        rules 0.2 the rollout's stepped collector bracket decides and nothing falls back to ``event``."""
        clocks = {SRV: ti.clock_domain(SRV, ti.DECLARED, 0, 0, ti.FIXTURE_DECLARED, ti.CONTINUOUS).to_record(),
                  NODE: ti.clock_domain(NODE, ti.DECLARED, 0, 0, ti.FIXTURE_DECLARED, ti.CONTINUOUS).to_record(),
                  COL: ti.clock_domain(COL, ti.UNKNOWN, continuity=ti.STEP_DECLARED).to_record()}
        observations = spec(logs=symptom(domain=NODE))
        v1 = self.outcome(observations, 1, clocks=clocks, log_domains=(NODE,))
        v2 = self.outcome(observations, 2, clocks=clocks, log_domains=(NODE,))
        self.assertEqual(v1["status"], "resolved")
        self.assertEqual(v2["status"], "abstained")
        self.assertIn("ordering_unknown", v2["reasons"])

    def test_t4_unknown_continuity_fails_closed(self):
        clocks = {COL: ti.clock_domain(COL, ti.UNKNOWN, continuity=ti.UNKNOWN).to_record()}
        self.assertEqual(self.outcome(spec(), 2, clocks=clocks)["status"], "abstained")

    def test_t5_unrelated_log_clocks_never_order_against_collector_brackets(self):
        clocks = {NODE: ti.clock_domain(NODE, ti.DECLARED, 1500, 200, ti.FIXTURE_DECLARED, ti.CONTINUOUS).to_record()}
        outcome = self.outcome(spec(logs=symptom(domain=NODE)), 2, clocks=clocks, log_domains=(NODE,))
        self.assertEqual(outcome["status"], "abstained")
        self.assertIn("ordering_unknown", outcome["reasons"])

    def test_t14_resource_versions_are_never_time(self):
        a = self._evidence(rollout(observed=("2026-11-12T10:02:00.000000000Z", 30_000_000_000), version="1000"))
        b = self._evidence(pod(observed=("2026-11-12T10:02:10.000000000Z", 1_000_000_000)))
        domains = {COL: ti.ClockDomain.from_record(ti.clock_domain(COL, ti.UNKNOWN,
                                                                   continuity=ti.CONTINUOUS).to_record())}
        self.assertEqual(int(a.source_version) < int(b.source_version), True)  # versions suggest an order...
        order = timeline.event_order(a, b, domains, TIMELINE_RULES_VERSION_V2)
        self.assertEqual(order.order, ti.UNORDERED)  # ...the brackets overlap, so there is none
        self.assertEqual(timeline.event_order(b, a, domains, TIMELINE_RULES_VERSION_V2).order, ti.UNORDERED)

    def _evidence(self, observation):
        fx = Fixture(2)
        return ev.observe(observation, source_id="k8s-a", registry=fx.registry,
                          kind_registry_version=ev.KIND_REGISTRY_VERSION_V3)


class Isolation(Base):
    def test_t6_other_namespaces_and_clusters_are_never_joined(self):
        for scope in ("b", "c"):
            with self.subTest(scope=scope):
                observations = {**spec(), **{k: v for k, v in spec(scope=scope).items() if not k[0].startswith("k8s")}}
                observations[("loki-a", "loki.checkout-api")] = []
                observations[(f"loki-{scope}", "loki.checkout-api")] = [symptom(scope=scope)]
                observations[("k8s-a", "k8s.pods")] = [pod()]
                outcome = self.outcome(observations, 2)
                self.assertEqual(outcome["status"], "abstained")
                self.assertIn("no_supported_hypothesis", outcome["reasons"])

    def test_brackets_from_two_sessions_are_refused_under_rules_0_2(self):
        observations = spec(pods=pod(observed_domain=COL2))
        inv1 = self.run_case(observations, 1, domains=(COL, COL2, SRV))  # rules 0.1 never read observed
        self.assertIn(inv1.result["outcome"]["status"], ("abstained", "resolved"))
        with self.assertRaises(Exception) as ctx:
            self.run_case(observations, 2, domains=(COL, COL2, SRV))
        self.assertIn("observed_clock_domains_mixed", repr(ctx.exception) + repr(ctx.exception.__cause__))


class GapsAndContradictions(Base):
    def test_t7_a_gap_keeps_the_hypothesis_unresolved(self):
        outcome = self.outcome(spec(), 2, partial=[("k8s-a", "k8s.deployments")])
        self.assertEqual(outcome["status"], "abstained")
        self.assertIn("limiting_evidence_gaps", outcome["reasons"])

    def test_t7_a_symptom_before_the_rollout_contradicts(self):
        outcome = self.outcome(spec(logs=symptom(at="2026-11-12T10:01:00Z")), 2)
        self.assertEqual(outcome["status"], "abstained")
        self.assertIn("contradicting_evidence_present", outcome["reasons"])


class VersionsAndReplay(Base):
    def test_t10_deterministic_under_each_profile(self):
        for profile in (1, 2):
            with self.subTest(profile=profile):
                a, b = self.run_case(spec(), profile), self.run_case(spec(), profile)
                self.assertEqual(a.result_bytes, b.result_bytes)
                self.assertEqual(a.result["rule_versions"], required_rule_versions(profile))
                self.assertEqual(a.result["engine_version"], "ca-engine/0.1-provisional")
                self.assertEqual(a.result["contract_version"], "ca-investigation-result/0.2-provisional")

    def test_t11_profile_1_keeps_timeline_rules_0_1(self):
        inv = self.run_case(spec(), 1)
        self.assertEqual(inv.result["timeline"]["rule_version"], TIMELINE_RULES_VERSION)

    def test_t12_profile_2_needs_contract_profile_3(self):
        observations = {k: [dict(o, times=[t for t in o["times"] if t["timestamp_kind"] != "observed"]) for o in v]
                        for k, v in spec().items()}
        inv = self.run_case(observations, 1, kinds=ev.KIND_REGISTRY_VERSION_V2)
        self.assertEqual(inv.result["rule_versions"]["timeline-rules"], TIMELINE_RULES_VERSION)
        with self.assertRaises(Exception) as ctx:
            self.run_case(observations, 2, kinds=ev.KIND_REGISTRY_VERSION_V2)
        self.assertIn("rule_profile_unsupported", repr(ctx.exception) + repr(ctx.exception.__cause__))

    def test_t12_unknown_rule_versions_are_refused(self):
        from cloud_autopsy.engine import rule_profile
        # 0.3 exists since the CA-P2-004g causal-scope guard (rule profile 3); 0.4 is still unknown.
        self.assertIsNone(rule_profile({**required_rule_versions(2), "timeline-rules": "ca-timeline-rules/0.4-provisional"}))
        self.assertIsNone(rule_profile({**required_rule_versions(1), "mechanism-catalog": "x/0.2-provisional"}))
        with self.assertRaises(ValueError):
            required_rule_versions(4)


if __name__ == "__main__":
    unittest.main()
