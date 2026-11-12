"""CA-P2-004b run lifecycle status in the API: offline tests, no database.

- Status access is explicit and run-scoped (grants contract 0.2, ``status_run_ids``).
- A status-only run never reaches the result loader, and every result, timeline, hypotheses,
  citations and evidence route still answers 403 for it.
- Lifecycle items and status documents are never verified and carry no result fields.
"""

import json
import unittest
import uuid
from types import SimpleNamespace

import _api_support as A
from cloud_autopsy.api import grants as G
from cloud_autopsy.api import service as svc
from test_api_offline import call
from test_summaries_offline import RESULT_KEYS


def run(tag):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ca-status-test/{tag}"))


COLLECTING, SEALING, SEALED, FAILED, STATUS_DOWN = (run(t) for t in ("collecting", "sealing", "sealed", "failed", "down"))
VERIFIED = A.RUNS["config-cause"]
NEVER_GRANTED = run("never-granted")


def status(state, reason=None, expired=None):
    record = {"state": state, "failure_reason": reason, "lease_expired": expired}
    return SimpleNamespace(state=state, to_record=lambda: dict(record))


class FakeStatus:
    def __init__(self):
        self.calls = []
        self.known = {COLLECTING: status("collecting"), SEALING: status("sealing", expired=False),
                      SEALED: status("sealed"), FAILED: status("failed", "seal:limit_exceeded"),
                      VERIFIED: status("sealed")}

    def __call__(self, run_id):
        self.calls.append(run_id)
        if run_id == STATUS_DOWN:
            raise svc.BackendDown()
        return self.known.get(run_id)


def provision(result_runs, status_runs):
    import tempfile
    from pathlib import Path
    directory = Path(tempfile.mkdtemp(prefix="ca-api-grants-"))
    record, tokens = G.issue(result_runs, status_runs)
    path = directory / "grants.json"
    G.write_private(path, json.dumps(record).encode("utf-8"))
    return path, tokens


class GrantContractTests(unittest.TestCase):
    def record(self, **grant):
        entry = {"name": "a", "token_sha256": "0" * 64, "run_ids": [], "status_run_ids": [FAILED], **grant}
        return {"contract_version": G.GRANTS_VERSION_STATUS, "grants": [entry]}

    def test_status_only_grants_are_explicit_disjoint_and_bounded(self):
        grant = list(G.parse(self.record())._grants)[0]
        self.assertTrue(grant.may_view_status(FAILED))
        self.assertFalse(grant.authorizes(FAILED))  # status never implies result access
        self.assertFalse(grant.may_view_status(NEVER_GRANTED))
        for bad in ({"run_ids": [FAILED]},                       # in both lists
                    {"status_run_ids": []},                      # names no run at all
                    {"status_run_ids": ["*"]},                   # no wildcard
                    {"status_run_ids": [FAILED, FAILED]},        # duplicates
                    {"status_run_ids": [FAILED.upper()]},        # not canonical
                    {"status_run_ids": [run(str(i)) for i in range(G.MAX_RUNS_PER_GRANT + 1)]}):
            with self.subTest(bad=list(bad)), self.assertRaises(G.GrantError):
                G.parse(self.record(**bad))
        extra = self.record()
        extra["grants"][0]["status"] = "all"
        with self.assertRaises(G.GrantError):
            G.parse(extra)

    def test_version_0_1_is_unchanged(self):
        record, _ = G.issue({"a": [VERIFIED]})
        self.assertEqual(record["contract_version"], G.GRANTS_VERSION)
        self.assertNotIn("status_run_ids", record["grants"][0])
        record["grants"][0]["status_run_ids"] = [FAILED]  # 0.1 has no status field
        with self.assertRaises(G.GrantError):
            G.parse(record)
        with self.assertRaises(G.GrantError):  # and 0.1 still needs at least one result run
            G.parse({"contract_version": G.GRANTS_VERSION,
                     "grants": [{"name": "a", "token_sha256": "0" * 64, "run_ids": []}]})


class StatusRouteTests(unittest.TestCase):
    def setUp(self):
        path, self.tokens = provision({"mixed": [VERIFIED, SEALING], "other": [A.RUNS["no-symptom"]]},
                                      {"mixed": [COLLECTING, SEALED, FAILED, STATUS_DOWN, NEVER_GRANTED.replace("a", "b")]})
        self.backend, self.status = A.FakeBackend(), FakeStatus()
        self.service = svc.ApiService(G.load(path), self.backend.load_verified, self.backend.check_ready,
                                      load_status=self.status)

    def get(self, path, token="mixed"):
        return call(self.service, path, self.tokens.get(token, token) if token else None)

    def test_status_is_run_scoped_and_never_verified(self):
        status, body = self.get(f"/v1/runs/{FAILED}/status")
        self.assertEqual(status, 200)
        self.assertEqual((body["verified"], body["access"], body["lifecycle"]),
                         (False, "status", {"state": "failed", "failure_reason": "seal:limit_exceeded",
                                            "lease_expired": None}))
        self.assertEqual(set(body), {"api_version", "run_id", "verified", "access", "lifecycle", "note"})
        status, body = self.get(f"/v1/runs/{VERIFIED}/status")
        self.assertEqual((status, body["access"], body["verified"]), (200, "result", False))
        self.status.calls.clear()
        # another token's run, a run in no grant, a bad token: refused before any lookup
        self.assertEqual(self.get(f"/v1/runs/{A.RUNS['no-symptom']}/status"), (403, {"error": "run_not_authorized"}))
        self.assertEqual(self.get(f"/v1/runs/{NEVER_GRANTED}/status"), (403, {"error": "run_not_authorized"}))
        self.assertEqual(self.get(f"/v1/runs/{FAILED}/status", None)[0], 401)
        self.assertEqual(self.get(f"/v1/runs/{FAILED}/status", "x" * 43)[0], 401)
        self.assertEqual(self.get(f"/v1/runs/{FAILED.upper()}/status")[0], 400)
        self.assertEqual(self.status.calls, [])
        self.assertEqual(self.get(f"/v1/runs/{STATUS_DOWN}/status"), (503, {"error": "database_unavailable"}))
        self.assertEqual(self.service.route_template("GET", f"/v1/runs/{FAILED}/status"),
                         ("GET", "/v1/runs/{run_id}/status"))

    def test_status_access_never_opens_results_or_evidence(self):
        for run_id in (COLLECTING, SEALED, FAILED):
            for path in (f"/v1/runs/{run_id}/result", f"/v1/runs/{run_id}/timeline", f"/v1/runs/{run_id}/hypotheses",
                         f"/v1/runs/{run_id}/citations", f"/v1/runs/{run_id}/evidence/{'0' * 64}"):
                with self.subTest(path=path):
                    self.assertEqual(self.get(path), (403, {"error": "run_not_authorized"}))
        self.assertEqual(self.backend.calls, [])

    def test_summaries_list_lifecycle_states_without_loading_status_only_results(self):
        status, body = self.get("/v1/summaries/1")
        self.assertEqual(status, 200)
        self.assertEqual(body["granted_total"], 7)
        items = {i["run_id"]: i for i in body["items"]}
        expected = {COLLECTING: ("collecting", "status"), SEALED: ("sealed", "status"),
                    FAILED: ("run_failed", "status"), SEALING: ("sealing", "result")}
        for run_id, (state, access) in expected.items():
            with self.subTest(state=state):
                self.assertEqual((items[run_id]["state"], items[run_id]["access"], items[run_id]["verified"]),
                                 (state, access, False))
                self.assertEqual(set(items[run_id]), {"run_id", "state", "verified", "access", "lifecycle"})
                self.assertFalse(set(items[run_id]) & (RESULT_KEYS - {"run_id", "state", "verified"}))
        self.assertEqual(items[FAILED]["lifecycle"]["failure_reason"], "seal:limit_exceeded")
        self.assertEqual(items[STATUS_DOWN]["state"], "unavailable")
        self.assertEqual(items[VERIFIED]["state"], "verified")
        self.assertEqual(items[NEVER_GRANTED.replace("a", "b")]["state"], "not_found")
        # the result loader saw only result-granted runs; never a status-only one
        self.assertEqual(sorted(self.backend.calls), sorted([VERIFIED, SEALING]))
        self.assertTrue(all(i.get("verified") is not True for i in body["items"] if i["run_id"] != VERIFIED))

    def test_a_sealed_result_run_without_a_stored_result_is_awaiting_result(self):
        path, tokens = provision({"r": [SEALED]}, {"r": []})
        service = svc.ApiService(G.load(path), self.backend.load_verified, self.backend.check_ready,
                                 load_status=self.status)
        item = call(service, "/v1/summaries/1", tokens["r"])[1]["items"][0]
        self.assertEqual((item["state"], item["verified"], item["access"]), ("awaiting_result", False, "result"))

    def test_without_a_status_loader_nothing_changes(self):
        path, tokens = provision({"r": [A.UNKNOWN]}, {"r": [FAILED]})
        service = svc.ApiService(G.load(path), self.backend.load_verified, self.backend.check_ready)
        self.assertEqual(call(service, f"/v1/runs/{FAILED}/status", tokens["r"]), (404, {"error": "status_not_available"}))
        items = {i["run_id"]: i["state"] for i in call(service, "/v1/summaries/1", tokens["r"])[1]["items"]}
        self.assertEqual(items, {A.UNKNOWN: "not_found", FAILED: "unavailable"})


if __name__ == "__main__":
    unittest.main()
