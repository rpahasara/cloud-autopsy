"""CA-P2-006d run summaries (``/v1/summaries/{page}``): offline tests, no database.

Only the caller's own granted runs are listed; each is verified through the loader before any
field is returned; failures are reported by state alone; pages are bounded and the work per
request stays inside one slot of the verified-read gate.
"""

import json
import unittest
import uuid

import _api_support as A
from cloud_autopsy.api import service as svc
from test_api_offline import _Headers, call

RESULT_KEYS = {"run_id", "state", "verified", "result_digest", "plan_id", "window", "outcome", "manifest", "evidence",
               "gaps", "hypotheses", "ordering"}


def many(n, tag):
    return [str(uuid.uuid5(uuid.NAMESPACE_URL, f"ca-summaries-test/{tag}/{i}")) for i in range(n)]


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.service, self.tokens, self.backend = A.service()

    def page(self, n, token="all", service=None):
        return call(service or self.service, f"/v1/summaries/{n}", self.tokens.get(token, token) if token else None)

    def test_only_the_tokens_own_runs_are_listed(self):
        status, body = self.page(1, "one")
        self.assertEqual(status, 200)
        self.assertEqual(body["granted_total"], 1)
        self.assertEqual([i["run_id"] for i in body["items"]], [A.RUNS["config-cause"]])
        status, body = self.page(1)
        granted = sorted(list(A.RUNS.values()) + [A.TAMPERED, A.DOWN, A.UNKNOWN])
        self.assertEqual([i["run_id"] for i in body["items"]], granted)
        self.assertEqual(body["granted_total"], len(granted))

    def test_authentication_and_page_format(self):
        self.assertEqual(self.page(1, None)[0], 401)
        self.assertEqual(self.page(1, "x" * 43)[0], 401)
        self.assertEqual(self.page("0"), (400, {"error": "invalid_page"}))
        self.assertEqual(self.page("01"), (400, {"error": "invalid_page"}))
        self.assertEqual(self.page(2), (404, {"error": "page_not_found"}))
        for bad in ("/v1/summaries", "/v1/summaries/", "/v1/summaries/a", "/v1/summaries/12345", "/v1/summaries/1/2"):
            with self.subTest(path=bad):
                self.assertEqual(call(self.service, bad, self.tokens["all"])[0], 404)
        self.assertEqual(call(self.service, "/v1/summaries/1?all=1", self.tokens["all"])[0], 400)
        self.assertEqual(self.service.handle("POST", "/v1/summaries/1", _Headers({})).status, 405)

    def test_pages_are_bounded_disjoint_and_cover_the_grant_once(self):
        runs = many(25, "pages") + [A.RUNS["config-cause"]]
        path, tokens = A.provision({"big": runs})
        backend = A.FakeBackend()
        service = svc.ApiService(A.G.load(path), backend.load_verified, backend.check_ready)
        seen = []
        for n in (1, 2, 3):
            backend.calls.clear()
            status, body = call(service, f"/v1/summaries/{n}", tokens["big"])
            self.assertEqual(status, 200)
            self.assertEqual((body["page"], body["pages"], body["page_size"], body["granted_total"]), (n, 3, 10, 26))
            self.assertLessEqual(len(body["items"]), svc.SUMMARY_PAGE_SIZE)
            self.assertEqual(backend.calls, [i["run_id"] for i in body["items"]])  # one verification per listed run, no more
            seen += [i["run_id"] for i in body["items"]]
        self.assertEqual(seen, sorted(runs))
        self.assertEqual(call(service, "/v1/summaries/4", tokens["big"]), (404, {"error": "page_not_found"}))

    def test_runs_without_a_verified_result_carry_only_their_state(self):
        body = self.page(1)[1]
        by_id = {i["run_id"]: i for i in body["items"]}
        self.assertEqual(by_id[A.TAMPERED], {"run_id": A.TAMPERED, "state": "unverifiable", "reason": "replay_mismatch"})
        self.assertEqual(by_id[A.UNKNOWN], {"run_id": A.UNKNOWN, "state": "not_found"})
        self.assertEqual(by_id[A.DOWN], {"run_id": A.DOWN, "state": "unavailable"})
        for variant, run_id in A.RUNS.items():
            with self.subTest(variant=variant):
                self.assertEqual(set(by_id[run_id]), RESULT_KEYS)
                self.assertEqual(by_id[run_id]["state"], "verified")
                self.assertIs(by_id[run_id]["verified"], True)

    def test_summary_figures_are_the_verified_results_own(self):
        body = self.page(1)[1]
        by_id = {i["run_id"]: i for i in body["items"]}
        for variant, run_id in A.RUNS.items():
            with self.subTest(variant=variant):
                item, r = by_id[run_id], self.backend.results[run_id].result
                self.assertEqual(item["result_digest"], r["result_digest"])
                self.assertEqual(item["plan_id"], r["inputs"]["plan_id"])
                self.assertEqual(item["window"], r["inputs"]["window"])
                self.assertEqual(item["outcome"], {k: r["outcome"][k] for k in ("status", "mechanism", "reasons")})
                members = {e["evidence_id"] for e in r["timeline"]["entries"]}
                self.assertEqual(item["evidence"]["records"], len(members))
                self.assertEqual(sum(v["records"] for v in item["evidence"]["by_source"].values()), len(members))
                self.assertEqual(sum(v["gaps"] for v in item["evidence"]["by_source"].values()), len(r["gaps"]))
                self.assertLessEqual(item["evidence"]["cited"], item["evidence"]["records"])
                self.assertEqual(item["gaps"]["total"], len(r["gaps"]))
                self.assertEqual(sum(item["hypotheses"].values()), len(r["hypotheses"]))
                self.assertEqual(item["ordering"]["unplaced"], sum(1 for e in r["timeline"]["entries"] if not e["reference_ms"]))
        resolved = [i for i in body["items"] if i.get("outcome", {}).get("status") == "resolved"]
        self.assertEqual([i["plan_id"] for i in resolved], ["ca-scenario-001-config-cause"])

    def test_a_page_takes_one_slot_of_the_verified_read_gate(self):
        service, tokens, backend = A.service()
        for _ in range(svc.DEFAULT_MAX_IN_FLIGHT):
            self.assertTrue(service._work.acquire(blocking=False))
        try:
            response = service.handle("GET", "/v1/summaries/1", _Headers({"Authorization": f"Bearer {tokens['all']}"}))
            self.assertEqual((response.status, json.loads(response.body)), (503, {"error": "overloaded"}))
            self.assertIn(("Retry-After", "1"), response.headers)
            self.assertEqual(backend.calls, [])
        finally:
            for _ in range(svc.DEFAULT_MAX_IN_FLIGHT):
                service._work.release()
        self.assertEqual(call(service, "/v1/summaries/1", tokens["all"])[0], 200)  # free again afterwards

    def test_preview_items_are_never_labelled_verified(self):
        grants_path, tokens = A.provision({"a": list(A.RUNS.values())})
        backend = A.FakeBackend()
        service = svc.ApiService(A.G.load(grants_path), backend.load_verified, backend.check_ready, preview=True)
        status, body = call(service, "/v1/summaries/1", tokens["a"])
        self.assertEqual(body["data_source"], "synthetic-preview")
        self.assertTrue(all(i["state"] == "preview" and i["verified"] is False for i in body["items"]))
        self.assertIn("not read from or verified against", body["verification"])

    def test_access_log_template_and_response_bound(self):
        self.assertEqual(self.service.route_template("GET", "/v1/summaries/3"), ("GET", "/v1/summaries/{page}"))
        self.assertEqual(self.service.route_template("GET", "/v1/summaries/x"), ("GET", "<rejected>"))
        response = self.service.handle("GET", "/v1/summaries/1", _Headers({"Authorization": f"Bearer {self.tokens['all']}"}))
        self.assertLess(len(response.body), svc.MAX_RESPONSE_BYTES)


if __name__ == "__main__":
    unittest.main()
