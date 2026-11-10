"""CA-P2-006b local read-only API against a real disposable PostgreSQL (synthetic data only).

Every result is served through ``results.load_verified_result`` on a fresh ``ca_engine``
connection per request. Tampering is simulated with the bootstrap superuser
(``session_replication_role = replica``), standing in for direct database access.
"""

import hashlib
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

import _db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser"))
import _cdp  # noqa: E402  (standard-library CDP client, test-only)

BROWSER_OK = bool(_cdp.find_browser()) or os.environ.get("CA_BROWSER_REQUIRE") == "1"

if _db.AVAILABLE:
    from cloud_autopsy.api import grants as G
    from cloud_autopsy.api import server
    from cloud_autopsy.app import pipeline
    from cloud_autopsy.contracts import canonical
    from cloud_autopsy.db import results
    from cloud_autopsy.engine import RESULT_DIGEST_ALGORITHM
    from cloud_autopsy.synthetic import scenario_001 as scenario


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        roles = {r: cls.fx.connect(r) for r in ("ca_planner", "ca_ingest", "ca_sealer", "ca_engine",
                                                "ca_result_writer")}
        cls.engine = roles["ca_engine"]
        cls.runs, cls.stored = {}, {}
        extra = [("to-tamper", "config-cause"), ("to-malform", "config-cause"), ("to-misshape", "no-symptom")]
        for key, variant in [(v, v) for v in scenario.VARIANTS] + extra:
            run_id, _, _ = pipeline.persist_and_seal(roles, variant)
            outcome, investigation = pipeline.record_result(roles["ca_engine"], roles["ca_result_writer"], run_id)
            assert outcome == results.STORED
            cls.runs[key], cls.stored[key] = run_id, investigation
        cls.unknown = str(uuid.uuid4())
        cls.secret_dir = Path(tempfile.mkdtemp(prefix="ca-api-it-"))
        record, cls.tokens = G.issue({"all": list(cls.runs.values()) + [cls.unknown],
                                      "one": [cls.runs["config-cause"]]})
        grants_path = cls.secret_dir / "grants.json"
        G.write_private(grants_path, json.dumps(record).encode("utf-8"))
        cls.grants_path = grants_path
        endpoint = _db.endpoint(cls.fx.name)
        connect = server.engine_connector(endpoint.host, endpoint.port, endpoint.database, cls.fx.passwords["ca_engine"])
        cls.connect = staticmethod(connect)  # a plain function stored on the class must not bind ``self``
        cls.server = server.build(grants_path, connect, quiet=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.secret_dir, ignore_errors=True)
        cls.fx.close()

    def get(self, path, token="all", method="GET", port=None):
        con = http.client.HTTPConnection("127.0.0.1", port or self.server.port, timeout=30)
        con.request(method, path, headers={"Authorization": f"Bearer {self.tokens[token]}"} if token else {})
        response = con.getresponse()
        body = json.loads(response.read())
        con.close()
        return response.status, body

    def test_health_and_readiness(self):
        self.assertEqual(self.get("/healthz", None)[0], 200)
        self.assertEqual(self.get("/readyz", None), (200, {"api_version": "ca-api/0.1-provisional", "status": "ready"}))

    def test_all_six_stored_results_and_citations_are_served_verified(self):
        for variant in scenario.VARIANTS:
            run_id, stored = self.runs[variant], self.stored[variant]
            with self.subTest(variant=variant):
                status, body = self.get(f"/v1/runs/{run_id}/result")
                self.assertEqual(status, 200)
                self.assertTrue(body["verified"])
                self.assertEqual(body["result_digest"], stored.result["result_digest"])
                self.assertEqual(canonical.canonical_bytes(body["data"]), stored.result_bytes)  # exact bytes
                self.assertEqual(self.get(f"/v1/runs/{run_id}/timeline")[1]["data"], stored.result["timeline"])
                hyp = self.get(f"/v1/runs/{run_id}/hypotheses")[1]["data"]
                self.assertEqual(hyp["outcome"], stored.result["outcome"])
                cites = self.get(f"/v1/runs/{run_id}/citations")[1]["data"]
                cited = sorted({e for h in cites["hypotheses"] for e in h["cited_evidence_ids"]})
                self.assertTrue(cited)
                for evidence_id in cited:
                    status, ev = self.get(f"/v1/runs/{run_id}/evidence/{evidence_id.split(':')[1]}")
                    self.assertEqual(status, 200)
                    self.assertEqual(ev["data"]["evidence_id"], evidence_id)
                    self.assertEqual(ev["data"]["record"]["evidence_id"], evidence_id)

    def test_run_level_authorization_and_refusals(self):
        allowed = self.runs["config-cause"]
        self.assertEqual(self.get(f"/v1/runs/{allowed}/result", "one")[0], 200)
        for variant, run_id in self.runs.items():
            if run_id != allowed:
                with self.subTest(variant=variant):
                    self.assertEqual(self.get(f"/v1/runs/{run_id}/result", "one"),
                                     (403, {"error": "run_not_authorized"}))
        self.assertEqual(self.get(f"/v1/runs/{allowed}/result", None)[0], 401)
        self.assertEqual(self.get(f"/v1/runs/{self.unknown}/result"), (404, {"error": "run_not_found"}))
        self.assertEqual(self.get(f"/v1/runs/{allowed}/result", method="POST")[0], 405)
        # Evidence of another run (a symptom only "symptom-before-change" has) is not served via this run.
        early = self.stored["symptom-before-change"].result["timeline"]["entries"]
        mine = {e["evidence_id"] for e in self.stored["config-cause"].result["timeline"]["entries"]}
        foreign = next(e["evidence_id"] for e in early if e["evidence_id"] not in mine)
        self.assertEqual(self.get(f"/v1/runs/{allowed}/evidence/{foreign.split(':')[1]}"),
                         (404, {"error": "evidence_not_found"}))

    def rewrite_stored(self, key, mutate):
        """Self-consistently rewrite a stored result (digest and SHA-256 recomputed), bypassing triggers."""
        doc = canonical.loads(self.stored[key].result_bytes)
        body = {k: v for k, v in doc.items() if k != "result_digest"}
        mutate(body)
        body["result_digest"] = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
        raw = canonical.canonical_bytes(body)
        admin = _db.superuser(self.fx.name)
        try:
            with admin.transaction():
                admin.run("SET LOCAL session_replication_role = replica")
                admin.run("UPDATE ca.investigation_result SET result_bytes = :b, result_bytes_sha256 = :h, "
                          "result_digest = :d WHERE run_id = CAST(:r AS uuid)", b=raw,
                          h=hashlib.sha256(raw).hexdigest(), d=body["result_digest"], r=self.runs[key])
        finally:
            admin.close()

    def test_malformed_stored_results_get_a_stable_409_without_data(self):  # PR #24 review H2
        cases = (("to-malform", lambda b: b.update(rule_versions=[])),
                 ("to-misshape", lambda b: b["outcome"].update(reasons=None)))
        for key, mutate in cases:
            with self.subTest(case=key):
                run_id = self.runs[key]
                self.assertEqual(self.get(f"/v1/runs/{run_id}/result")[0], 200)
                self.rewrite_stored(key, mutate)
                for route in ("result", "timeline", "hypotheses", "citations"):
                    status, body = self.get(f"/v1/runs/{run_id}/{route}")
                    self.assertEqual((status, body), (409, {"error": "result_unverifiable",
                                                            "reason": "result_malformed"}))
                self.assertEqual(self.get("/healthz", None)[0], 200)  # the server keeps serving

    def test_concurrent_requests_are_bounded_by_open_database_connections(self):  # PR #24 review H1
        entered, release = threading.Semaphore(0), threading.Event()

        def gated_connect():
            db = self.connect()
            entered.release()
            release.wait(30)
            return db

        gated = server.build(self.grants_path, gated_connect, quiet=True)
        threading.Thread(target=gated.serve_forever, daemon=True).start()
        admin = _db.superuser(self.fx.name)
        try:
            for path, token, slots in ((f"/v1/runs/{self.runs['config-cause']}/result", "all", 4),
                                       ("/readyz", None, 1)):
                with self.subTest(path=path):
                    statuses, threads = [], []
                    for _ in range(12):
                        threads.append(threading.Thread(
                            target=lambda: statuses.append(self.get(path, token, port=gated.port))))
                        threads[-1].start()
                    for _ in range(slots):
                        self.assertTrue(entered.acquire(timeout=30))
                    open_now = admin.one("SELECT count(*) FROM pg_stat_activity WHERE datname = :d "
                                         "AND application_name = 'cloud-autopsy-api'", d=self.fx.name)[0]
                    self.assertEqual(open_now, slots)
                    for _ in range(300):  # the refused requests are answered without waiting for a slot
                        if len(statuses) >= 12 - slots:
                            break
                        time.sleep(0.05)
                    overloaded = [b for st, b in statuses if st == 503]
                    self.assertEqual(overloaded, [{"error": "overloaded"}] * (12 - slots))
                    release.set()
                    for t in threads:
                        t.join(30)
                    release.clear()
                    admitted = [b for st, b in statuses if st == 200]
                    self.assertEqual(len(admitted), slots)
                    if token:
                        self.assertTrue(all(b["verified"] and b["result_digest"] ==
                                            self.stored["config-cause"].result["result_digest"] for b in admitted))
        finally:
            release.set()
            admin.close()
            gated.shutdown()
            gated.server_close()

    @unittest.skipUnless(BROWSER_OK, "no Chromium-family browser installed (set CA_BROWSER)")
    def test_dashboard_shows_database_verified_results_and_refuses_tampering(self):  # CA-P2-006c
        b = _cdp.Browser(1440, 900)
        try:
            b.navigate(f"http://127.0.0.1:{self.server.port}/")
            runs = [self.runs["config-cause"], self.runs["configmap-unavailable"], self.runs["to-tamper"]]
            b.js(f"document.querySelector('#token').value = {json.dumps(self.tokens['all'])};"
                 f"document.querySelector('#run-ids').value = {json.dumps(chr(10).join(runs))};"
                 "document.querySelector('#connect-form').requestSubmit(); 1")
            b.wait_for("document.querySelector('#app').dataset.state === 'ready' && document.querySelector('#connect').hidden", 30)
            self.assertEqual(b.js("document.querySelector('#mode-chip').textContent"), "Verified on read")
            self.assertEqual(b.js("document.querySelector('.outcome-word').textContent"), "Resolved")
            self.assertEqual(b.js("document.querySelector('.verify-title').textContent"), "Byte-identical replay")
            b.js("document.querySelector('[data-view=evidence]').click(); 1")
            b.wait_for("document.querySelectorAll('.ev-row').length > 0")
            b.js("document.querySelector('.ev-row').click(); 1")
            b.wait_for("document.querySelector('.insp-body .badges')", 30)
            self.assertIn("Served after verification", b.js("document.querySelector('.insp-body .badges').textContent"))
            b.js("document.querySelector('[data-view=overview]').click(); document.querySelector('#run-pill').click(); 1")
            b.wait_for("document.querySelectorAll('.run-item').length === 3")
            b.js("document.querySelectorAll('.run-item')[1].click(); 1")
            b.wait_for("document.querySelector('.outcome-word')?.textContent === 'Abstained'", 30)
            self.assertEqual(b.js("document.querySelector('#mode-chip').textContent"), "Verified on read")
            self.assertEqual(b.console_errors(), [])
        finally:
            b.close()

    def test_tampered_result_is_never_served(self):
        run_id = self.runs["to-tamper"]
        self.assertEqual(self.get(f"/v1/runs/{run_id}/result")[0], 200)  # verified before tampering
        doc = canonical.loads(self.stored["to-tamper"].result_bytes)
        body = {k: v for k, v in doc.items() if k != "result_digest"}
        body["outcome"]["reasons"] = sorted(set(body["outcome"]["reasons"]) | {"forged"})
        body["result_digest"] = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
        forged = canonical.canonical_bytes(body)
        admin = _db.superuser(self.fx.name)
        try:
            with admin.transaction():
                admin.run("SET LOCAL session_replication_role = replica")
                admin.run("UPDATE ca.investigation_result SET result_bytes = :b, result_bytes_sha256 = :h, "
                          "result_digest = :d WHERE run_id = CAST(:r AS uuid)", b=forged,
                          h=hashlib.sha256(forged).hexdigest(), d=body["result_digest"], r=run_id)
        finally:
            admin.close()
        for route in ("result", "timeline", "hypotheses", "citations"):
            with self.subTest(route=route):
                self.assertEqual(self.get(f"/v1/runs/{run_id}/{route}"),
                                 (409, {"error": "result_unverifiable", "reason": "replay_mismatch"}))
        evidence_hex = self.stored["to-tamper"].result["outcome"]["evidence_ids"][0].split(":")[1]
        self.assertEqual(self.get(f"/v1/runs/{run_id}/evidence/{evidence_hex}")[0], 409)


if __name__ == "__main__":
    unittest.main()
