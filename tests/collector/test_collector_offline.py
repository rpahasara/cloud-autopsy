"""CA-P2-004e collector, offline: allowlist, pagination safeguards, fault mapping, sanitization,
recording 0.3, fail-closed batches, honest abstention and deterministic replay. No cluster, no network.
"""

import io
import json
import logging
import os
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import _fake_api as F
from cloud_autopsy.app import bundle as B
from cloud_autopsy.app import create as C
from cloud_autopsy.app import k8s_recording as K
from cloud_autopsy.collector import client as cl
from cloud_autopsy.collector import collect as co
from cloud_autopsy.contracts import acquisition as acq
from cloud_autopsy.contracts import evidence as ev
from cloud_autopsy.contracts import frozen_input as fi

V2 = ev.KIND_REGISTRY_VERSION_V2


def config(**overrides):
    base = dict(server="https://127.0.0.1:6443", ca_file=Path("unused"), token_file=Path("unused"),
                namespace="ca-demo", cluster_id="ca-kind-synthetic", recording_id="ca-collect-test", page_limit=2)
    base.update(overrides)
    return co.CollectorConfig(**base)


def collect(api, **overrides):
    return cl.collect_list(api, overrides.pop("resource", "events"), "ca-demo",
                           overrides.pop("page_limit", 2), overrides.pop("max_pages", 20),
                           overrides.pop("max_restarts", 1))


class AllowlistTests(unittest.TestCase):
    def test_only_the_four_namespaced_list_paths_can_be_formed(self):
        self.assertEqual(cl.build_path("pods", "ca-demo", 50), "/api/v1/namespaces/ca-demo/pods?limit=50")
        for resource in ("secrets", "configmaps", "pods/log", "pods/exec", "nodes", "namespaces", "../secrets"):
            with self.subTest(resource=resource), self.assertRaises(cl.CollectorError):
                cl.build_path(resource, "ca-demo", 50)
        for ns in ("Other", "ca-demo/../kube-system", "", "a" * 64):
            with self.subTest(ns=ns), self.assertRaises(cl.CollectorError):
                cl.build_path("pods", ns, 50)
        for limit in (0, 501, "5", None):
            with self.subTest(limit=limit), self.assertRaises(cl.CollectorError):
                cl.build_path("pods", "ca-demo", limit)

    def test_continue_tokens_are_opaque_bounded_and_encoded_as_one_value(self):
        token = "a+b/c=d&e%f?g h:" + "x" * 10
        path = cl.build_path("pods", "ca-demo", 5, token)
        self.assertEqual(path.count("&"), 1)  # limit & continue: nothing in the token splits the query
        self.assertTrue(path.endswith("continue=a%2Bb%2Fc%3Dd%26e%25f%3Fg%20h%3A" + "x" * 10))
        for bad in ("bad\ntoken", "\x00", "", "x" * (cl.MAX_TOKEN_CHARS + 1), "café", 5):
            with self.subTest(bad=repr(bad)[:20]), self.assertRaises(cl.CollectorError):
                cl.build_path("pods", "ca-demo", 5, bad)

    def test_only_https_on_loopback_is_accepted(self):
        for ok in ("https://127.0.0.1:6443", "https://localhost:6443", "https://[::1]:6443"):
            cl.check_server(ok)
        for bad in ("http://127.0.0.1:6443", "https://10.0.0.5:6443", "https://kubernetes.default.svc",
                    "https://example.com", "https://127.0.0.1:6443/api", "https://user:pw@127.0.0.1:6443",
                    "https://127.0.0.1:6443?x=1", "ftp://127.0.0.1"):
            with self.subTest(bad=bad), self.assertRaises(cl.CollectorError):
                cl.check_server(bad)


class PaginationTests(unittest.TestCase):
    def test_a_paginated_collection_is_consistent_and_tokens_never_persist(self):
        api = F.FakeApi()
        result = collect(api)
        self.assertEqual((result.outcome, result.pages, result.collection_resource_version), ("consistent", 2, "3104"))
        self.assertEqual(len(result.items), 3)  # 4 events, the Secret-involving one withheld
        self.assertEqual(result.counts, {"secret_events_withheld": 1})
        sent = [q.get("continue") for _, q, _ in api.requests]
        self.assertEqual(sent[0], None)
        self.assertIn(sent[1], api.issued)  # the opaque token round-tripped exactly
        self.assertNotIn(sent[1], json.dumps(result.items))

    def test_item_resource_versions_do_not_decide_consistency(self):
        result = collect(F.FakeApi(faults={"events": {"item_rv_drift": True}}))
        self.assertEqual(result.outcome, "consistent")

    def test_a_changed_collection_resource_version_discards_every_page(self):
        result = collect(F.FakeApi(faults={"events": {"rv_change_on_page": 2}}))
        self.assertEqual((result.outcome, result.error, result.items, result.collection_resource_version),
                         ("rv_changed", "collection_rv_changed", [], None))

    def test_410_restarts_from_scratch_without_reusing_any_token(self):
        api = F.FakeApi(faults={"events": {"gone_on_page": 2, "gone_times": 1}})
        result = collect(api)
        self.assertEqual((result.outcome, result.restarts, len(result.items)), ("consistent", 1, 3))
        continues = [q.get("continue") for _, q, _ in api.requests]
        self.assertEqual(continues[2], None)          # the restart starts with no continue parameter
        self.assertNotIn("STOLEN-TOKEN-AFTER-410", continues)
        self.assertNotIn(continues[1], continues[2:])  # the expired attempt's token is never sent again

    def test_repeated_410_fails_and_keeps_nothing(self):
        api = F.FakeApi(faults={"events": {"gone_on_page": 2}})
        result = collect(api, max_restarts=1)
        self.assertEqual((result.outcome, result.error, result.items, result.restarts),
                         ("expired", "list_expired", [], 1))
        self.assertNotIn("STOLEN-TOKEN-AFTER-410", [q.get("continue") for _, q, _ in api.requests])

    def test_the_page_bound_truncates(self):
        result = collect(F.FakeApi(), max_pages=1)
        self.assertEqual((result.outcome, result.pages, result.remaining_item_count, result.collection_resource_version),
                         ("truncated", 1, 2, "3104"))

    def test_failures_map_to_codes_and_keep_nothing(self):
        cases = ((401, "denied"), (403, "denied"), (429, "rate_limited"), (500, "unavailable"), (503, "unavailable"),
                 (404, "invalid"), (302, "unavailable"))
        for status, outcome in cases:
            with self.subTest(status=status):
                result = collect(F.FakeApi(faults={"events": {"status": status}}))
                self.assertEqual((result.outcome, result.error, result.items), (outcome, f"http_{status}", []))
        for raw, error in ((b"{not json", "body_not_strict_json"), (b'{"a": 1, "a": 2}', "body_not_strict_json"),
                           (b'{"apiVersion": "v1", "kind": "SecretList", "metadata": {"resourceVersion": "1"}, "items": []}',
                            "list_shape_invalid"),
                           (b'{"apiVersion": "v1", "kind": "EventList", "metadata": {}, "items": []}', "collection_rv_missing"),
                           (b"x" * (cl.MAX_PAGE_BYTES + 1), "page_too_large")):
            with self.subTest(error=error):
                result = collect(F.FakeApi(faults={"events": {"raw": raw}}))
                self.assertEqual((result.outcome, result.error, result.items), ("invalid", error, []))
        result = collect(F.FakeApi(faults={"events": {"duplicate": True}}))
        self.assertEqual((result.outcome, result.error), ("invalid", "item_duplicate"))

    def test_transport_errors_are_codes(self):
        class Down:
            def get(self, path):
                raise cl.CollectorError("timeout")

        self.assertEqual(collect(Down()).outcome, "timeout")
        Down.get = lambda self, path: (_ for _ in ()).throw(cl.CollectorError("unavailable"))
        self.assertEqual(collect(Down()).outcome, "unavailable")


class SanitizationTests(unittest.TestCase):
    def test_nothing_planted_survives_projection(self):
        api = F.FakeApi()
        results = [collect(api, resource=r) for r in ("pods", "replicasets", "deployments", "events")]
        self.assertEqual(F.scan([json.dumps([r.items for r in results])]), set())
        pod = results[0].items[0]
        self.assertEqual(set(pod), {"metadata", "spec", "status"})
        self.assertNotIn("annotations", pod["metadata"])
        self.assertEqual(set(pod["spec"]), {"containers", "volumes", "nodeName"})
        self.assertGreater(results[0].counts["secret_env_refs"], 0)
        self.assertGreater(results[0].counts["secret_or_projected_volumes"], 0)
        rs = results[1].items[0]
        self.assertEqual(rs["metadata"]["annotations"], {"deployment.kubernetes.io/revision": "1"})


class RunTests(unittest.TestCase):
    def run_collector(self, api, **overrides):
        out = F.tempdir(self) / "run"
        clock = F.Clock()
        collections, conversion, report = co.run(config(**overrides), out, transport=api, wall_ms=clock.wall_ms,
                                                 monotonic=clock.monotonic)
        return out, collections, conversion, report

    def test_successful_collections_are_partial_with_zero_verified_coverage(self):
        out, collections, conversion, report = self.run_collector(F.FakeApi())
        self.assertEqual({c.resource: c.outcome for c in collections},
                         {"deployments": "consistent", "events": "consistent", "pods": "consistent",
                          "replicasets": "consistent"})
        outcomes = {a["query_id"]: (a["outcome"], a["reason"], a["coverage_claimed"]) for a in conversion.report["acquisitions"]}
        self.assertEqual(outcomes, {"k8s.configmaps": ("failed", "source_unavailable", False),  # never collected (D3)
                                    "k8s.deployments": ("partial", "continuity_lost", False),
                                    "k8s.events": ("partial", "continuity_lost", False),
                                    "k8s.pods": ("partial", "continuity_lost", False)})
        loaded = B.load(out / "bundle")
        self.assertFalse([b for b in loaded.batches if b["outcome"] in (acq.COMPLETE, acq.EMPTY)])
        frozen = fi.seal(loaded.plan, loaded.registry, list(loaded.batches))
        self.assertTrue(all(a["verified_ms"] == 0 for a in frozen.root()["acquisitions"]))
        self.assertEqual(frozen.root()["status"], "incomplete")
        inv = C.investigate_offline(loaded)
        self.assertEqual(inv.result["outcome"]["status"], "abstained")
        self.assertNotEqual(inv.result["outcome"]["status"], "resolved")
        self.assertEqual(report["verified_coverage_ms"], 0)
        cursors = {b["query_id"]: b["cursor"]["after"] for b in loaded.batches}
        self.assertEqual((cursors["k8s.pods"], cursors["k8s.events"]), ("rv:3101", "rv:3104"))
        manifest = json.loads((out / "recording" / "recording.json").read_bytes())
        self.assertEqual((manifest["contract_version"], manifest["provenance"], manifest["clock"]["status"]),
                         (K.RECORDING_VERSION_V3, "collector", "unknown"))
        for r in manifest["responses"]:
            self.assertNotIn("snapshot_at", r)
            self.assertNotIn("coverage", r)

    def test_an_empty_list_is_partial_never_empty(self):
        items = F.planted_items()
        items["events"] = []
        out, _, conversion, _ = self.run_collector(F.FakeApi(items=items))
        a = next(a for a in conversion.report["acquisitions"] if a["query_id"] == "k8s.events")
        self.assertEqual((a["outcome"], a["observations"], a["coverage_claimed"]), ("partial", 0, False))

    def test_separate_kinds_are_separate_collections(self):
        out, collections, conversion, _ = self.run_collector(F.FakeApi())
        a = next(a for a in conversion.report["acquisitions"] if a["query_id"] == "k8s.deployments")
        self.assertEqual(a["collection_resource_versions"], {"deployments": "3102", "replicasets": "3103"})
        self.assertEqual((a["outcome"], a["reason"]), ("partial", "continuity_lost"))
        loaded = B.load(out / "bundle")
        deploy = next(b for b in loaded.batches if b["query_id"] == "k8s.deployments")
        self.assertFalse(deploy["cursor"]["after"].startswith("rv:"))  # two RVs are never joined into one

    def test_faults_become_gaps_not_coverage(self):
        api = F.FakeApi(faults={"pods": {"status": 403}, "replicasets": {"status": 503},
                                "events": {"rv_change_on_page": 2}})
        out, collections, conversion, report = self.run_collector(api, max_restarts=0)
        outcomes = {a["query_id"]: (a["outcome"], a["reason"]) for a in conversion.report["acquisitions"]}
        self.assertEqual(outcomes["k8s.pods"], ("denied", "authorization_denied"))
        self.assertEqual(outcomes["k8s.events"], ("failed", "invalid_response"))         # collection RV changed
        self.assertEqual(outcomes["k8s.deployments"], ("failed", "source_unavailable"))  # its ReplicaSets failed
        expired = F.FakeApi(faults={"events": {"gone_on_page": 2}})
        _, _, conversion, _ = self.run_collector(expired, max_restarts=0)
        a = next(a for a in conversion.report["acquisitions"] if a["query_id"] == "k8s.events")
        self.assertEqual((a["outcome"], a["reason"], a["response"]["events"]), ("failed", "source_unavailable", "expired"))
        self.assertEqual(C.investigate_offline(B.load(out / "bundle")).result["outcome"]["status"], "abstained")

    def test_truncation_is_partial_page_limit(self):
        _, _, conversion, _ = self.run_collector(F.FakeApi(), max_pages=1)
        a = next(a for a in conversion.report["acquisitions"] if a["query_id"] == "k8s.events")
        self.assertEqual((a["outcome"], a["reason"]), ("partial", "page_limit"))

    def test_nothing_sensitive_is_written_raised_or_logged(self):
        api = F.FakeApi(faults={"pods": {"status": 403}, "events": {"gone_on_page": 2}})
        logs, out_text, err_text = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with redirect_stdout(out_text), redirect_stderr(err_text):
                out, collections, conversion, report = self.run_collector(api, max_restarts=0)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual(F.scan([out, logs.getvalue(), out_text.getvalue(), err_text.getvalue(), json.dumps(report)]), set())
        for token in api.issued:
            self.assertEqual(F.scan([out]), set())
            for path in out.rglob("*"):
                if path.is_file():
                    self.assertNotIn(token.encode(), path.read_bytes())
        try:
            cl.collect_list(type("Boom", (), {"get": lambda self, p: (_ for _ in ()).throw(
                cl.CollectorError("unavailable"))})(), "secrets", "ca-demo")
        except cl.CollectorError as exc:
            self.assertEqual(F.scan([str(exc)]), set())

    def test_replay_is_deterministic(self):
        out, _, conversion, _ = self.run_collector(F.FakeApi())
        again = K.convert(out / "recording", V2)
        second = F.tempdir(self) / "bundle"
        again.write_bundle(second)
        tree = lambda root: {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}  # noqa: E731
        self.assertEqual(tree(out / "bundle"), tree(second))
        self.assertEqual(again.report_bytes(), conversion.report_bytes())
        out2, _, _, _ = self.run_collector(F.FakeApi())  # the same API and clock give the same bytes
        self.assertEqual(tree(out / "recording"), tree(out2 / "recording"))
        self.assertEqual(tree(out / "bundle"), tree(out2 / "bundle"))


class RecordingV3Tests(unittest.TestCase):
    def recording(self):
        out = F.tempdir(self) / "run"
        clock = F.Clock()
        co.run(config(), out, transport=F.FakeApi(), wall_ms=clock.wall_ms, monotonic=clock.monotonic)
        return out / "recording"

    def save(self, root, manifest):
        (root / "recording.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode())

    def refused(self, root, code):
        with self.assertRaises(K.RecordingError) as ctx:
            K.convert(root, V2)
        self.assertEqual(ctx.exception.code, code)

    def test_a_0_3_recording_cannot_carry_snapshot_or_coverage(self):
        for field, value in (("snapshot_at", "2026-10-15T08:00:01Z"),
                             ("coverage", {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T08:00:01Z"})):
            with self.subTest(field=field):
                root = self.recording()
                manifest = json.loads((root / "recording.json").read_bytes())
                manifest["responses"][0][field] = value
                self.save(root, manifest)
                self.refused(root, "recording_manifest_invalid")

    def test_a_0_3_recording_must_come_from_the_collector_with_an_unknown_clock(self):
        for change in ({"provenance": "hand-written"},
                       {"clock": {"clock_domain_id": "k8s-apiserver", "status": "declared", "offset_ms": 0,
                                  "offset_uncertainty_ms": 1, "continuity": "declared_continuous"}}):
            with self.subTest(change=list(change)):
                root = self.recording()
                self.save(root, {**json.loads((root / "recording.json").read_bytes()), **change})
                self.refused(root, "recording_manifest_invalid")

    def test_the_manifest_rv_must_match_the_collected_list(self):
        root = self.recording()
        manifest = json.loads((root / "recording.json").read_bytes())
        entry = next(r for r in manifest["responses"] if r["resource"] == "pods")
        entry["collection_resource_version"] = "9999"
        self.save(root, manifest)
        self.refused(root, "recording_manifest_conflict")

    def test_a_failed_collection_carries_no_file_or_rv(self):
        root = self.recording()
        manifest = json.loads((root / "recording.json").read_bytes())
        entry = next(r for r in manifest["responses"] if r["resource"] == "pods")
        entry["outcome"] = "denied"
        self.save(root, manifest)
        self.refused(root, "recording_manifest_invalid")


@unittest.skipUnless(F.openssl() or os.environ.get("CA_COLLECTOR_TLS_REQUIRE") == "1",
                     "openssl is not available to generate a throwaway test certificate")
class TlsTests(unittest.TestCase):
    def setUp(self):
        self.dir = F.tempdir(self)
        self.cert, self.key = F.make_cert(self.dir)
        self.token = F.write_token(self.dir)

    def serve(self, api, **kwargs):
        server = F.TlsServer(api, self.cert, self.key, **kwargs)
        self.addCleanup(server.close)
        return server

    def test_a_collection_over_verified_tls(self):
        api = F.FakeApi()
        server = self.serve(api)
        transport = cl.HttpsTransport(f"https://127.0.0.1:{server.port}", self.cert, self.token, timeout=10)
        self.assertNotIn("synthetic-test-token", repr(transport))
        result = cl.collect_list(transport, "events", "ca-demo", 2)
        self.assertEqual((result.outcome, result.pages), ("consistent", 2))
        out = self.dir / "run"
        co.run(config(server=f"https://127.0.0.1:{server.port}", ca_file=self.cert, token_file=self.token), out)
        self.assertEqual(F.scan([out]), set())
        self.assertNotIn(b"synthetic-test-token", b"".join(p.read_bytes() for p in out.rglob("*") if p.is_file()))

    def test_an_untrusted_certificate_is_refused(self):
        other = self.dir / "other"
        other.mkdir()
        other_cert, _ = F.make_cert(other)
        api = F.FakeApi()
        server = self.serve(api)
        transport = cl.HttpsTransport(f"https://127.0.0.1:{server.port}", other_cert, self.token, timeout=10)
        result = cl.collect_list(transport, "events", "ca-demo", 2)
        self.assertEqual((result.outcome, result.error), ("unavailable", "unavailable"))
        self.assertEqual(api.requests, [])  # nothing reached the handler

    def test_redirects_are_not_followed(self):
        api = F.FakeApi()
        server = self.serve(api, redirect=True)
        transport = cl.HttpsTransport(f"https://127.0.0.1:{server.port}", self.cert, self.token, timeout=10)
        result = cl.collect_list(transport, "events", "ca-demo", 2)
        self.assertEqual((result.outcome, result.error, len(api.requests)), ("unavailable", "http_302", 1))

    def test_a_wrong_token_is_denied_and_the_body_is_not_kept(self):
        api = F.FakeApi()
        server = self.serve(api)
        bad = self.dir / "bad-token"
        bad.write_text("not-the-token-00000000000000000000000000000", encoding="ascii")
        transport = cl.HttpsTransport(f"https://127.0.0.1:{server.port}", self.cert, bad, timeout=10)
        result = cl.collect_list(transport, "pods", "ca-demo", 2)
        self.assertEqual((result.outcome, result.error, result.items), ("denied", "http_401", []))


if __name__ == "__main__":
    unittest.main()
