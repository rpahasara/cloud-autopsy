"""CA-P2-004g, item 3: reproduce why a real rollout still abstains apart from logs (characterization tests).

These tests pin today's fail-closed behaviour; they are not a proposal and change no policy. Each cause is
reproduced alone against the fake API, and the expected batch outcomes, reasons and counts are asserted:

1. A status-only Deployment update (no new revision) is a delivered change the converter does not turn
   into evidence (``no_new_revision``). Inside the proof it makes the Deployment batch
   ``partial`` / ``changes_withheld``.
2. A Pod first seen pending (no node, no container statuses) cannot be converted (``node_missing``,
   ``container_statuses_missing``); inside the proof it makes the Pod batch ``partial`` / ``changes_withheld``.
3. Every resource's initial list state is a ``partial`` / ``continuity_lost`` batch: a state at an unplaced
   moment, never coverage of changes.
4. The plan window spans the whole recording, beyond each acquisition's verified coverage, so every
   acquisition has coverage holes at the window's edges.

Each is a limiting gap, so the investigation abstains. ``docs/phase2/ca-p2-004/ca-p2-004g-completeness.md``
discusses what a change would require. Any change to the projection or completeness policy is a separate
decision for the product owner.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import _fake_api as F
import _fake_podlogs as FL
import _fake_watch as FW

from cloud_autopsy.app import bundle as B
from cloud_autopsy.app import create as C
from cloud_autopsy.collector import collect as co
from cloud_autopsy.collector import podlogs as PLC
from cloud_autopsy.collector import watch as wt

WATCH = wt.WatchConfig(session_seconds=2.0, probe_interval_s=0.2, idle_timeout_s=0.5, final_wait_s=1.5)
UID = "0b8e7c1e-0000-4000-8000-0000000c0001"


class Characterization(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ca-completeness-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        F.write_token(self.tmp)

    def run_session(self, cluster, steps, logs=False):
        self.addCleanup(getattr(cluster, "stop_all", lambda: None))
        FW.Mutator(steps, interval=0.3, delay=0.3).start()
        cfg = co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=self.tmp / "ca",
                                 token_file=self.tmp / "token", namespace=F.NAMESPACE,
                                 cluster_id="ca-kind-synthetic", recording_id="ca-completeness")
        kw = {"pod_logs": PLC.LogConfig(rotation_s=0.25, drain_wait_s=2.0, idle_timeout_s=2.0)} if logs else {}
        _, conversion, _ = co.run_watch(cfg, WATCH, self.tmp / "out", transport=cluster, rule_profile=2, **kw)
        self.conversion = conversion
        inv = C.investigate_offline(B.load(self.tmp / "out" / "bundle"))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        return {a["query_id"]: a for a in conversion.report["acquisitions"]}, inv.result

    def outcomes(self, query):
        return {(b["outcome"], b["reason"]) for b in self.conversion.batch_records if b["query_id"] == query}

    def test_1_a_status_only_deployment_update_makes_the_deployment_batch_partial(self):
        cluster = FW.FakeCluster(bookmark_interval=0.05)
        acquisitions, result = self.run_session(cluster, [lambda: cluster.touch("deployments")])
        self.assertEqual(acquisitions["k8s.deployments"]["unconverted"].get("no_new_revision"), 1)
        self.assertIn(("partial", "changes_withheld"), self.outcomes("k8s.deployments"))
        self.assertEqual(acquisitions["k8s.deployments"]["verified_coverage_ms"], 0)
        self.assertIn("limiting_evidence_gaps", result["outcome"]["reasons"])

    def test_2_a_pod_first_seen_pending_makes_the_pod_batch_partial(self):
        cluster = FL.LogCluster()

        def pending():
            obj = cluster.pod_object("checkout-api-7c9f8-p1", UID)
            del obj["spec"]["nodeName"]
            obj["status"] = {"phase": "Pending"}
            cluster._record("pods", "ADDED", obj)

        acquisitions, _ = self.run_session(cluster, [pending])
        unconverted = acquisitions["k8s.pods"]["unconverted"]
        self.assertTrue({"node_missing", "container_statuses_missing"} & set(unconverted), unconverted)
        self.assertIn(("partial", "changes_withheld"), self.outcomes("k8s.pods"))

    def test_3_and_4_list_state_and_window_edges_are_gaps_in_every_run(self):
        cluster = FW.FakeCluster(bookmark_interval=0.05)
        _, result = self.run_session(cluster, [])
        for query in ("k8s.deployments", "k8s.events", "k8s.pods", "k8s.replicasets"):
            self.assertIn(("partial", "continuity_lost"), self.outcomes(query), query)
        subjects = {(g["query_id"], g["subject"]) for g in result["gaps"]}
        self.assertTrue({("k8s.pods", "coverage"), ("k8s.deployments", "coverage")} & subjects, subjects)
        self.assertIn("limiting_evidence_gaps", result["outcome"]["reasons"])


if __name__ == "__main__":
    unittest.main()
