"""CA-P2-006b local read-only API: offline tests (no database; real HTTP on 127.0.0.1).

Results come from the in-memory engine path; the PostgreSQL integration tests cover the real
verify-on-read backend.
"""

import http.client
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
from pathlib import Path

import _api_support as A
from cloud_autopsy.api import API_VERSION
from cloud_autopsy.api import grants as G
from cloud_autopsy.api import service as svc
from cloud_autopsy.api.transport import LoopbackServer


def call(service, path, token=None, method="GET", headers=None):
    hdrs = {"Authorization": f"Bearer {token}"} if token else {}
    hdrs.update(headers or {})
    response = service.handle(method, path, _Headers(hdrs))
    return response.status, json.loads(response.body)


class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class GrantTests(unittest.TestCase):
    def assert_code(self, code, fn):
        with self.assertRaises(G.GrantError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)

    def test_only_hashes_are_stored_and_tokens_are_strong(self):
        path, tokens = A.provision({"a": [A.RUNS["config-cause"]]})
        text = path.read_text(encoding="utf-8")
        self.assertNotIn(tokens["a"], text)
        self.assertGreaterEqual(len(tokens["a"]), 43)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_authentication_is_exact(self):
        path, tokens = A.provision({"a": [A.RUNS["config-cause"]], "b": [A.RUNS["no-symptom"]]})
        grants = G.load(path)
        self.assertEqual(grants.authenticate(f"Bearer {tokens['a']}").name, "a")
        self.assertEqual(grants.authenticate(f"Bearer {tokens['b']}").name, "b")
        for bad in (None, "", tokens["a"], f"bearer {tokens['a']}", f"Bearer {tokens['a']}x",
                    f"Bearer {tokens['a'][:-1]}", f"Basic {tokens['a']}", "Bearer " + "A" * 43,
                    f"Bearer  {tokens['a']}", f"Bearer {tokens['a']} "):
            with self.subTest(bad=str(bad)[:20]):
                self.assertIsNone(grants.authenticate(bad))

    def test_grants_name_runs_explicitly(self):
        record, _ = G.issue({"a": [A.RUNS["config-cause"]]})
        for mutate in (lambda r: r["grants"][0].update(run_ids=["*"]),
                       lambda r: r["grants"][0].update(run_ids=[]),
                       lambda r: r["grants"][0].update(run_ids=[A.RUNS["config-cause"].upper()]),
                       lambda r: r["grants"][0].update(run_ids=[A.RUNS["config-cause"]] * 2),
                       lambda r: r["grants"][0].update(extra=True),
                       lambda r: r["grants"].append(dict(r["grants"][0])),
                       lambda r: r.update(contract_version="ca-api-grants/9.9")):
            broken = json.loads(json.dumps(record))
            mutate(broken)
            with self.subTest(mutation=json.dumps(broken)[-60:]):
                with self.assertRaises(G.GrantError):
                    G.parse(broken)

    def test_grants_file_must_live_outside_git_and_be_private(self):
        directory = Path(tempfile.mkdtemp(prefix="ca-api-repo-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        (directory / ".git").mkdir()
        record, _ = G.issue({"a": [A.RUNS["config-cause"]]})
        inside = directory / "nested" / "grants.json"
        inside.parent.mkdir()
        G.write_private(inside, json.dumps(record).encode())
        self.assert_code("grants_in_repository", lambda: G.load(inside))
        outside = Path(tempfile.mkdtemp(prefix="ca-api-outside-")) / "grants.json"
        G.write_private(outside, b'{"contract_version": "x", "contract_version": "y"}')
        self.assert_code("grants_invalid", lambda: G.load(outside))
        if os.name == "posix":
            loose = outside.with_name("loose.json")
            G.write_private(loose, json.dumps(record).encode())
            os.chmod(loose, 0o644)
            self.assert_code("grants_permissions", lambda: G.load(loose))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.service, self.tokens, self.backend = A.service()
        self.all, self.one = self.tokens["all"], self.tokens["one"]

    def test_health_and_readiness(self):
        self.assertEqual(call(self.service, "/healthz"), (200, {"api_version": API_VERSION, "status": "ok"}))
        self.assertEqual(call(self.service, "/readyz")[0], 200)
        self.backend.ready = False
        self.assertEqual(call(self.service, "/readyz"), (503, {"error": "not_ready"}))

    def test_every_route_serves_the_verified_result(self):
        for variant, run_id in A.RUNS.items():
            expected = self.backend.results[run_id]
            with self.subTest(variant=variant):
                status, body = call(self.service, f"/v1/runs/{run_id}/result", self.all)
                self.assertEqual(status, 200)
                self.assertEqual((body["verified"], body["run_id"], body["result_digest"]),
                                 (True, run_id, expected.result_digest))
                self.assertEqual(body["data"], expected.result)
                self.assertEqual(call(self.service, f"/v1/runs/{run_id}/timeline", self.all)[1]["data"],
                                 expected.result["timeline"])
                hyp = call(self.service, f"/v1/runs/{run_id}/hypotheses", self.all)[1]["data"]
                self.assertEqual((hyp["outcome"], hyp["hypotheses"]),
                                 (expected.result["outcome"], expected.result["hypotheses"]))
                cites = call(self.service, f"/v1/runs/{run_id}/citations", self.all)[1]["data"]
                self.assertEqual(cites["gaps"], expected.result["gaps"])
                for h in cites["hypotheses"]:
                    for evidence_id in h["cited_evidence_ids"]:
                        status, ev = call(self.service, f"/v1/runs/{run_id}/evidence/{evidence_id.split(':')[1]}",
                                          self.all)
                        self.assertEqual(status, 200)
                        self.assertEqual(ev["data"]["record"], expected.evidence[evidence_id]["record"])
                        self.assertIn(h["hypothesis_id"], ev["data"]["cited_by_hypothesis_ids"])

    def test_tokens_are_bound_to_their_runs(self):
        allowed = A.RUNS["config-cause"]
        self.assertEqual(call(self.service, f"/v1/runs/{allowed}/result", self.one)[0], 200)
        for run_id in [r for r in A.RUNS.values() if r != allowed] + [A.UNKNOWN]:
            self.backend.calls.clear()
            self.assertEqual(call(self.service, f"/v1/runs/{run_id}/result", self.one),
                             (403, {"error": "run_not_authorized"}))
            self.assertEqual(self.backend.calls, [])  # refused before any database access

    def test_refusals(self):
        run = A.RUNS["config-cause"]
        other_evidence = next(iter(self.backend.results[A.RUNS["no-symptom"]].evidence))
        own = set(self.backend.results[run].evidence)
        foreign = next(e for e in self.backend.results[A.RUNS["symptom-before-change"]].evidence if e not in own)
        cases = [
            ("GET", f"/v1/runs/{run}/result", None, 401, "invalid_token"),
            ("GET", f"/v1/runs/{run}/result", "x" * 43, 401, "invalid_token"),
            ("GET", f"/v1/runs/{A.UNKNOWN}/result", self.all, 404, "run_not_found"),
            ("GET", f"/v1/runs/{A.TAMPERED}/result", self.all, 409, "result_unverifiable"),
            ("GET", f"/v1/runs/{A.DOWN}/result", self.all, 503, "database_unavailable"),
            ("GET", f"/v1/runs/{run.upper()}/result", self.all, 400, "invalid_run_id"),
            ("GET", "/v1/runs/not-a-uuid/result", self.all, 400, "invalid_run_id"),
            ("GET", f"/v1/runs/{run}/result?verify=false", self.all, 400, "invalid_path"),
            ("GET", f"/v1/runs/{run}/%72esult", self.all, 400, "invalid_path"),
            ("GET", f"/v1/runs/{run}/../{A.RUNS['no-symptom']}/result", self.all, 404, "route_not_found"),
            ("GET", f"/v1/runs/{run}/raw", self.all, 404, "route_not_found"),
            ("GET", f"/v1/runs/{run}/evidence/not-an-id", self.all, 400, "invalid_evidence_id"),
            ("GET", f"/v1/runs/{run}/evidence/{foreign.split(':')[1]}", self.all, 404, "evidence_not_found"),
            ("GET", f"/v1/runs/{run}/evidence/{foreign.split(':')[1].upper()}", self.all, 400, "invalid_evidence_id"),
            ("GET", "/v1/runs/" + "a" * 300, self.all, 414, "path_too_long"),
            ("POST", f"/v1/runs/{run}/result", self.all, 405, "method_not_allowed"),
            ("DELETE", f"/v1/runs/{run}/result", self.all, 405, "method_not_allowed"),
        ]
        self.assertIsNotNone(other_evidence)
        for method, path, token, status, code in cases:
            with self.subTest(path=path[-50:], method=method):
                got_status, body = call(self.service, path, token, method)
                self.assertEqual((got_status, body["error"]), (status, code))
                self.assertNotIn("data", body)  # never a fallback payload
        tampered = call(self.service, f"/v1/runs/{A.TAMPERED}/result", self.all)[1]
        self.assertEqual(tampered, {"error": "result_unverifiable", "reason": "replay_mismatch"})
        self.assertEqual(call(self.service, f"/v1/runs/{run}/result", self.all, headers={"Content-Length": "5"}),
                         (413, {"error": "request_body_not_allowed"}))
        self.assertEqual(self.service.handle("GET", f"/v1/runs/{run}/result",
                                             _Headers(Authorization=f"Bearer {self.all}"), 10_000).status, 431)

    def test_response_size_is_bounded(self):
        run = A.RUNS["config-cause"]
        big = self.backend.results[run]
        big.result = {**big.result, "timeline": {"entries": ["x" * 1000] * 5000}}
        self.assertEqual(call(self.service, f"/v1/runs/{run}/timeline", self.all), (500, {"error": "response_too_large"}))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service, cls.tokens, _ = A.service()
        cls.server = LoopbackServer(cls.service, 0, quiet=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, token=None, body=None, headers=None):
        con = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        hdrs = {"Authorization": f"Bearer {token}"} if token else {}
        hdrs.update(headers or {})
        con.request(method, path, body=body, headers=hdrs)
        response = con.getresponse()
        data = response.read()
        con.close()
        return response, data

    def test_bound_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for host in ("0.0.0.0", "", "localhost", "::1", "192.0.2.1"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    LoopbackServer(self.service, 0, host=host)

    def test_http_round_trip_and_headers(self):
        run = A.RUNS["config-cause"]
        response, data = self.request("GET", f"/v1/runs/{run}/citations", self.tokens["all"])
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.getheader("Server"), "ca-api")
        self.assertTrue(json.loads(data)["verified"])

    def test_http_refusals(self):
        run = A.RUNS["config-cause"]
        self.assertEqual(self.request("GET", f"/v1/runs/{run}/result")[0].status, 401)
        self.assertEqual(self.request("GET", f"/v1/runs/{A.RUNS['no-symptom']}/result", self.tokens["one"])[0].status,
                         403)
        self.assertEqual(self.request("POST", f"/v1/runs/{run}/result", self.tokens["all"], body=b"{}")[0].status, 405)
        self.assertEqual(self.request("PUT", f"/v1/runs/{run}/result", self.tokens["all"], body=b"{}")[0].status, 405)
        self.assertEqual(self.request("GET", f"/v1/runs/{run}/result", self.tokens["all"], body=b"x" * 10)[0].status,
                         413)
        self.assertEqual(self.request("GET", f"/v1/runs/{run}/result", self.tokens["all"],
                                      headers={"X-Pad": "p" * 9000})[0].status, 431)


if __name__ == "__main__":
    unittest.main()
