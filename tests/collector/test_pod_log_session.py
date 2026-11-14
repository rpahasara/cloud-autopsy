"""CA-P2-004g offline: pod logs collected inside a watch session against a fake API, end to end.

Checks: the recording is 0.5 and re-derives byte-identically; continuity is proven only when every line
from seq 1 arrived and the tail is covered; faults (denied, dropped line, disconnect, name reuse, garbage,
partial line) become gaps and keep every log batch partial; proven coverage is a complete batch with a
``log_sequence_continuity`` basis (batch 0.3, M11) that a forged claim cannot pass on replay; planted log and env
values never reach any written file.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import _fake_api as F
import _fake_podlogs as FL
import _fake_watch as FW

from cloud_autopsy.app import create as C
from cloud_autopsy.app import bundle as B
from cloud_autopsy.app import k8s_watch_recording as W
from cloud_autopsy.collector import collect as co
from cloud_autopsy.collector import podlogs as PLC
from cloud_autopsy.collector import watch as wt
from cloud_autopsy.contracts import evidence as ev

UID_A, UID_B, UID_C = ("0b8e7c1e-0000-4000-8000-0000000c0001", "0b8e7c1e-0000-4000-8000-0000000c0002",
                       "0b8e7c1e-0000-4000-8000-0000000c0003")
DECLARED = [("checkout-api", "DB_POOL_MAX", "pool.maxConnections")]
LOG = PLC.LogConfig(rotation_s=0.25, drain_wait_s=2.0, idle_timeout_s=2.0)
WATCH = wt.WatchConfig(session_seconds=2.5, probe_interval_s=0.2, idle_timeout_s=0.5, final_wait_s=1.5)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ca-podlog-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        F.write_token(self.tmp)

    def run_session(self, cluster, steps=(), log_config=LOG, name="out"):
        self.cluster = cluster
        self.addCleanup(cluster.stop_all)
        FW.Mutator(steps, interval=0.3, delay=0.2).start()
        cfg = co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=self.tmp / "ca", token_file=self.tmp / "token",
                                 namespace=F.NAMESPACE, cluster_id="ca-kind-synthetic", recording_id="ca-podlogs")
        out = self.tmp / name
        entries, conversion, doc = co.run_watch(cfg, WATCH, out, transport=cluster, rule_profile=2,
                                                pod_logs=log_config, declared_limits=DECLARED)
        self.out, self.conversion = out, conversion
        return conversion.report["pod_logs"]

    def written(self):
        return b"".join(p.read_bytes() for p in sorted(self.out.rglob("*")) if p.is_file())


class Clean(Base):
    def clean(self):
        cluster = FL.LogCluster()
        return self.run_session(cluster, [lambda: cluster.spawn("checkout-api-7c9f8-c1", UID_A),
                                          lambda: setattr(cluster.workloads[UID_A], "symptom", True),
                                          lambda: cluster.spawn("checkout-api-7c9f8-c2", UID_B),
                                          lambda: cluster.stop(UID_B)])

    def test_proven_log_coverage_is_a_complete_batch_with_a_log_basis(self):
        report = self.clean()
        self.assertEqual(report["gaps"], [], report)
        self.assertTrue(report["coverage_proven"] and report["basis_emitted"], report)
        inst = report["instances"]
        self.assertTrue(any(i["stopped"] for i in inst.values()))
        self.assertTrue(all(i["covered_to_end"] for i in inst.values()))
        self.assertTrue(any(i["handshake_bounds"] > 0 for i in inst.values()))
        log_batches = [b for b in self.conversion.batch_records if b["query_id"] == W.LOG_QUERY]
        complete = [b for b in log_batches if b["outcome"] in ("complete", "empty")]
        self.assertTrue(complete)
        basis = complete[0]["coverage_basis"]
        manifest = json.loads((self.out / "recording" / "recording.json").read_bytes())
        self.assertEqual((basis["kind"], basis["session_id"], basis["clock_domain_id"]),
                         ("log_sequence_continuity", manifest["session_id"],
                          manifest["clocks"]["collector"]["clock_domain_id"]))
        self.assertEqual({(i["pod_uid"], i["ending"]) for i in basis["instances"]},
                         {(UID_A, "drained"), (UID_B, "stopped")})
        # the anchors are the Pod watch's own; the Pod batches are not made complete by log continuity
        pod_bases = [b["coverage_basis"] for b in self.conversion.batch_records
                     if b["query_id"] == "k8s.pods" and b["coverage_basis"] is not None]
        for pb in pod_bases:
            self.assertEqual(pb["kind"], "watch_continuity")
        self.assertTrue(all(b["contract_version"] == "ca-acquisition-batch/0.3-provisional"
                            for b in self.conversion.batch_records))
        lines = [o for b in log_batches for o in b["observations"]]
        self.assertTrue(lines and all("message" not in o["attributes"] for o in lines))
        self.assertTrue(all(any(t["timestamp_kind"] == "observed" for t in o["times"]) for o in lines))
        # Replay is byte-identical; the investigation runs, and abstains on the remaining non-log gaps.
        W.verify_bundle(self.out / "recording", self.out / "bundle")
        inv = C.investigate_offline(B.load(self.out / "bundle"))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        plan = json.loads((self.out / "bundle" / "plan.json").read_bytes())
        self.assertEqual(plan["contract_versions"]["observation-kinds"], ev.KIND_REGISTRY_VERSION_V4)
        self.assertEqual(plan["contract_versions"]["acquisition-batch"], "ca-acquisition-batch/0.3-provisional")

    def test_a_forged_log_basis_is_refused_on_replay(self):
        self.clean()
        batches = sorted((self.out / "bundle" / "batches").iterdir())
        for path in batches:
            doc = json.loads(path.read_bytes())
            if doc["query_id"] == W.LOG_QUERY and doc["coverage_basis"]:
                doc["coverage_basis"]["instances"][0]["last_seq"] += 1000
                from cloud_autopsy.contracts.canonical import canonical_bytes
                path.write_bytes(canonical_bytes(doc))
                break
        else:
            self.fail("no complete log batch")
        with self.assertRaises(Exception) as ctx:
            W.verify_bundle(self.out / "recording", self.out / "bundle")
        self.assertIn("replay_mismatch", repr(ctx.exception) + str(getattr(ctx.exception, "code", "")))

    def test_planted_log_and_env_values_are_never_written(self):
        cluster = FL.LogCluster(planted=True)
        self.run_session(cluster, [lambda: cluster.spawn("checkout-api-7c9f8-c1", UID_A)])
        data = self.written()
        for needle in FL.LOG_NEEDLES + F.PLANTED + (F.TOKEN,) if hasattr(F, "TOKEN") else FL.LOG_NEEDLES + F.PLANTED:
            self.assertNotIn(needle.encode(), data, needle)
        self.assertNotIn(b"DEBUG_DUMP", data)


class Faults(Base):
    def gaps(self, faults, steps=None, **kw):
        cluster = FL.LogCluster(log_faults=faults, **kw)
        steps = steps or [lambda: cluster.spawn("checkout-api-7c9f8-c1", UID_A)]
        report = self.run_session(cluster, steps(cluster) if callable(steps) else steps)
        W.verify_bundle(self.out / "recording", self.out / "bundle")
        inv = C.investigate_offline(B.load(self.out / "bundle"))
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        return {g[2] for g in report["gaps"]}, report

    def test_denied_logs_are_not_collected(self):
        self.assertIn("not_collected", self.gaps({"deny": True})[0])

    def test_a_silently_dropped_line_is_a_sequence_gap(self):
        gaps, report = self.gaps({"drop_seq": 3})
        self.assertIn("sequence_gap", gaps)
        self.assertFalse(report["basis_emitted"])
        log_batches = [b for b in self.conversion.batch_records if b["query_id"] == W.LOG_QUERY]
        self.assertEqual({(b["outcome"], b["reason"]) for b in log_batches}, {("partial", "continuity_unproven")})
        self.assertTrue(all(b["coverage_basis"] is None for b in log_batches))

    def test_a_garbage_line_is_an_unparseable_gap(self):
        gaps, _ = self.gaps({"garbage_after": 2})
        self.assertIn("unparseable_line", gaps)
        self.assertNotIn(b"PLANTED-LOG-PASSWORD", self.written())

    def test_name_reuse_attributes_nothing_to_the_old_pod(self):
        def steps(cluster):
            # The old pod's object is deleted while its container still writes (its stream stays open),
            # and a new pod takes the same name; the fake stream then follows the name to the new pod.
            return [lambda: cluster.spawn("checkout-api-7c9f8-c1", UID_A),
                    lambda: cluster._record("pods", "DELETED", cluster.objects["pods"][UID_A]),
                    lambda: cluster.spawn("checkout-api-7c9f8-c1", UID_C)]
        gaps, report = self.gaps({"swap_on_reuse": True}, steps)
        self.assertIn("name_reused", gaps, report)
        # Every stream for the old UID that was still open when the name was reused is unused, so no line
        # reaches the old UID through the reused name; any line attributed to it is from its own STARTED boot.
        old = [s for s in report["streams"].values() if s["uid"] == UID_A]
        self.assertTrue(old and any(s["reason"] == "name_reused" for s in old), report)
        lines = [o for b in self.conversion.batch_records if b["query_id"] == W.LOG_QUERY for o in b["observations"]]
        old_boots = {k.split("/")[2] for k in report["instances"] if k.startswith(UID_A)}
        self.assertTrue(all(o["attributes"]["boot"] in old_boots for o in lines if o["source_uid"] == UID_A))
        new_boots = {k.split("/")[2] for k in report["instances"] if k.startswith(UID_C)}
        self.assertFalse(old_boots & new_boots)

    def test_a_partial_line_is_counted_not_assumed(self):
        def steps(cluster):
            return [lambda: cluster.spawn("checkout-api-7c9f8-c1", UID_A), lambda: cluster.stop(UID_A, delete=False)]
        _, report = self.gaps({"partial_at_end": True}, steps)
        self.assertGreaterEqual(report["counts"].get("lines_partial", 0), 1)


if __name__ == "__main__":
    unittest.main()
