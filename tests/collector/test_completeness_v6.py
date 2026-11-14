"""CA-P2-004g, recording 0.6 (M12a-c, M12d measurement): adversarial regression tests.

Unit tests of ``app.completeness.classify``, then end-to-end sessions against the fake API:
- each original abstention cause, separately and together;
- a status-only update never suppresses a genuine spec change (scale, strategy, a missing generation);
- pending init-container activity is never hidden by supersession;
- a symptom with no protocol lower bound (it may precede the change) is a gap, never silently unordered;
- no common verified interval is reported as such, and the run abstains (no window is fabricated);
- 0.5 recordings convert exactly as before (no classification, no intervals).
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import _fake_api as F
import _fake_podlogs as FL
import _fake_watch as FW

from cloud_autopsy.app import bundle as B
from cloud_autopsy.app import completeness as CM
from cloud_autopsy.app import create as C
from cloud_autopsy.collector import collect as co
from cloud_autopsy.collector import podlogs as PLC
from cloud_autopsy.collector import watch as wt

UID_A, UID_B = "0b8e7c1e-0000-4000-8000-0000000c0001", "0b8e7c1e-0000-4000-8000-0000000c0002"
DEP = "0b8e7c1e-0000-4000-8000-00000000d001"


def dep(gen=1, rev="2", digest="d1"):
    return {"metadata": {"uid": DEP, "generation": gen, "annotations": {"deployment.kubernetes.io/revision": rev}},
            "specDigest": digest}


def step(obj, reason=None, event="MODIFIED", in_proof=True, uid=DEP, rv="10"):
    return {"uid": uid, "rv": rv, "event": event, "object": obj, "reason": reason, "in_proof": in_proof}


def pod(phase="Pending", init=False, started=False, statuses=True):
    obj = {"metadata": {"uid": UID_A}, "spec": {"containers": [{"name": "checkout-api"}]}, "status": {"phase": phase}}
    if init:
        obj["spec"]["initContainers"] = [{"name": "init"}]
    if statuses:
        obj["status"]["containerStatuses"] = [{"started": started, "restartCount": 0}]
    return obj


class Classify(unittest.TestCase):
    def test_a_status_only_update_is_classified(self):
        steps = [step(dep(), event="LISTED"), step(dep(), "no_new_revision")]
        self.assertEqual(CM.classify("deployments", steps), {1: "status_only"})

    def test_a_genuine_spec_change_is_never_status_only(self):
        for name, later in (("scale (generation and spec digest change)", dep(gen=2, digest="d2")),
                            ("spec digest changed alone", dep(digest="d2")),
                            ("revision changed without conversion", dep(rev="3")),
                            ("generation missing", {**dep(), "metadata": {**dep()["metadata"], "generation": None}}),
                            ("digest missing", {**dep(), "specDigest": None})):
            with self.subTest(case=name):
                steps = [step(dep(), event="LISTED"), step(later, "no_new_revision")]
                self.assertEqual(CM.classify("deployments", steps), {})

    def test_a_generation_rise_is_accounted_only_by_a_later_rollout_at_that_generation(self):
        rising = step(dep(gen=2), "no_new_revision")
        rollout = step(dep(gen=2, rev="3"), None)
        self.assertEqual(CM.classify("deployments", [step(dep(), event="LISTED"), rising, rollout]),
                         {1: "accounted_by_rollout"})
        other_gen = step(dep(gen=3, rev="3"), None)
        self.assertEqual(CM.classify("deployments", [step(dep(), event="LISTED"), rising, other_gen]), {})
        self.assertEqual(CM.classify("deployments", [step(dep(), event="LISTED"), rising]), {})
        outside = step(dep(gen=2, rev="3"), None, in_proof=False)
        self.assertEqual(CM.classify("deployments", [step(dep(), event="LISTED"), rising, outside]), {})

    def test_no_comparison_across_a_deletion_or_without_a_previous_version(self):
        self.assertEqual(CM.classify("deployments", [step(dep(), "no_new_revision")]), {})
        steps = [step(dep(), event="LISTED"), step(dep(), event="DELETED"), step(dep(), "no_new_revision")]
        self.assertEqual(CM.classify("deployments", steps), {})

    def test_a_quiet_pending_pod_is_superseded_by_a_later_converted_observation(self):
        steps = [step(pod(), "node_missing", uid=UID_A), step(pod(phase="Running"), None, uid=UID_A)]
        self.assertEqual(CM.classify("pods", steps), {0: "superseded"})

    def test_supersession_never_hides_activity_deletion_or_failure(self):
        cases = {
            "init container in spec": [step(pod(init=True), "node_missing", uid=UID_A), step(pod("Running"), None, uid=UID_A)],
            "a container started": [step(pod(started=True), "node_missing", uid=UID_A), step(pod("Running"), None, uid=UID_A)],
            "an init container started": [step({**pod(), "status": {"phase": "Pending", "initContainerStatuses":
                                                                     [{"started": True}]}}, "container_statuses_missing", uid=UID_A),
                                          step(pod("Running"), None, uid=UID_A)],
            "not pending": [step(pod(phase="Unknown"), "node_missing", uid=UID_A), step(pod("Running"), None, uid=UID_A)],
            "deleted before conversion": [step(pod(), "node_missing", uid=UID_A), step(pod(), None, event="DELETED", uid=UID_A)],
            "never converted": [step(pod(), "node_missing", uid=UID_A)],
            "then another failure": [step(pod(), "node_missing", uid=UID_A), step(pod("Running"), "restart_count_invalid", uid=UID_A),
                                     step(pod("Running"), None, uid=UID_A)],
            "conversion outside the proof": [step(pod(), "node_missing", uid=UID_A),
                                             step(pod("Running"), None, uid=UID_A, in_proof=False)],
            "pending outside the proof": [step(pod(), "node_missing", uid=UID_A, in_proof=False),
                                          step(pod("Running"), None, uid=UID_A)],
            "another pod converts": [step(pod(), "node_missing", uid=UID_A), step(pod("Running"), None, uid=UID_B)],
            "a started-state field absent": [step({**pod(), "status": {"phase": "Pending", "containerStatuses": [{}]}},
                                                  "node_missing", uid=UID_A), step(pod("Running"), None, uid=UID_A)],
        }
        for name, steps in cases.items():
            with self.subTest(case=name):
                self.assertEqual(CM.classify("pods", steps), {})


WATCH = wt.WatchConfig(session_seconds=2.0, probe_interval_s=0.2, idle_timeout_s=0.5, final_wait_s=1.5)
LOGS = PLC.LogConfig(rotation_s=0.25, drain_wait_s=2.0, idle_timeout_s=2.0)


class Sessions(unittest.TestCase):
    """Recording 0.6 sessions against the fake API (with the pod-log fake, so profile 4)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ca-v6-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        F.write_token(self.tmp)
        self.cluster = FL.LogCluster()
        self.addCleanup(self.cluster.stop_all)
        d = self.cluster.objects["deployments"][DEP]
        d["metadata"]["generation"] = 1
        # The planted Event about a Secret is withheld by design; it is removed here so a clean starting state is
        # possible, and kept in test_a_withheld_listed_item_keeps_the_starting_state_partial.
        self.secret_events = {u: e for u, e in self.cluster.objects["events"].items()
                              if e.get("involvedObject", {}).get("kind") == "Secret"}
        for u in self.secret_events:
            del self.cluster.objects["events"][u]

    def run_v6(self, steps, window=(0, 2), faults=None, version6=True):
        if faults:
            self.cluster.faults.update(faults)
        FW.Mutator(steps, interval=0.3, delay=0.3).start()
        cfg = co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=self.tmp / "ca", token_file=self.tmp / "token",
                                 namespace=F.NAMESPACE, cluster_id="ca-kind-synthetic", recording_id="ca-v6")
        out = self.tmp / f"out{len(list(self.tmp.iterdir()))}"
        _, conversion, _ = co.run_watch(cfg, WATCH, out, transport=self.cluster, rule_profile=2, pod_logs=LOGS,
                                        incident_window=window if version6 else None)
        self.conversion = conversion
        inv = C.investigate_offline(B.load(out / "bundle"))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")   # nothing here may resolve
        return {a["query_id"]: a for a in conversion.report["acquisitions"]}, inv.result

    def outcomes(self, query):
        return {(b["outcome"], b["reason"]) for b in self.conversion.batch_records if b["query_id"] == query}

    def status_update(self):
        d = dict(self.cluster.objects["deployments"][DEP])
        d["status"] = {"conditions": [{"type": "Progressing", "reason": "NewReplicaSetAvailable",
                                       "lastUpdateTime": "2026-11-14T10:00:00Z"}]}
        self.cluster._record("deployments", "MODIFIED", d)

    def scale(self):
        import copy
        d = copy.deepcopy(self.cluster.objects["deployments"][DEP])
        d["metadata"]["generation"] += 1
        d["spec"]["replicas"] = d["spec"].get("replicas", 1) + 1
        self.cluster._record("deployments", "MODIFIED", d)

    def pending_then_scheduled(self, init=False, started=False):
        obj = self.cluster.pod_object("checkout-api-7c9f8-p1", UID_A)
        node = obj["spec"].pop("nodeName")
        statuses = obj.pop("status")
        obj["status"] = {"phase": "Pending"}
        if init:
            obj["spec"]["initContainers"] = [{"name": "migrate", "image": "busybox"}]
            obj["status"]["initContainerStatuses"] = [{"name": "migrate", "state": {"running": {}},
                                                       "restartCount": 0}] if started else []
        self.cluster._record("pods", "ADDED", obj)
        later = self.cluster.pod_object("checkout-api-7c9f8-p1", UID_A)
        later["spec"]["nodeName"] = node
        later["status"] = {**statuses, "phase": "Running"}
        if init:
            later["spec"]["initContainers"] = obj["spec"]["initContainers"]
        self.cluster.workloads[UID_A] = FL.Workload(self.cluster, UID_A, interval=self.cluster.interval).start()
        self.cluster._record("pods", "MODIFIED", later)

    def test_cause_1_a_status_only_update_no_longer_withholds(self):
        acquisitions, _ = self.run_v6([self.status_update])
        self.assertEqual(acquisitions["k8s.deployments"]["classified"].get("status_only"), 1)
        self.assertEqual(self.outcomes("k8s.deployments"), {("complete", None)})

    def test_a_scale_change_still_withholds(self):
        acquisitions, _ = self.run_v6([self.scale])
        self.assertEqual(acquisitions["k8s.deployments"]["classified"], {})
        self.assertIn(("partial", "changes_withheld"), self.outcomes("k8s.deployments"))

    def test_cause_2_a_quiet_pending_pod_is_superseded(self):
        acquisitions, _ = self.run_v6([self.pending_then_scheduled])
        self.assertEqual(acquisitions["k8s.pods"]["classified"].get("superseded"), 1)
        self.assertNotIn(("partial", "changes_withheld"), self.outcomes("k8s.pods"))
        self.assertIn(UID_A, {i[0] for i in acquisitions["k8s.pods"]["classified_items"]})   # provenance kept

    def test_pending_init_container_activity_is_never_hidden(self):
        acquisitions, result = self.run_v6([lambda: self.pending_then_scheduled(init=True, started=True)])
        self.assertEqual(acquisitions["k8s.pods"]["classified"], {})
        self.assertIn(("partial", "changes_withheld"), self.outcomes("k8s.pods"))
        gaps = {g[2] for g in self.conversion.report["pod_logs"]["gaps"]}
        self.assertIn("init_containers_not_collected", gaps)
        self.assertFalse(self.conversion.report["pod_logs"]["basis_emitted"])

    def test_cause_3_the_listed_state_opens_the_proven_batch(self):
        self.run_v6([])
        for query in ("k8s.deployments", "k8s.events", "k8s.pods", "k8s.replicasets"):
            self.assertNotIn(("partial", "continuity_lost"), self.outcomes(query), query)
        listed = [o for b in self.conversion.batch_records if b["query_id"] == "k8s.replicasets"
                  for o in b["observations"]]
        self.assertTrue(listed)
        # listed state carries no observed bracket: it is never presented as witnessed during the segment
        self.assertTrue(all(all(t["timestamp_kind"] != "observed" for t in o["times"]) for o in listed))

    def test_cause_4_and_all_together_the_window_edges_remain_and_are_reported(self):
        acquisitions, result = self.run_v6([self.status_update, self.pending_then_scheduled])
        intervals = self.conversion.report["intervals"]
        self.assertIsNotNone(intervals["verified_interval_ms"])
        plan_window = intervals["plan_window_ms"]
        verified = intervals["verified_interval_ms"]
        self.assertTrue(plan_window[0] < verified[0] or verified[1] < plan_window[1])   # never narrowed
        subjects = {g["subject"] for g in result["gaps"]}
        self.assertIn("coverage", subjects)                                          # the edges stay gaps
        self.assertIn("limiting_evidence_gaps", result["outcome"]["reasons"])

    def test_a_symptom_with_no_lower_bound_is_a_gap(self):
        early = FL.Workload(self.cluster, UID_B, interval=self.cluster.interval)
        early.symptom = True
        self.cluster.workloads[UID_B] = early
        self.cluster._record("pods", "ADDED", self.cluster.pod_object("checkout-api-7c9f8-e1", UID_B))
        early.start()
        import time
        time.sleep(0.3)   # symptom lines written before the session: no protocol lower bound exists
        self.run_v6([])
        gaps = {(g[0], g[2]) for g in self.conversion.report["pod_logs"]["gaps"]}
        self.assertIn((UID_B, "symptom_unplaced"), gaps)
        self.assertFalse(self.conversion.report["pod_logs"]["basis_emitted"])

    def test_no_common_verified_interval_abstains_without_a_fabricated_window(self):
        self.run_v6([], faults={"replicasets": {"list_status": 500}})
        intervals = self.conversion.report["intervals"]
        self.assertIsNone(intervals["verified_interval_ms"])
        self.assertFalse(intervals["requested_inside_verified"])

    def test_a_withheld_listed_item_keeps_the_starting_state_partial(self):
        self.cluster.objects["events"].update(self.secret_events)
        acquisitions, _ = self.run_v6([])
        self.assertEqual(acquisitions["k8s.events"]["withheld"].get("list"), 1)
        self.assertIn(("partial", "continuity_lost"), self.outcomes("k8s.events"))
        self.assertIsNone(self.conversion.report["intervals"]["verified_interval_ms"])

    def test_a_0_5_recording_is_unchanged(self):
        acquisitions, _ = self.run_v6([self.status_update], version6=False)
        self.assertNotIn("intervals", self.conversion.report)
        self.assertNotIn("classified", acquisitions["k8s.deployments"])
        self.assertIn(("partial", "changes_withheld"), self.outcomes("k8s.deployments"))
        self.assertIn(("partial", "continuity_lost"), self.outcomes("k8s.pods"))


if __name__ == "__main__":
    unittest.main()
