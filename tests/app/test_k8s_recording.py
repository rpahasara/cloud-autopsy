"""CA-P2-004c offline tests: the recorded Kubernetes evidence adapter. No database, no network.

- The committed synthetic recordings equal a fresh export; conversion is deterministic and pinned.
- Pods, ReplicaSets and Deployment rollouts become existing 0.1 observation kinds.
- Events and ConfigMaps are validated and counted as ``unsupported_conversion``: never planned,
  never covered, never evidence, and they cannot change an investigation's result.
- ConfigMap values and event text never reach a bundle or a report.
- Failed, denied, missing, truncated and malformed responses are reported honestly, with no coverage.
- Unsafe or sensitive input is refused before anything is written.
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.app import bundle as B  # noqa: E402
from cloud_autopsy.app import create as C  # noqa: E402
from cloud_autopsy.app import k8s_cli  # noqa: E402
from cloud_autopsy.app import k8s_recording as K  # noqa: E402
from cloud_autopsy.contracts import CONTRACT_VERSIONS  # noqa: E402
from cloud_autopsy.contracts import acquisition as acq  # noqa: E402
from cloud_autopsy.contracts import evidence as ev  # noqa: E402
from cloud_autopsy.contracts import frozen_input as fi  # noqa: E402
from cloud_autopsy.synthetic import k8s_recordings as R  # noqa: E402

EXAMPLES = REPO / "examples" / "k8s-recordings"
LEAKS = ("synthetic-placeholder-not-a-secret", "maxConnections=4", "Back-off", "ScalingReplicaSet", "ConfigChanged",
         "configuration changed", "secretKeyRef", "checkout-db\"", "last-applied")
# Pinned for determinism: SHA-256 of bundle.json and of the canonical report, and the offline result digest.
PINS = {
    "rollout-complete": ("b0ab16f0bae6da89dc703478c07be41e5da159191acf2b731b4e1ed2b4998070",
                         "bb60f69da4df84232f65357347422496e3a7d864573c04c8514ba94e8155ffc6",
                         "7630383de1c3addfd523d9c6a5b74f297ea72bbe3f8d037b7c0d0fb8100299bc"),
    "degraded": ("9bb957876e543463bad14bb8f9905871f88834d7012ec58fb26a31be880a22d9",
                 "492a553e67f9e47fd737f892869c8d6fca9771ab4bae1241ce9e3a65dfe10169",
                 "5a335d6c44ff0ab1c43b9bad8055b5156fd547b40ee1fa15e94ece96f2a8a381"),
    "events-only": ("e0f2db15e76fc2435f882fdc6956d2fd11a1f2d943317c985f0ed8603bad2da6",
                    "e80c6eda51dfc36e59a5ae65c3f0ea928b7bdf03b1ea7e75b80ef1879cd16b2b",
                    "22960bd7682fbf7450fd4c44e02c24466508c32eebae4fe319c611d7a78c4c00"),
}


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ca-k8s-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def copy(self, name="rollout-complete"):
        target = self.tmp / f"rec-{len(list(self.tmp.iterdir()))}"
        shutil.copytree(EXAMPLES / name, target)
        return target

    def manifest(self, root):
        return json.loads((root / K.MANIFEST).read_bytes())

    def save(self, root, manifest):
        (root / K.MANIFEST).write_bytes(R.body_bytes(manifest))

    def set_body(self, root, resource, body, raw=None):
        """Replace a recorded response body and update its manifest digest."""
        data = raw if raw is not None else R.body_bytes(body)
        (root / "responses" / f"{resource}.json").write_bytes(data)
        manifest = self.manifest(root)
        for entry in manifest["responses"]:
            if entry["resource"] == resource:
                entry["sha256"] = hashlib.sha256(data).hexdigest()
        self.save(root, manifest)

    def body(self, root, resource):
        return json.loads((root / "responses" / f"{resource}.json").read_bytes())

    def convert(self, root):
        return K.convert(root)

    def bundle(self, conversion):
        out = self.tmp / f"bundle-{len(list(self.tmp.iterdir()))}"
        conversion.write_bundle(out)
        return out

    def investigate(self, conversion):
        return C.investigate_offline(B.load(self.bundle(conversion)))

    def acquisition(self, conversion, query):
        return next(a for a in conversion.report["acquisitions"] if a["query_id"] == query)

    def unsupported(self, conversion, resource):
        return next(u for u in conversion.report["unsupported"] if u["resource"] == resource)

    def refused(self, root, code):
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(root)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))


class ExampleTests(Workspace):
    def test_examples_equal_a_fresh_export_and_hold_no_real_data(self):
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        for name in R.RECORDINGS:
            K.export_example(fresh / name, name)
            self.assertEqual(tree(EXAMPLES / name), tree(fresh / name), name)
            self.assertEqual(self.manifest(EXAMPLES / name)["data_classification"], "synthetic")

    def test_conversion_is_deterministic_and_pinned(self):
        for name in R.RECORDINGS:
            with self.subTest(recording=name):
                first, second = self.convert(EXAMPLES / name), self.convert(self.copy(name))
                a, b = tree(self.bundle(first)), tree(self.bundle(second))
                self.assertEqual(a, b)
                self.assertEqual(first.report_bytes(), second.report_bytes())
                pins = (hashlib.sha256(a["bundle.json"]).hexdigest(), hashlib.sha256(first.report_bytes()).hexdigest(),
                        self.investigate(first).result_digest.split(":")[-1])
                self.assertEqual(pins, PINS[name])

    def test_existing_contracts_are_unchanged(self):
        self.assertEqual(CONTRACT_VERSIONS["observation-kinds"], "ca-observation-kinds/0.1-provisional")
        self.assertEqual(sorted(ev.KINDS), ["alert_firing", "configmap_change", "deployment_rollout", "log_line",
                                             "metric_sample", "pod", "replicaset"])

    def test_pods_replicasets_and_rollouts_become_existing_kinds(self):
        conversion = self.convert(EXAMPLES / "rollout-complete")
        loaded = B.load(self.bundle(conversion))
        kinds = sorted(o["observation_kind"] for b in loaded.batches for o in b["observations"])
        self.assertEqual(kinds, ["deployment_rollout", "pod", "pod", "replicaset", "replicaset"])
        rollout = next(o for b in loaded.batches for o in b["observations"] if o["observation_kind"] == "deployment_rollout")
        self.assertEqual(rollout["attributes"]["changed_fields"], ["spec.template.spec.containers[checkout-api].image"])
        self.assertEqual((rollout["attributes"]["old_replicaset"], rollout["attributes"]["new_replicaset"]),
                         ("checkout-api-6d4b5", "checkout-api-7c9f8"))
        self.assertEqual([t["timestamp_kind"] for t in rollout["times"]], ["event", "completed"])
        # source identity and namespace binding come from the recording's single registry source
        self.assertEqual([(s.source_id, s.cluster_id, s.namespace) for s in loaded.registry.sources],
                         [("k8s-api", "ca-kind-synthetic", "ca-demo")])
        self.assertEqual(self.acquisition(conversion, "k8s.pods")["out_of_scope"], {"pods": 1})  # debug-shell, counted

    def test_raw_timestamps_and_their_precision_are_kept(self):
        loaded = B.load(self.bundle(self.convert(EXAMPLES / "rollout-complete")))
        pods = {o["entity"]["name"]: o["times"][0] for b in loaded.batches for o in b["observations"]
                if o["observation_kind"] == "pod"}
        self.assertEqual(pods["checkout-api-7c9f8-b1"], {"timestamp_kind": "event", "raw": "2026-10-15T08:11:02Z",
                                                         "clock_domain_id": "k8s-apiserver",
                                                         "declared_precision_ns": 1_000_000_000})
        self.assertEqual(pods["checkout-api-7c9f8-b2"]["declared_precision_ns"], 1_000_000)  # ".250": milliseconds
        # an unparseable timestamp is retained as raw text, not invented or dropped
        root = self.copy()
        body = self.body(root, "pods")
        body["items"][0]["metadata"]["creationTimestamp"] = "15 Oct 2026 08:11"
        self.set_body(root, "pods", body)
        result = self.investigate(self.convert(root)).result
        raws = [e for e in result["timeline"]["entries"] if e["entity"]["name"] == "checkout-api-7c9f8-b1"]
        self.assertEqual(len(raws), 1)
        self.assertIsNone(raws[0]["reference_ms"])

    def test_every_example_investigates_offline(self):
        for name in R.RECORDINGS:
            with self.subTest(recording=name):
                inv = self.investigate(self.convert(EXAMPLES / name))
                self.assertIs(inv.verified, False)
                self.assertEqual(inv.result["outcome"]["status"], "abstained")


class UnsupportedTests(Workspace):
    def test_events_and_configmaps_are_never_planned_covered_or_evidence(self):
        for name in R.RECORDINGS:
            with self.subTest(recording=name):
                conversion = self.convert(EXAMPLES / name)
                loaded = B.load(self.bundle(conversion))
                queries = sorted(a["query_id"] for a in conversion.plan_record["expected_acquisitions"])
                self.assertEqual(queries, ["k8s.deployments", "k8s.pods"])
                self.assertEqual(sorted(loaded.registry.sources[0].query_ids), ["k8s.deployments", "k8s.pods"])
                self.assertTrue(all(b["query_id"] in queries for b in loaded.batches))
                frozen = fi.seal(loaded.plan, loaded.registry, list(loaded.batches))
                self.assertEqual(sorted(a["query_id"] for a in frozen.root()["acquisitions"]), queries)
                for u in conversion.report["unsupported"]:
                    self.assertEqual((u["classification"], u["coverage_claimed"], u["used_as_evidence"]),
                                     ("unsupported_conversion", False, False))

    def test_unsupported_records_are_counted_not_dropped(self):
        conversion = self.convert(EXAMPLES / "rollout-complete")
        self.assertEqual(self.unsupported(conversion, "events")["counts"],
                         {"ConfigMap/Warning": 1, "Deployment/Normal": 1, "Pod/Warning": 1})
        self.assertEqual(self.unsupported(conversion, "configmaps")["counts"],
                         {"configmaps": 1, "data_keys": 2, "values_excluded": True})
        degraded = self.convert(EXAMPLES / "degraded")
        self.assertEqual(self.unsupported(degraded, "events")["response"], "http_504")
        self.assertEqual(self.unsupported(degraded, "configmaps")["response"], "http_403")

    def test_events_cannot_change_an_investigation(self):
        """Warnings that "name" a cause, or no events and ConfigMaps at all: the same bundle, the same result."""
        baseline = self.convert(EXAMPLES / "rollout-complete")
        loud = self.copy()
        body = self.body(loud, "events")
        for i in range(20):
            body["items"].append({**body["items"][1], "metadata": {**body["items"][1]["metadata"], "name": f"loud.{i}",
                                                                   "uid": f"0b8e7c1e-0000-4000-8000-0000000f{i:04d}"},
                                  "reason": "OOMKilling", "message": "root cause: pool exhausted (synthetic)"})
        self.set_body(loud, "events", body)
        quiet = self.copy()
        manifest = self.manifest(quiet)
        manifest["responses"] = [r for r in manifest["responses"] if r["resource"] not in ("events", "configmaps")]
        for resource in ("events", "configmaps"):
            (quiet / "responses" / f"{resource}.json").unlink()
        self.save(quiet, manifest)
        expected = tree(self.bundle(baseline))
        for variant in (loud, quiet):
            converted = self.convert(variant)
            self.assertEqual(tree(self.bundle(converted)), expected)
            self.assertEqual(self.investigate(converted).result_bytes, self.investigate(baseline).result_bytes)
        self.assertEqual(self.unsupported(self.convert(loud), "events")["items"], 23)
        self.assertEqual(self.unsupported(self.convert(quiet), "events")["response"], "not_recorded")

    def test_events_only_recording_has_no_coverage_and_no_evidence(self):
        conversion = self.convert(EXAMPLES / "events-only")
        loaded = B.load(self.bundle(conversion))
        self.assertEqual(sorted((b["query_id"], b["outcome"], b["reason"], b["coverage"], len(b["observations"]))
                                for b in loaded.batches),
                         [("k8s.deployments", "failed", "source_unavailable", None, 0),
                          ("k8s.pods", "denied", "authorization_denied", None, 0)])
        result = self.investigate(conversion).result
        self.assertEqual(result["timeline"]["entries"], [])
        self.assertEqual(result["outcome"]["evidence_ids"], [])
        self.assertTrue(all(not h["prerequisites"] or all(not p["evidence_ids"] for p in h["prerequisites"])
                            for h in result["hypotheses"]))
        self.assertTrue(result["gaps"])  # the missing acquisitions are reported as gaps

    def test_cited_evidence_comes_only_from_converted_kinds(self):
        conversion = self.convert(EXAMPLES / "rollout-complete")
        loaded = B.load(self.bundle(conversion))
        result = self.investigate(conversion).result
        converted = {e.evidence_id for b in loaded.batches
                     for e in acq.decode_batch(b, loaded.plan, loaded.registry).evidence}
        self.assertEqual({e.observation_kind for b in loaded.batches
                          for e in acq.decode_batch(b, loaded.plan, loaded.registry).evidence},
                         {"pod", "replicaset", "deployment_rollout"})
        cited = {e["evidence_id"] for e in result["timeline"]["entries"]} | set(result["outcome"]["evidence_ids"])
        for h in result["hypotheses"]:
            cited |= {e for p in h["prerequisites"] for e in p["evidence_ids"]}
        self.assertLessEqual(cited, converted)

    def test_values_and_event_text_never_leave_the_recording(self):
        for name in R.RECORDINGS:
            with self.subTest(recording=name):
                conversion = self.convert(EXAMPLES / name)
                written = b"".join(tree(self.bundle(conversion)).values()) + conversion.report_bytes()
                for leak in LEAKS:
                    self.assertNotIn(leak.encode(), written, leak)
                result = self.investigate(conversion).result_bytes
                for leak in LEAKS:
                    self.assertNotIn(leak.encode(), result, leak)


class HonestFailureTests(Workspace):
    def test_response_failures_map_to_outcomes_without_coverage(self):
        cases = ((401, None, "denied", "authorization_denied"), (403, None, "denied", "authorization_denied"),
                 (429, None, "failed", "rate_limited"), (504, "timeout", "failed", "timeout"),
                 (500, "unavailable", "failed", "source_unavailable"))
        for status, error, outcome, reason in cases:
            with self.subTest(status=status):
                root = self.copy()
                manifest = self.manifest(root)
                for entry in manifest["responses"]:
                    if entry["resource"] == "pods":
                        entry.update(http_status=status, error=error, file=None, sha256=None, coverage=None)
                (root / "responses" / "pods.json").unlink()
                self.save(root, manifest)
                a = self.acquisition(self.convert(root), "k8s.pods")
                self.assertEqual((a["outcome"], a["reason"], a["observations"], a["coverage_claimed"]),
                                 (outcome, reason, 0, False))

    def test_a_resource_that_was_not_recorded_is_unavailable(self):
        root = self.copy()
        manifest = self.manifest(root)
        manifest["responses"] = [r for r in manifest["responses"] if r["resource"] != "replicasets"]
        (root / "responses" / "replicasets.json").unlink()
        self.save(root, manifest)
        a = self.acquisition(self.convert(root), "k8s.deployments")
        self.assertEqual((a["outcome"], a["reason"], a["response"]["replicasets"], a["coverage_claimed"]),
                         ("failed", "source_unavailable", "not_recorded", False))

    def test_a_continue_token_is_partial_and_never_claims_coverage(self):
        a = self.acquisition(self.convert(EXAMPLES / "degraded"), "k8s.pods")
        self.assertEqual((a["outcome"], a["reason"], a["observations"], a["coverage_claimed"]),
                         ("partial", "page_limit", 1, False))
        loaded = B.load(self.bundle(self.convert(EXAMPLES / "degraded")))
        pods = [b for b in loaded.batches if b["query_id"] == "k8s.pods"][0]
        self.assertEqual(pods["truncation"], {"truncated": True, "reason": "page_limit", "omitted_count": 2})

    def test_malformed_bodies_and_items_make_the_acquisition_invalid_not_partial(self):
        def no_node(body):
            del body["items"][0]["spec"]["nodeName"]

        def wrong_kind(body):
            body["kind"] = "ServiceList"

        def duplicate(body):
            body["items"].append(body["items"][0])

        def bad_restarts(body):
            body["items"][0]["status"]["containerStatuses"][0]["restartCount"] = -1

        for mutate, code in ((no_node, "node_missing"), (wrong_kind, "list_kind_mismatch"),
                             (duplicate, "item_duplicate"), (bad_restarts, "restart_count_invalid")):
            with self.subTest(code=code):
                root = self.copy()
                body = self.body(root, "pods")
                mutate(body)
                self.set_body(root, "pods", body)
                a = self.acquisition(self.convert(root), "k8s.pods")
                self.assertEqual((a["outcome"], a["reason"], a["observations"], a["item_errors"]),
                                 ("failed", "invalid_response", 0, {code: 1}))
        root = self.copy()
        self.set_body(root, "pods", None, raw=b'{"kind": "PodList", "kind": "PodList", "items": []}')
        self.assertEqual(self.acquisition(self.convert(root), "k8s.pods")["item_errors"], {"body_not_strict_json": 1})

    def test_rollouts_need_the_recorded_replicasets(self):
        root = self.copy()
        body = self.body(root, "replicasets")
        body["items"] = body["items"][:1]  # the revision-2 ReplicaSet is missing
        self.set_body(root, "replicasets", body)
        a = self.acquisition(self.convert(root), "k8s.deployments")
        self.assertEqual((a["outcome"], a["item_errors"]), ("failed", {"rollout_replicaset_missing": 1}))
        root = self.copy()
        body = self.body(root, "deployments")
        body["items"][0]["metadata"]["annotations"]["deployment.kubernetes.io/revision"] = "1"
        self.set_body(root, "deployments", body)
        a = self.acquisition(self.convert(root), "k8s.deployments")
        self.assertEqual((a["outcome"], a["observations"], a["notes"]), ("complete", 2, {"no_previous_revision": 1}))

    def test_disjoint_coverage_is_not_verified(self):
        root = self.copy()
        manifest = self.manifest(root)
        for entry in manifest["responses"]:
            if entry["resource"] == "replicasets":
                entry["coverage"] = {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T08:05:00Z"}
            if entry["resource"] == "deployments":
                entry["coverage"] = {"start": "2026-10-15T08:10:00Z", "end": "2026-10-15T08:30:00Z"}
        self.save(root, manifest)
        a = self.acquisition(self.convert(root), "k8s.deployments")
        self.assertEqual((a["outcome"], a["coverage_claimed"]), ("failed", False))


class RefusalTests(Workspace):
    def test_manifest_and_classification(self):
        cases = (({"data_classification": "customer"}, "recording_classification_refused"),
                 ({"contract_version": "ca-k8s-recording/9"}, "recording_version_unsupported"),
                 ({"extra": 1}, "recording_manifest_invalid"),
                 ({"namespace": "Not_A_Namespace"}, "recording_manifest_invalid"),
                 ({"window": {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T10:00:00Z"}}, "recording_manifest_invalid"))
        for change, code in cases:
            with self.subTest(code=code, change=list(change)):
                root = self.copy()
                self.save(root, {**self.manifest(root), **change})
                self.refused(root, code)

    def test_secrets_are_refused(self):
        root = self.copy()
        manifest = self.manifest(root)
        manifest["responses"].append({"resource": "secrets", "file": None, "sha256": None, "http_status": 403,
                                      "error": None, "coverage": None})
        self.save(root, manifest)
        self.refused(root, "recording_sensitive_refused")
        root = self.copy()
        body = self.body(root, "configmaps")
        body["items"].append({"kind": "Secret", "metadata": {"name": "x", "namespace": "ca-demo"}})
        self.set_body(root, "configmaps", body)
        self.refused(root, "recording_sensitive_refused")

    def test_namespace_isolation(self):
        for resource, mutate in (("pods", lambda b: b["items"][0]["metadata"].update(namespace="other")),
                                 ("events", lambda b: b["items"][0]["involvedObject"].update(namespace="other"))):
            with self.subTest(resource=resource):
                root = self.copy()
                body = self.body(root, resource)
                mutate(body)
                self.set_body(root, resource, body)
                self.refused(root, "recording_namespace_mismatch")

    def test_files_paths_and_digests(self):
        root = self.copy()
        (root / "responses" / "pods.json").write_bytes(b"{}")  # digest no longer matches
        self.refused(root, "recording_digest_mismatch")
        root = self.copy()
        (root / "ground-truth.json").write_bytes(b"{}")
        self.refused(root, "recording_unexpected_entry")
        root = self.copy()
        manifest = self.manifest(root)
        manifest["responses"][0]["file"] = "../pods.json"
        self.save(root, manifest)
        self.refused(root, "recording_path_refused")
        root = self.copy()
        manifest = self.manifest(root)
        manifest["responses"].append(dict(manifest["responses"][0]))
        self.save(root, manifest)
        self.refused(root, "recording_manifest_conflict")

    @unittest.skipUnless(os.name == "nt", "Windows junctions")
    def test_a_junction_is_refused(self):
        root = self.copy()
        target = self.tmp / "elsewhere"
        target.mkdir()
        shutil.move(str(root / "responses"), str(target / "responses"))
        subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "responses"), str(target / "responses")],
                       check=True, capture_output=True)
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(root)
        self.assertIn(ctx.exception.code, {"recording_link_refused", "recording_unexpected_entry"})

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlink_is_refused(self):
        root = self.copy()
        (root / "responses" / "pods.json").unlink()
        (root / "responses" / "pods.json").symlink_to(EXAMPLES / "rollout-complete" / "responses" / "pods.json")
        self.refused(root, "recording_link_refused")


class CliTests(Workspace):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = k8s_cli.main(list(argv))
        return code, out.getvalue()

    def test_converts_reports_and_refuses_without_writing(self):
        out, report = self.tmp / "b", self.tmp / "r.json"
        code, text = self.run_cli(str(EXAMPLES / "rollout-complete"), "--out", str(out), "--report", str(report))
        self.assertEqual(code, 0)
        self.assertIn("unsupported_conversion", text)
        self.assertEqual(json.loads(report.read_bytes())["contract_version"], K.REPORT_VERSION)
        B.load(out)
        bad = self.copy()
        self.save(bad, {**self.manifest(bad), "data_classification": "customer"})
        code, text = self.run_cli(str(bad), "--out", str(self.tmp / "never"), "--json")
        self.assertEqual((code, json.loads(text)["code"]), (1, "recording_classification_refused"))
        self.assertFalse((self.tmp / "never").exists())


if __name__ == "__main__":
    unittest.main()
