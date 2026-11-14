"""CA-P2-004g, recording 0.7: Kubernetes Events explicitly not collected (product-owner decision, scoped).

- The choice is declared before collection, needs the incident mode (an incident window), and is recorded in the
  manifest (``not_collected``), the source registry (no Events query; the registry ID says so), the run plan's
  expected acquisitions and the conversion report.
- No Events coverage is claimed and no Events gap is made; the verified interval uses only the declared
  acquisitions; the Events-enabled mode, and 0.4-0.6 recordings, are unchanged.
- A 0.7 manifest that declares anything else, or still carries an Events stream, is refused.
- The API states what the sealed plan declared: ``kubernetes_events`` is ``not_collected``, never a coverage claim,
  and the dashboard says exactly "Kubernetes Events: Not collected".
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import _fake_api as F
import _fake_podlogs as FL

from cloud_autopsy.app import bundle as B
from cloud_autopsy.app import create as C
from cloud_autopsy.app import k8s_recording as K
from cloud_autopsy.app import k8s_watch_recording as W
from cloud_autopsy.collector import client as cl
from cloud_autopsy.collector import collect as co
from cloud_autopsy.collector import podlogs as PLC
from cloud_autopsy.collector import watch as wt
from cloud_autopsy.contracts import plan as pl
from cloud_autopsy.contracts.sources import SourceRegistry


REPO = Path(__file__).resolve().parents[2]
WATCH = wt.WatchConfig(session_seconds=3.0, probe_interval_s=0.2, idle_timeout_s=0.5, final_wait_s=1.5)
LOGS = PLC.LogConfig(rotation_s=0.25, drain_wait_s=1.0, idle_timeout_s=1.0)


class NoEventsMode(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ca-no-events-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        F.write_token(self.tmp)
        self.cluster = FL.LogCluster()
        self.addCleanup(self.cluster.stop_all)
        self.cfg = co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=self.tmp / "ca",
                                      token_file=self.tmp / "token", namespace=F.NAMESPACE,
                                      cluster_id="ca-kind-synthetic", recording_id="ca-no-events")

    def collect(self, name="out", **kw):
        return co.run_watch(self.cfg, WATCH, self.tmp / name, transport=self.cluster, rule_profile=3, pod_logs=LOGS,
                            incident_window=(1, 2), **kw)

    def test_the_exclusion_is_declared_and_recorded_everywhere(self):
        _, conversion, _ = self.collect(no_events=True)
        out = self.tmp / "out"
        manifest = json.loads((out / "recording" / "recording.json").read_bytes())
        self.assertEqual(manifest["contract_version"], "ca-k8s-recording/0.7-provisional")
        self.assertEqual(manifest["not_collected"], [W.EVENTS_EXCLUSION])
        self.assertNotIn("events", {s["resource"] for s in manifest["streams"]})
        self.assertFalse(any(r.endswith("/events") or "watch=1" in r and "/events?" in r for r in self.cluster.requests))
        registry = json.loads((out / "bundle" / "registry.json").read_bytes())
        self.assertTrue(registry["registry_id"].endswith("-src-noevents"))
        self.assertNotIn("k8s.events", registry["sources"][0]["query_ids"])
        plan = json.loads((out / "bundle" / "plan.json").read_bytes())
        self.assertNotIn("k8s.events", {a["query_id"] for a in plan["expected_acquisitions"]})
        self.assertEqual(plan["rule_versions"]["timeline-rules"], "ca-timeline-rules/0.3-provisional")
        self.assertEqual(conversion.report["not_collected"][0]["statement"], "Kubernetes Events: Not collected")
        self.assertNotIn("k8s.events", {b["query_id"] for b in conversion.batch_records})
        intervals = conversion.report["intervals"]
        self.assertNotIn("k8s.events", intervals["acquisitions_with_unclean_batches"])
        W.verify_bundle(out / "recording", out / "bundle")                       # replay byte-identical
        inv = C.investigate_offline(B.load(out / "bundle"))
        self.assertFalse([g for g in inv.result["gaps"] if g["query_id"] == "k8s.events"])

    def test_the_events_enabled_mode_is_unchanged(self):
        _, conversion, _ = self.collect()
        self.assertEqual(json.loads((self.tmp / "out" / "recording" / "recording.json").read_bytes())["contract_version"],
                         "ca-k8s-recording/0.6-provisional")
        self.assertIn("k8s.events", {b["query_id"] for b in conversion.batch_records})
        self.assertNotIn("not_collected", conversion.report)

    def test_the_exclusion_needs_the_incident_mode_and_cannot_drop_other_resources(self):
        with self.assertRaises(cl.CollectorError):
            co.run_watch(self.cfg, WATCH, self.tmp / "x", transport=self.cluster, pod_logs=LOGS, no_events=True)
        with self.assertRaises(cl.CollectorError):
            wt.run_session(self.cluster, F.NAMESPACE, WATCH, resources=("deployments", "events", "replicasets"))

    def test_a_0_7_recording_declaring_anything_else_is_refused(self):
        self.collect(no_events=True)
        manifest_path = self.tmp / "out" / "recording" / "recording.json"
        good = manifest_path.read_bytes()
        for mutate in (lambda m: m.update(not_collected=[]),
                       lambda m: m.update(not_collected=[dict(W.EVENTS_EXCLUSION, query_id="k8s.pods")]),
                       lambda m: m.pop("not_collected"),
                       lambda m: m["streams"].append({"resource": "events", "parts": m["streams"][0]["parts"]})):
            with self.subTest(mutate=mutate):
                manifest = json.loads(good)
                mutate(manifest)
                from cloud_autopsy.contracts.canonical import canonical_bytes
                manifest_path.write_bytes(canonical_bytes(manifest))
                with self.assertRaises(K.RecordingError):
                    K.convert(self.tmp / "out" / "recording", "ca-observation-kinds/0.4-provisional", rule_profile=3)
        manifest_path.write_bytes(good)


class DeclaredAcquisitions(unittest.TestCase):
    def registry(self, queries):
        return SourceRegistry.from_record({
            "contract_version": "ca-source-registry/0.1-provisional", "registry_id": "r",
            "sources": [{"source_id": "k8s-api", "source_kind": "kubernetes_api", "cluster_id": "c", "namespace": "ns",
                         "clock_domain_ids": ["d"], "query_ids": sorted(queries)}]})

    def plan(self, registry, queries):
        return pl.RunPlan.from_record({
            "contract_version": pl.RUN_PLAN_VERSION, "plan_id": "p", "registry_id": "r", "registry_digest": registry.digest,
            "window": {"start": "2026-11-14T10:00:00Z", "end": "2026-11-14T10:10:00Z"},
            "expected_acquisitions": [{"source_id": "k8s-api", "query_id": q, "mandatory": True} for q in sorted(queries)],
            "contract_versions": pl.required_contract_versions(), "rule_versions": {}, "synthesis_mode": "disabled",
            "limits": {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 10, "max_batch_deliveries": 10,
                       "max_observations_per_batch": 10, "max_observations_total": 10, "max_batch_bytes": 100_000,
                       "max_total_bytes": 1_000_000}}, registry)

    def test_the_api_states_what_the_plan_declared(self):
        for queries, expected in ((["k8s.pods", "k8s.events"], "collected"), (["k8s.pods"], "not_collected")):
            registry = self.registry(queries)
            self.assertEqual(pl.declared_acquisitions(self.plan(registry, queries), registry)["kubernetes_events"], expected)

    def test_the_dashboard_wording_is_exact(self):
        views = (REPO / "src" / "cloud_autopsy" / "api" / "ui" / "views.js").read_text(encoding="utf-8")
        self.assertIn('"Kubernetes Events: Not collected"', views)
        for wrong in ("No Events", "Events verified", "No events"):
            self.assertNotIn(wrong, views)


if __name__ == "__main__":
    unittest.main()
