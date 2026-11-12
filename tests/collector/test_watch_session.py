"""CA-P2-004f offline: list + watch sessions against a fake API (in-process and over loopback TLS).

Every scenario checks what matters: coverage only where a probe was proven, every other period a
gap, the recording re-derives byte-identically, and no planted value, Status message or continue
token is written. Short bounds keep each session to a couple of seconds.
"""

import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

import _fake_api as F
import _fake_watch as FW

from cloud_autopsy.app import k8s_watch_recording as W
from cloud_autopsy.collector import client as cl
from cloud_autopsy.collector import collect as co
from cloud_autopsy.collector import watch as wt
from cloud_autopsy.contracts import acquisition as acq

QUICK = dict(session_seconds=1.6, probe_interval_s=0.1, idle_timeout_s=0.4, final_wait_s=0.8)


def config(tmp, recording_id="ca-watch-test"):
    return co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=tmp / "ca.crt", token_file=tmp / "token",
                              namespace="ca-demo", cluster_id="ca-kind-synthetic", recording_id=recording_id)


class Session(unittest.TestCase):
    def run_watch(self, cluster, steps=(), stop=None, on_signal=None, **bounds):
        tmp = F.tempdir(self, "ca-watch-session-")
        if steps:
            FW.Mutator(steps, interval=0.12, delay=0.35).start()
        wconfig = wt.WatchConfig(**{**QUICK, **bounds})
        entries, conversion, report = co.run_watch(config(tmp), wconfig, tmp / "out", transport=cluster, stop=stop,
                                                   on_signal=on_signal)
        self.assertEqual(F.scan([tmp / "out"]), set(), "a planted value was written")
        self.assertNotIn(FW.PLANTED_TOKEN.encode(), b"".join(p.read_bytes() for p in (tmp / "out").rglob("*")
                                                             if p.is_file()))
        W.verify_bundle(tmp / "out" / "recording", tmp / "out" / "bundle")  # replay: byte-identical
        acquisitions = {a["query_id"]: a for a in conversion.report["acquisitions"]}
        batches = {}
        for record in conversion.batch_records:
            batches.setdefault(record["query_id"], []).append(record)
        return entries, acquisitions, batches, report

    def assert_honest(self, batches):
        """Coverage claims only with a basis; nothing withheld is complete or empty."""
        for records in batches.values():
            for r in records:
                if r["outcome"] in (acq.COMPLETE, acq.EMPTY):
                    self.assertIsNotNone(r["coverage_basis"])
                    self.assertEqual(r["coverage"]["start"], r["coverage_basis"]["start_anchor"]["at"])
                    self.assertEqual(r["coverage"]["end"], r["coverage_basis"]["end_anchor"]["at"])
                else:
                    self.assertIsNone(r["coverage_basis"])

    def test_a_healthy_session_proves_coverage_for_every_resource(self):
        cluster = FW.FakeCluster(bookmark_interval=0.08)
        steps = [lambda: cluster.touch("pods"), lambda: cluster.add_event("ev-1"), lambda: cluster.touch("replicasets"),
                 lambda: cluster.delete("pods", 1)]
        entries, acquisitions, batches, report = self.run_watch(cluster, steps)
        self.assert_honest(batches)
        for query, a in acquisitions.items():
            with self.subTest(query=query):
                self.assertGreater(a["verified_coverage_ms"], 0)
                self.assertTrue(a["segments"][0]["proven"])
        self.assertGreater(report["verified_coverage_ms"], 0)
        kinds = {o["observation_kind"] for r in batches["k8s.pods"] for o in r["observations"]}
        self.assertIn("k8s_object_deleted", kinds)
        observed = [t for r in batches["k8s.pods"] if r["outcome"] == acq.COMPLETE for o in r["observations"]
                    for t in o["times"] if t["timestamp_kind"] == "observed"]
        self.assertTrue(observed)
        self.assertTrue(all(t["clock_domain_id"] == co.COLLECTOR_CLOCK_DOMAIN for t in observed))

    def test_bookmarks_and_events_alone_never_cover_time(self):
        cluster = FW.FakeCluster(faults={r: {"probe_status": 500} for r in FW.KINDS}, bookmark_interval=0.05)
        _, acquisitions, batches, report = self.run_watch(cluster, [lambda: cluster.touch("pods")])
        self.assertEqual(report["verified_coverage_ms"], 0)
        self.assertFalse([r for rs in batches.values() for r in rs if r["outcome"] in (acq.COMPLETE, acq.EMPTY)])
        self.assertIn("continuity_unproven", {r["reason"] for r in batches["k8s.pods"]})

    def test_a_silent_watch_proves_nothing(self):
        cluster = FW.FakeCluster(faults={r: {"no_bookmarks": True} for r in FW.KINDS})
        _, _, batches, report = self.run_watch(cluster)
        self.assertEqual(report["verified_coverage_ms"], 0)
        self.assertFalse([r for rs in batches.values() for r in rs if r["outcome"] in (acq.COMPLETE, acq.EMPTY)])

    def test_an_accepted_resume_keeps_continuity(self):
        cluster = FW.FakeCluster(faults={"pods": {"eof_after": 3}}, bookmark_interval=0.08)
        entries, acquisitions, batches, _ = self.run_watch(cluster, [lambda: cluster.touch("pods")])
        types = [e["type"] for e in entries["pods"]]
        self.assertIn("disconnect", types)
        self.assertEqual(types.count("list"), 1)  # one segment: the resume continued it
        self.assertTrue(acquisitions["k8s.pods"]["segments"][0]["proven"])
        self.assertEqual(acquisitions["k8s.pods"]["segments"][0]["reconnects"], 1)
        self.assert_honest(batches)

    def test_clean_server_timeouts_do_not_exhaust_the_reconnect_budget(self):
        """Seen on kind: watches the server ends cleanly (timeoutSeconds) are resumed, not counted as faults."""
        cluster = FW.FakeCluster(faults={r: {"eof_every": 2} for r in FW.KINDS}, bookmark_interval=0.05)
        _, acquisitions, batches, _ = self.run_watch(cluster, [lambda: cluster.touch("pods")], max_reconnects=1)
        for query, a in acquisitions.items():
            with self.subTest(query=query):
                self.assertNotEqual(a["segments"][-1]["end"], "reconnects_exhausted")
                self.assertEqual(len(a["segments"]), 1)
        self.assertTrue(acquisitions["k8s.replicasets"]["segments"][0]["proven"])
        self.assert_honest(batches)

    def test_a_refused_resume_relists_and_leaves_a_gap(self):
        cluster = FW.FakeCluster(faults={"pods": {"eof_after": 3, "gone_on_resume": True}}, bookmark_interval=0.08)
        entries, acquisitions, batches, _ = self.run_watch(cluster, [lambda: cluster.touch("pods")])
        segments = acquisitions["k8s.pods"]["segments"]
        self.assertGreaterEqual(len(segments), 2)
        self.assertEqual(segments[0]["end"], "expired")
        self.assert_honest(batches)
        complete = [r for r in batches["k8s.pods"] if r["outcome"] in (acq.COMPLETE, acq.EMPTY)]
        ends = sorted((r["coverage"]["start"], r["coverage"]["end"]) for r in complete)
        for (_, end), (start, _) in zip(ends, ends[1:]):
            self.assertLess(end, start, "verified coverage must not bridge a relist")

    def test_an_expired_watch_event_relists(self):
        cluster = FW.FakeCluster(faults={"events": {"error_410_after": 2}}, bookmark_interval=0.08)
        _, acquisitions, batches, _ = self.run_watch(cluster)
        self.assertEqual(acquisitions["k8s.events"]["segments"][0]["end"], "expired")
        self.assertGreaterEqual(len(acquisitions["k8s.events"]["segments"]), 2)
        self.assert_honest(batches)

    def test_a_revoked_binding_ends_the_resource_as_a_gap(self):
        cluster = FW.FakeCluster(faults={"pods": {"eof_after": 1, "deny_watch_after": 1}}, bookmark_interval=0.05)
        _, acquisitions, batches, _ = self.run_watch(cluster)
        self.assertEqual(acquisitions["k8s.pods"]["segments"][-1]["end"], "denied")
        self.assert_honest(batches)

    def test_invalid_streams_end_the_segment(self):
        for fault, code in (("garbage_after", "invalid_line"), ("oversize_after", "line_too_large"),
                            ("regress_after", "rv_regression"), ("foreign_after", "namespace_mismatch")):
            with self.subTest(fault=fault):
                cluster = FW.FakeCluster(faults={"pods": {fault: 1}}, bookmark_interval=0.05)
                _, acquisitions, batches, _ = self.run_watch(cluster, max_line_bytes=4096)
                self.assertEqual(acquisitions["k8s.pods"]["segments"][-1]["end"], code)
                self.assert_honest(batches)

    def test_the_event_limit_truncates(self):
        cluster = FW.FakeCluster(bookmark_interval=0.08)
        steps = [lambda: cluster.touch("pods", n) for n in range(6)]
        _, acquisitions, batches, _ = self.run_watch(cluster, steps, max_events=2)
        self.assertEqual(acquisitions["k8s.pods"]["segments"][-1]["end"], "event_limit")
        last = batches["k8s.pods"][-1]
        self.assertEqual((last["outcome"], last["reason"], last["truncation"]["truncated"]),
                         (acq.PARTIAL, "event_limit", True))

    def test_a_withheld_change_is_never_complete(self):
        cluster = FW.FakeCluster(bookmark_interval=0.08)
        steps = [lambda: cluster.add_event("secret-ev", "FailedMount", "Secret", "planted-secret-name-0b2")]
        _, acquisitions, batches, _ = self.run_watch(cluster, steps)
        self.assertEqual(acquisitions["k8s.events"]["withheld"].get("secret_event"), 1)
        reasons = {r["reason"] for r in batches["k8s.events"]}
        self.assertTrue({"changes_withheld", "continuity_unproven"} & reasons)
        self.assert_honest(batches)

    def test_a_denied_list_is_denied(self):
        cluster = FW.FakeCluster(faults={"pods": {"list_status": 403}}, bookmark_interval=0.08)
        _, acquisitions, batches, _ = self.run_watch(cluster)
        self.assertEqual([(r["outcome"], r["reason"]) for r in batches["k8s.pods"]],
                         [(acq.DENIED, "authorization_denied")])

    def test_a_signal_ends_the_session_gracefully(self):
        cluster = FW.FakeCluster(bookmark_interval=0.08)
        stop = threading.Event()
        threading.Timer(0.6, stop.set).start()
        entries, acquisitions, _, _ = self.run_watch(cluster, stop=stop, on_signal=lambda: True, session_seconds=10)
        self.assertEqual({a["segments"][-1]["end"] for a in acquisitions.values()}, {"signal"})
        self.assertEqual({e["type"] for e in entries["pods"]} - {"list", "watch_open", "probe", "bookmark", "end"},
                         set())


@unittest.skipUnless(F.openssl(), "openssl is needed to generate a throwaway test certificate")
class OverTls(unittest.TestCase):
    def test_a_session_over_verified_loopback_tls(self):
        tmp = F.tempdir(self, "ca-watch-tls-")
        cert, key = F.make_cert(tmp)
        cluster = FW.FakeCluster(bookmark_interval=0.08)
        server = FW.WatchTlsServer(cluster, cert, key)
        self.addCleanup(server.close)
        FW.Mutator([lambda: cluster.touch("pods"), lambda: cluster.add_event("tls-ev")], delay=0.4).start()
        cfg = co.CollectorConfig(server=f"https://127.0.0.1:{server.port}", ca_file=cert, token_file=F.write_token(tmp),
                                 namespace="ca-demo", cluster_id="ca-kind-synthetic", recording_id="ca-watch-tls")
        wconfig = wt.WatchConfig(**{**QUICK, "session_seconds": 3.0, "final_wait_s": 1.5})
        _, conversion, report = co.run_watch(cfg, wconfig, tmp / "out")
        self.assertGreater(report["verified_coverage_ms"], 0)
        self.assertEqual(F.scan([tmp / "out"]), set())
        token = (tmp / "token").read_bytes()
        self.assertNotIn(token, b"".join(p.read_bytes() for p in (tmp / "out").rglob("*") if p.is_file()))


class Allowlist(unittest.TestCase):
    def test_only_allowlisted_watch_paths_can_be_formed(self):
        path = cl.build_watch_path("pods", "ca-demo", "12345678901234567890123", 300)
        self.assertEqual(path, "/api/v1/namespaces/ca-demo/pods?watch=1&resourceVersion=12345678901234567890123"
                               "&allowWatchBookmarks=true&timeoutSeconds=300")
        for args in (("secrets", "ca-demo", "1", 10), ("configmaps", "ca-demo", "1", 10), ("pods", "Bad", "1", 10),
                     ("pods", "ca-demo", "01", 10), ("pods", "ca-demo", "1&x=y", 10), ("pods", "ca-demo", "1", 0),
                     ("pods", "ca-demo", "1", 601), ("pods", "ca-demo", "1" * 129, 10)):
            with self.subTest(args=args), self.assertRaises(cl.CollectorError):
                cl.build_watch_path(*args)

    def test_bounds_are_checked(self):
        for bad in (dict(session_seconds=0.5), dict(session_seconds=601), dict(max_events=0),
                    dict(max_line_bytes=10), dict(max_reconnects=11), dict(probe_interval_s=0)):
            with self.subTest(bad=bad), self.assertRaises(cl.CollectorError):
                wt.WatchConfig(**bad).check()


if __name__ == "__main__":
    unittest.main()
