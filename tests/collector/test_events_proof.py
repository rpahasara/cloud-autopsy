"""CA-P2-004g: why the Events acquisition stops proving coverage (deterministic reproduction).

A probe is proven only when the watch later delivers an event or a BOOKMARK at or above the probe's
resourceVersion. kube-apiserver serves Events without a watch cache by default (its default watch-cache size
for ``events`` is 0), and BOOKMARKs come from the watch cache, so an Events watch receives no BOOKMARKs. Once
Events go quiet, nothing delivers a higher resourceVersion: every later probe stays unproven, although the
watch is healthy and open. Kubernetes does not guarantee periodic BOOKMARKs either way.

The fake API reproduces exactly that: Events without BOOKMARKs (the ``no_bookmarks`` fault), activity early
in the session, then quiet; Pods with BOOKMARKs. The collector behaves correctly: it claims nothing it
cannot prove. This test pins that behaviour and the diagnostic facts the kind job prints.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import _fake_api as F
import _fake_watch as FW

from cloud_autopsy.app import stream_facts as SF
from cloud_autopsy.collector import collect as co
from cloud_autopsy.collector import watch as wt

WATCH = wt.WatchConfig(session_seconds=2.5, probe_interval_s=0.2, idle_timeout_s=0.5, final_wait_s=1.0)


class QuietEventsWithoutBookmarks(unittest.TestCase):
    def test_a_quiet_watch_without_bookmarks_proves_nothing_after_its_last_event(self):
        tmp = Path(tempfile.mkdtemp(prefix="ca-events-proof-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        F.write_token(tmp)
        cluster = FW.FakeCluster(faults={"events": {"no_bookmarks": True}}, bookmark_interval=0.05)
        FW.Mutator([lambda: cluster.add_event("e1"), lambda: cluster.add_event("e2")], interval=0.1, delay=0.3).start()
        # The rest of the cluster keeps advancing the global revision (as leases and node status do on kind).
        FW.Mutator([lambda: cluster.touch("replicasets")] * 25, interval=0.1, delay=0.5).start()
        cfg = co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=tmp / "ca", token_file=tmp / "token",
                                 namespace=F.NAMESPACE, cluster_id="ca-kind-synthetic", recording_id="ca-events-proof")
        _, conversion, _ = co.run_watch(cfg, WATCH, tmp / "out", transport=cluster)
        facts = SF.facts(tmp / "out" / "recording")

        events, pods = facts["events"][0], facts["pods"][0]
        # The Events watch was healthy and quiet: one segment, ended by the session; its only disconnects are the
        # collector's own idle timeouts on a silent stream, each resumed from the last delivered resourceVersion
        # (no relist, no failure); no BOOKMARKs; its last delivery is an event, and the probes after it stay unproven.
        self.assertEqual((len(facts["events"]), events["end"], events["bookmarks"]), (1, "session_end", 0))
        self.assertLessEqual(set(events["disconnects"]), {"idle_timeout"})
        self.assertEqual(events["watch_opens"], 1 + len(events["disconnects"]))
        self.assertEqual(events["last_delivered"][1], "ADDED")
        self.assertGreater(events["probes_unproven"], 0)
        self.assertFalse(events["final_probe"]["proven"])
        # The Pod watch, with BOOKMARKs, proves its final probe.
        self.assertGreater(pods["bookmarks"], 0)
        self.assertTrue(pods["final_probe"]["proven"])

        acquisitions = {a["query_id"]: a for a in conversion.report["acquisitions"]}
        self.assertLess(acquisitions["k8s.events"]["verified_coverage_ms"], acquisitions["k8s.pods"]["verified_coverage_ms"])
        tails = {(b["outcome"], b["reason"]) for b in conversion.batch_records if b["query_id"] == "k8s.events"}
        self.assertTrue(tails & {("partial", "continuity_unproven")} or
                        acquisitions["k8s.events"]["verified_coverage_ms"] < acquisitions["k8s.pods"]["verified_coverage_ms"])


if __name__ == "__main__":
    unittest.main()
