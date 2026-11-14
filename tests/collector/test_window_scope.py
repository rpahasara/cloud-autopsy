"""CA-P2-004g, M12d: the incident window replaces the plan window only when the proofs and the causal scope allow it.

``_window_decision`` (pure) is tested case by case with synthetic intervals and batches, then one recording 0.6
session against the fake API narrows for real: the plan window becomes the incident window declared before
collection, nothing is dropped, and replay re-derives the same bundle byte for byte.

Cases (product-owner list): 1 inside -> narrowed; 2 rollout and symptoms outside -> refused; 3 rollout outside,
symptom inside -> refused; 4 a contradicting symptom just outside -> refused and listed; 5 missing coverage in
the window -> refused; 6 no common verified interval -> refused; 7 an unproven tail -> refused.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import _fake_api as F
import _fake_podlogs as FL
import _fake_watch as FW

from cloud_autopsy.app import bundle as B
from cloud_autopsy.app import create as C
from cloud_autopsy.app import k8s_watch_recording as W
from cloud_autopsy.collector import collect as co
from cloud_autopsy.collector import podlogs as PLC
from cloud_autopsy.collector import watch as wt

DOMAIN = "ca-collector-cs-0123456789abcdef"
T0 = 1_794_600_000_000          # ms; the incident window is [T0 + 20 s, T0 + 140 s)
WINDOW = [T0 + 20_000, T0 + 140_000]


def iso_ns(ms):
    from cloud_autopsy.app import k8s_recording as K
    return K._ms_text(ms)[:-5] + ".000000000Z"


def obs(kind, at_ms, width_ms=1_000, template=None, ref=None):
    o = {"observation_kind": kind, "source_ref": ref or f"k8s:{kind}@{at_ms}",
         "times": [{"timestamp_kind": "observed", "raw": iso_ns(at_ms), "clock_domain_id": DOMAIN,
                    "declared_precision_ns": width_ms * 1_000_000}], "attributes": {}}
    if template:
        o["attributes"]["template"] = template
    return o


def rollout(at_ms):
    return obs("deployment_rollout", at_ms)


def symptom(at_ms):
    return obs("log_line", at_ms, template="POOL_EXHAUSTED")


def decide(observations, verified=(T0, T0 + 150_000), unclean=()):
    intervals = {"requested_incident_window_ms": WINDOW, "verified_interval_ms": list(verified) if verified else None,
                 "acquisitions_with_unclean_batches": list(unclean)}
    return W._window_decision(intervals, [{"query_id": "q", "observations": observations}], DOMAIN)


class Decision(unittest.TestCase):
    def test_1_rollout_and_symptoms_inside_the_window_may_narrow(self):
        d = decide([rollout(T0 + 30_000), symptom(T0 + 60_000), symptom(T0 + 90_000)])
        self.assertEqual((d["narrowed"], d["narrowing_refused"]), (True, []))

    def test_2_rollout_and_symptoms_entirely_outside_never_narrow(self):
        for at in (T0 + 1_000, T0 + 145_000):
            with self.subTest(at=at):
                d = decide([rollout(at), symptom(at + 2_000)])
                self.assertFalse(d["narrowed"])
                self.assertIn("relevant_evidence_outside_incident_window", d["narrowing_refused"])
                self.assertEqual(d["relevant_outside_count"], 2)

    def test_3_rollout_outside_symptom_inside_never_narrows(self):
        d = decide([rollout(T0 + 10_000), symptom(T0 + 60_000)])
        self.assertFalse(d["narrowed"])
        self.assertEqual([o["observation_kind"] for o in d["relevant_outside"]], ["deployment_rollout"])

    def test_4_a_contradicting_symptom_just_outside_is_listed_and_blocks(self):
        d = decide([symptom(T0 + 19_000), rollout(T0 + 30_000), symptom(T0 + 60_000)])   # ends 1 ms short
        self.assertFalse(d["narrowed"])
        self.assertEqual(d["relevant_outside"][0]["bracket_ms"], [T0 + 19_000, T0 + 19_999])
        straddling = decide([symptom(T0 + 19_500), rollout(T0 + 30_000)])                 # overlaps the start
        self.assertFalse(straddling["narrowed"])

    def test_5_missing_coverage_inside_the_window_never_narrows(self):
        for verified in ((T0 + 25_000, T0 + 150_000), (T0, T0 + 139_999), (T0, T0 + 25_000)):
            with self.subTest(verified=verified):
                d = decide([rollout(T0 + 30_000)], verified=verified)
                self.assertIn("incident_window_not_inside_verified_interval", d["narrowing_refused"])

    def test_6_no_common_verified_interval_never_narrows(self):
        d = decide([rollout(T0 + 30_000)], verified=None)
        self.assertIn("no_common_verified_interval", d["narrowing_refused"])

    def test_7_an_unproven_tail_is_never_treated_as_clean(self):
        d = decide([rollout(T0 + 30_000)], unclean=("k8s.events",))
        self.assertIn("unclean_batches", d["narrowing_refused"])

    def test_unbracketed_and_context_evidence_does_not_count_as_inside(self):
        listed = {"observation_kind": "deployment_rollout", "source_ref": "k8s:listed", "attributes": {},
                  "times": [{"timestamp_kind": "event", "raw": "2026-11-14T10:00:00Z", "clock_domain_id": "k8s-apiserver",
                             "declared_precision_ns": None}]}
        # A listed rollout has no bracket: it cannot satisfy or block the window rule, and the engine cannot
        # order it (tests/engine/test_window_safety.py proves it never supports a chain).
        self.assertTrue(decide([listed, rollout(T0 + 30_000)])["narrowed"])
        self.assertTrue(decide([obs("k8s_event", T0 + 1_000), obs("pod", T0 + 145_000)])["narrowed"])


class NarrowedSession(unittest.TestCase):
    def test_a_clean_session_narrows_keeps_everything_and_replays(self):
        tmp = Path(tempfile.mkdtemp(prefix="ca-window-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        F.write_token(tmp)
        cluster = FL.LogCluster()
        self.addCleanup(cluster.stop_all)
        for uid in [u for u, e in cluster.objects["events"].items() if e.get("involvedObject", {}).get("kind") == "Secret"]:
            del cluster.objects["events"][uid]
        cfg = co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=tmp / "ca", token_file=tmp / "token",
                                 namespace=F.NAMESPACE, cluster_id="ca-kind-synthetic", recording_id="ca-window")
        watch = wt.WatchConfig(session_seconds=3.0, probe_interval_s=0.2, idle_timeout_s=0.5, final_wait_s=1.5)
        _, conversion, _ = co.run_watch(cfg, watch, tmp / "out", transport=cluster, rule_profile=2,
                                        pod_logs=PLC.LogConfig(rotation_s=0.25, drain_wait_s=1.0, idle_timeout_s=1.0),
                                        incident_window=(1, 2))
        intervals = conversion.report["intervals"]
        self.assertTrue(intervals["narrowed"], intervals)
        self.assertEqual(intervals["plan_window_ms"], intervals["requested_incident_window_ms"])
        self.assertLessEqual(intervals["verified_interval_ms"][0], intervals["requested_incident_window_ms"][0])
        plan = json.loads((tmp / "out" / "bundle" / "plan.json").read_bytes())
        self.assertEqual(plan["window"], {k: v for k, v in conversion.plan_record["window"].items()})
        # Every batch is clean, claims exactly the incident window, and still states its whole proof.
        for b in conversion.batch_records:
            self.assertIn(b["outcome"], ("complete", "empty"))
            self.assertEqual(b["coverage"], conversion.plan_record["window"])
            self.assertLessEqual(b["coverage_basis"]["start_anchor"]["at"], b["coverage"]["start"])
            self.assertGreaterEqual(b["coverage_basis"]["end_anchor"]["at"], b["coverage"]["end"])
        # Nothing was dropped: the listed objects are all still there.
        rs = [o for b in conversion.batch_records if b["query_id"] == "k8s.replicasets" for o in b["observations"]]
        self.assertEqual(len(rs), len(cluster.objects["replicasets"]))
        W.verify_bundle(tmp / "out" / "recording", tmp / "out" / "bundle")   # replay: byte-identical
        inv = C.investigate_offline(B.load(tmp / "out" / "bundle"))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")     # no symptom: nothing to resolve
        self.assertIn("no_symptom_observed", inv.result["outcome"]["reasons"])
        self.assertEqual([g for g in inv.result["gaps"]], [])              # the window is fully verified


if __name__ == "__main__":
    unittest.main()
