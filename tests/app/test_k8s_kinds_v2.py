"""CA-P2-004d offline tests: Kubernetes Events and ConfigMap metadata under observation kinds 0.2,
and the coverage semantics of recorded snapshots. No database, no network.

- Under a 0.2 plan, Events become ``k8s_event`` and ConfigMaps ``configmap_metadata``; under 0.1 they
  stay ``unsupported_conversion``. Kinds 0.2 needs a snapshot (0.2) recording.
- 0.1 kinds produce byte-identical evidence under either plan.
- Events and ConfigMap metadata never establish a cause, never change a hypothesis, and ConfigMap
  metadata is never a configuration change.
- No ConfigMap value, value hash, credential-like key name, Secret reference or Event message leaves
  the recording.
- A snapshot covers its own instant only; skewed snapshots and declared windows are never complete.
"""

import hashlib
import json
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
from cloud_autopsy.app import k8s_recording as K  # noqa: E402
from cloud_autopsy.contracts import acquisition as acq  # noqa: E402
from cloud_autopsy.contracts import canonical  # noqa: E402
from cloud_autopsy.contracts import evidence as ev  # noqa: E402
from cloud_autopsy.contracts import frozen_input as fi  # noqa: E402
from cloud_autopsy.contracts import plan as pl  # noqa: E402
from cloud_autopsy.contracts.errors import ContractError  # noqa: E402
from cloud_autopsy.synthetic import k8s_recordings as R  # noqa: E402

EXAMPLES = REPO / "examples" / "k8s-recordings"
V1, V2 = ev.KIND_REGISTRY_VERSION, ev.KIND_REGISTRY_VERSION_V2
NEW_KINDS = {"k8s_event", "configmap_metadata"}
LEAKS = ("synthetic-placeholder-not-a-secret", "db.password", "maxConnections=4", "Back-off", "Scaled up",
         "configuration changed", "secretKeyRef", "DB_PASSWORD", "last-applied", "checkout-db\"")
# Pinned for determinism: (bundle.json SHA-256, report SHA-256, offline result digest) per recording and kinds.
PINS = {
    ("snapshot-complete", "0.1"): ("c4232117e5328268f97f0e709f46498b139922073288d4ff08074758049a170f",
                                   "65361e7b604e690bb03eea63712c437f5579e11322937f8e789c6d2e418e50cb",
                                   "22732ffcee066a5f983411d3cecd1f5afa02194b011ddebdcdc7d0280f599317"),
    ("snapshot-complete", "0.2"): ("9bbe9ae6c42a7eeabc620f6a6b1f213dd14bfc3c412b4441a6581c153f9d3a62",
                                   "781e9f38d7105cd3056d0ae21025bbaca3d9be5e9cebfc002dadc0b96d2cc885",
                                   "ccef5d70cbda8a597800eea60355397322987957148c9c272dab17ed66aaa458"),
    ("snapshot-skewed", "0.1"): ("9f1121924f0f0b1ef49c4244d678d41ac9a8fb0e01af133b1ac847646ec771f1",
                                 "83526533dd42ef45f462de39d4d3b7f385780af7fa7446b276185893fc54b65a",
                                 "0729c8295484c9c46b91585f5e018561933b9f91b444b2f960b3e9e8730b63a0"),
    ("snapshot-skewed", "0.2"): ("439c07a73f2ad13cbeefccad9332fe19ee959787a8b143d64c6d8e7103274236",
                                 "1644a3db3d512481dd5cf41542638e24d6749b94851a2497d27017ddee7b0294",
                                 "488cf3cbbdc6f7ba5098bb5912247866d0d3ae5b44696f93c4657648186cc1c6"),
}


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ca-k8s-v2-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def copy(self, name="snapshot-complete"):
        target = self.tmp / f"rec-{len(list(self.tmp.iterdir()))}"
        shutil.copytree(EXAMPLES / name, target)
        return target

    def set_body(self, root, resource, body):
        data = R.body_bytes(body)
        (root / "responses" / f"{resource}.json").write_bytes(data)
        manifest = json.loads((root / K.MANIFEST).read_bytes())
        for entry in manifest["responses"]:
            if entry["resource"] == resource:
                entry["sha256"] = hashlib.sha256(data).hexdigest()
        (root / K.MANIFEST).write_bytes(R.body_bytes(manifest))

    def body(self, root, resource):
        return json.loads((root / "responses" / f"{resource}.json").read_bytes())

    def bundle(self, conversion):
        out = self.tmp / f"bundle-{len(list(self.tmp.iterdir()))}"
        conversion.write_bundle(out)
        return out

    def convert_and_investigate(self, source, kinds=V2):
        conversion = K.convert(source, kinds)
        loaded = B.load(self.bundle(conversion))
        return conversion, loaded, C.investigate_offline(loaded)

    @staticmethod
    def evidence(loaded):
        return [e for b in loaded.batches for e in acq.decode_batch(b, loaded.plan, loaded.registry).evidence]

    @staticmethod
    def acquisition(conversion, query):
        return next(a for a in conversion.report["acquisitions"] if a["query_id"] == query)

    @staticmethod
    def cited(result):
        ids = set(result["outcome"]["evidence_ids"])
        for h in result["hypotheses"]:
            ids |= {e for p in h["prerequisites"] for e in p["evidence_ids"]}
            ids |= {e for p in h["prerequisites"] for o in p["orderings"] for e in (o["a"], o["b"])}
            ids |= {e for c in h["contradictions"] for e in c["evidence_ids"]}
            if h.get("change_evidence_id"):
                ids.add(h["change_evidence_id"])
        return ids


class ConversionTests(Workspace):
    def test_snapshot_examples_equal_a_fresh_export(self):
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        for name in R.RECORDINGS_V2:
            K.export_example(fresh / name, name)
            self.assertEqual(tree(EXAMPLES / name), tree(fresh / name), name)

    def test_kinds_0_2_converts_events_and_configmap_metadata(self):
        conversion, loaded, _ = self.convert_and_investigate(EXAMPLES / "snapshot-complete")
        self.assertEqual(loaded.plan.kind_registry_version, V2)
        self.assertEqual(sorted(q for _, q, _ in loaded.plan.expected_acquisitions),
                         ["k8s.configmaps", "k8s.deployments", "k8s.events", "k8s.pods"])
        self.assertEqual({(q, m) for _, q, m in loaded.plan.expected_acquisitions if q in ("k8s.events", "k8s.configmaps")},
                         {("k8s.events", False), ("k8s.configmaps", False)})
        kinds = sorted(e.observation_kind for e in self.evidence(loaded))
        self.assertEqual(kinds, ["configmap_metadata", "deployment_rollout", "k8s_event", "k8s_event", "k8s_event",
                                 "pod", "pod", "replicaset", "replicaset"])
        self.assertEqual(conversion.report["unsupported"], [])
        cm = next(e for e in self.evidence(loaded) if e.observation_kind == "configmap_metadata")
        self.assertEqual(dict(cm.attributes), {"data_key_names": ("pool.maxConnections",), "binary_key_names": (),
                                               "withheld_key_count": 1, "immutable": False})
        warning = next(e for e in self.evidence(loaded) if e.observation_kind == "k8s_event" and e.attributes["reason"] == "BackOff")
        # the recorded event has a lastTimestamp only, so only the "event" time is kept (none is invented)
        self.assertEqual((warning.attributes["involved_kind"], warning.attributes["type"], warning.attributes["count"],
                          [t.timestamp_kind for t in warning.times], warning.times[0].raw),
                         ("Pod", "Warning", 3, ["event"], "2026-10-15T08:16:00Z"))

    def test_kinds_0_1_keeps_events_unsupported_and_shares_identical_evidence(self):
        old_conversion, old, _ = self.convert_and_investigate(EXAMPLES / "snapshot-complete", V1)
        _, new, _ = self.convert_and_investigate(EXAMPLES / "snapshot-complete", V2)
        self.assertEqual([u["classification"] for u in old_conversion.report["unsupported"]],
                         ["unsupported_conversion", "unsupported_conversion"])
        self.assertFalse({e.observation_kind for e in self.evidence(old)} & NEW_KINDS)
        old_records = {e.evidence_id: canonical.canonical_bytes(e.to_record()) for e in self.evidence(old)}
        new_records = {e.evidence_id: canonical.canonical_bytes(e.to_record()) for e in self.evidence(new)
                       if e.observation_kind not in NEW_KINDS}
        self.assertEqual(old_records, new_records)  # the same stored bytes: never re-labelled

    def test_kinds_0_2_needs_a_snapshot_recording_and_a_known_version(self):
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(EXAMPLES / "rollout-complete", V2)
        self.assertEqual(ctx.exception.code, "recording_kinds_need_snapshot_recording")
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(EXAMPLES / "snapshot-complete", "ca-observation-kinds/0.3-provisional")
        self.assertEqual(ctx.exception.code, "recording_kinds_unsupported")

    def test_mixed_versions_are_refused(self):
        conversion = K.convert(EXAMPLES / "snapshot-complete", V2)
        loaded = B.load(self.bundle(conversion))
        old_plan_record = {**conversion.plan_record, "contract_versions": pl.required_contract_versions(V1)}
        old_plan = pl.RunPlan.from_record(old_plan_record, loaded.registry)
        events = next(b for b in conversion.batch_records if b["query_id"] == "k8s.events")
        with self.assertRaises(ContractError) as ctx:  # a 0.2 kind under a 0.1 plan
            acq.decode_batch({**events, "plan_digest": old_plan.digest}, old_plan, loaded.registry)
        self.assertEqual(ctx.exception.code, "observation_kind_unsupported")

    def test_conversion_is_deterministic(self):
        for name in R.RECORDINGS_V2:
            for kinds in (V1, V2):
                with self.subTest(recording=name, kinds=kinds):
                    a, b = K.convert(EXAMPLES / name, kinds), K.convert(self.copy(name), kinds)
                    self.assertEqual(tree(self.bundle(a)), tree(self.bundle(b)))
                    self.assertEqual(a.report_bytes(), b.report_bytes())
                    key = (name, kinds[-15:-12])
                    pins = (hashlib.sha256(tree(self.bundle(a))["bundle.json"]).hexdigest(),
                            hashlib.sha256(a.report_bytes()).hexdigest(),
                            C.investigate_offline(B.load(self.bundle(a))).result_digest.split(":")[-1])
                    self.assertEqual(pins, PINS[key])


class EngineGuardrailTests(Workspace):
    def test_events_and_configmap_metadata_never_establish_or_change_a_cause(self):
        _, old, old_inv = self.convert_and_investigate(EXAMPLES / "snapshot-complete", V1)
        _, new, new_inv = self.convert_and_investigate(EXAMPLES / "snapshot-complete", V2)
        new_kind_ids = {e.evidence_id for e in self.evidence(new) if e.observation_kind in NEW_KINDS}
        self.assertTrue(new_kind_ids)
        self.assertFalse(self.cited(new_inv.result) & new_kind_ids)
        shape = lambda r: [(h["mechanism"], h["status"], h.get("change_evidence_id")) for h in r["hypotheses"]]  # noqa: E731
        self.assertEqual(shape(new_inv.result), shape(old_inv.result))
        self.assertEqual(new_inv.result["outcome"]["status"], "abstained")
        # but they are visible in the timeline, as context
        kinds = {e["observation_kind"] for e in new_inv.result["timeline"]["entries"]}
        self.assertLessEqual(NEW_KINDS, kinds)

    def test_loud_warnings_naming_a_cause_change_no_hypothesis(self):
        root = self.copy()
        body = self.body(root, "events")
        warning = body["items"][1]
        for i in range(20):
            body["items"].append({**warning, "metadata": {**warning["metadata"], "name": f"loud.{i}",
                                                          "uid": f"0b8e7c1e-0000-4000-8000-0000000f{i:04d}"},
                                  "reason": "OOMKilling", "message": "root cause: pool exhausted (synthetic)"})
        self.set_body(root, "events", body)
        _, baseline, base_inv = self.convert_and_investigate(EXAMPLES / "snapshot-complete")
        _, loud, loud_inv = self.convert_and_investigate(root)
        self.assertEqual(len([e for e in self.evidence(loud) if e.observation_kind == "k8s_event"]), 23)
        self.assertEqual([(h["mechanism"], h["status"]) for h in loud_inv.result["hypotheses"]],
                         [(h["mechanism"], h["status"]) for h in base_inv.result["hypotheses"]])
        self.assertEqual(loud_inv.result["outcome"], base_inv.result["outcome"])
        self.assertNotIn(b"root cause", loud_inv.result_bytes)

    def test_configmap_metadata_is_never_a_configuration_change(self):
        _, loaded, inv = self.convert_and_investigate(EXAMPLES / "snapshot-complete")
        metadata = {e.evidence_id for e in self.evidence(loaded) if e.observation_kind == "configmap_metadata"}
        for h in inv.result["hypotheses"]:
            self.assertNotIn(h.get("change_evidence_id"), metadata)
            if h["mechanism"] == "config_limit_reduction":
                self.assertNotEqual(h["status"], "supported")
        self.assertNotIn("configmap_change", {e.observation_kind for e in self.evidence(loaded)})


class PrivacyTests(Workspace):
    def test_no_values_hashes_secrets_or_messages_leave_the_recording(self):
        values = list(R.CONFIG_VALUES.values())
        value_hashes = [hashlib.sha256(v.encode()).hexdigest() for v in values]
        for name in R.RECORDINGS_V2:
            for kinds in (V1, V2):
                with self.subTest(recording=name, kinds=kinds):
                    conversion, loaded, inv = self.convert_and_investigate(EXAMPLES / name, kinds)
                    written = b"".join(tree(self.bundle(conversion)).values()) + conversion.report_bytes() + inv.result_bytes
                    for needle in list(LEAKS) + values[1:] + value_hashes:
                        self.assertNotIn(needle.encode(), written, needle)

    def test_credential_like_key_names_are_withheld_and_counted(self):
        root = self.copy()
        body = self.body(root, "configmaps")
        body["items"][0]["data"]["api_token"] = "x"
        body["items"][0]["binaryData"] = {"tls.key-private_key": "AAAA", "logo.png": "AAAA"}
        self.set_body(root, "configmaps", body)
        _, loaded, _ = self.convert_and_investigate(root)
        cm = next(e for e in self.evidence(loaded) if e.observation_kind == "configmap_metadata")
        self.assertEqual((cm.attributes["data_key_names"], cm.attributes["binary_key_names"], cm.attributes["withheld_key_count"]),
                         (("pool.maxConnections",), ("logo.png",), 3))

    def test_namespace_and_secret_boundaries_hold_under_0_2(self):
        for resource, mutate, code in (
                ("events", lambda b: b["items"][0]["involvedObject"].update(namespace="other"), "recording_namespace_mismatch"),
                ("configmaps", lambda b: b["items"][0]["metadata"].update(namespace="other"), "recording_namespace_mismatch"),
                ("events", lambda b: b["items"].append({"kind": "Secret", "metadata": {"name": "s", "namespace": "ca-demo"}}),
                 "recording_sensitive_refused")):
            with self.subTest(resource=resource, code=code):
                root = self.copy()
                body = self.body(root, resource)
                mutate(body)
                self.set_body(root, resource, body)
                with self.assertRaises(K.RecordingError) as ctx:
                    K.convert(root, V2)
                self.assertEqual(ctx.exception.code, code)

    def test_malformed_events_fail_only_their_acquisition(self):
        root = self.copy()
        body = self.body(root, "events")
        del body["items"][0]["count"]
        self.set_body(root, "events", body)
        conversion, loaded, _ = self.convert_and_investigate(root)
        a = self.acquisition(conversion, "k8s.events")
        self.assertEqual((a["outcome"], a["reason"], a["item_errors"], a["coverage_claimed"]),
                         ("failed", "invalid_response", {"event_count_invalid": 1}, False))
        self.assertEqual(self.acquisition(conversion, "k8s.pods")["outcome"], "complete")
        self.assertFalse({e.observation_kind for e in self.evidence(loaded)} & {"k8s_event"})


class CoverageSemanticsTests(Workspace):
    def test_a_snapshot_covers_its_own_instant_only(self):
        conversion, loaded, inv = self.convert_and_investigate(EXAMPLES / "snapshot-complete")
        for b in loaded.batches:
            self.assertEqual(b["coverage"], {"start": "2026-10-15T08:29:59.000Z", "end": "2026-10-15T08:29:59.001Z"})
        frozen = fi.seal(loaded.plan, loaded.registry, list(loaded.batches))
        self.assertTrue(all(a["verified_ms"] == 1 for a in frozen.root()["acquisitions"]))
        self.assertEqual(frozen.root()["status"], "incomplete")  # the rest of the window is a coverage gap
        reasons = {r for g in inv.result["gaps"] for r in g["reasons"]}
        self.assertIn("coverage_gap", reasons)
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        for a in conversion.report["acquisitions"]:
            self.assertEqual(a["coverage_basis"], K.SNAPSHOT_INSTANT)

    def test_skewed_snapshots_and_failures_are_never_complete(self):
        conversion, loaded, inv = self.convert_and_investigate(EXAMPLES / "snapshot-skewed")
        outcomes = {a["query_id"]: (a["outcome"], a["reason"], a["coverage_claimed"]) for a in conversion.report["acquisitions"]}
        self.assertEqual(outcomes, {"k8s.configmaps": ("denied", "authorization_denied", False),
                                    "k8s.deployments": ("partial", "continuity_lost", False),
                                    "k8s.events": ("failed", "timeout", False),
                                    "k8s.pods": ("complete", None, True)})
        frozen = fi.seal(loaded.plan, loaded.registry, list(loaded.batches))
        verified = {a["query_id"]: a["verified_ms"] for a in frozen.root()["acquisitions"]}
        self.assertEqual(verified, {"k8s.configmaps": 0, "k8s.deployments": 0, "k8s.events": 0, "k8s.pods": 1})
        self.assertEqual(inv.result["outcome"]["status"], "abstained")

    def test_a_snapshot_at_the_window_end_or_outside_is_refused(self):
        for at in ("2026-10-15T08:30:00Z", "2026-10-15T07:59:59Z", "2026-10-15T08:10:00.0005Z"):
            with self.subTest(at=at):
                root = self.copy()
                manifest = json.loads((root / K.MANIFEST).read_bytes())
                manifest["responses"][0]["snapshot_at"] = at
                (root / K.MANIFEST).write_bytes(R.body_bytes(manifest))
                with self.assertRaises(K.RecordingError) as ctx:
                    K.convert(root, V2)
                self.assertEqual(ctx.exception.code, "recording_manifest_invalid")

    def test_a_0_2_recording_cannot_declare_a_window(self):
        root = self.copy()
        manifest = json.loads((root / K.MANIFEST).read_bytes())
        manifest["responses"][0]["coverage"] = {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T08:30:00Z"}
        (root / K.MANIFEST).write_bytes(R.body_bytes(manifest))
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(root, V2)
        self.assertEqual(ctx.exception.code, "recording_manifest_invalid")


if __name__ == "__main__":
    unittest.main()
