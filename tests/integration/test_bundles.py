"""CA-P2-004a: creating investigations from evidence bundles against a real disposable PostgreSQL.

- Every example bundle is created through the least-privileged roles. Each stored result is
  re-verified on read, and must equal the offline result and the result of the existing fixture
  pipeline.
- A failure part-way leaves no successful-looking run: no stored result, nothing served, no grant.
- A created run opens in the existing Home and Investigation dashboards through a private grant.
Synthetic data only.
"""

import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import _db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser"))
import _cdp  # noqa: E402  (standard-library CDP client, test-only)

BROWSER_OK = bool(_cdp.find_browser()) or os.environ.get("CA_BROWSER_REQUIRE") == "1"
EXAMPLES = _db.REPO / "examples" / "bundles"

if _db.AVAILABLE:
    from cloud_autopsy.api import server
    from cloud_autopsy.app import bundle as B
    from cloud_autopsy.app import create as C
    from cloud_autopsy.app import create_cli, pipeline
    from cloud_autopsy.db import results
    from cloud_autopsy.synthetic import scenario_001 as scenario

ROLES = ("ca_planner", "ca_ingest", "ca_sealer", "ca_engine", "ca_result_writer")


class Boom:
    """Stands in for a role connection that fails on first use (a dropped connection, say)."""

    def __getattr__(self, name):
        raise RuntimeError("simulated connection failure")


class FixtureDatabase:
    """The shape ``create_cli`` expects from a ``DisposableDatabase``, over a test fixture."""

    def __init__(self, fx):
        endpoint = _db.endpoint(fx.name)
        self.fx, self.host, self.port, self.name, self.passwords = fx, endpoint.host, endpoint.port, fx.name, fx.passwords
        self.roles = {r: fx.connect(r) for r in ROLES}

    def connect(self, role):
        return self.fx.connect(role)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class BundleCreationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        cls.db = FixtureDatabase(cls.fx)
        cls.tmp = Path(tempfile.mkdtemp(prefix="ca-bundles-it-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.fx.close()

    def state(self, run_id):
        admin = _db.superuser(self.fx.name)
        try:
            return admin.one("SELECT state FROM ca.run WHERE run_id = CAST(:r AS uuid)", r=run_id)[0]
        finally:
            admin.close()

    def test_every_example_bundle_is_created_verified_and_equal_to_offline_and_the_fixture_pipeline(self):
        for variant in scenario.VARIANTS:
            with self.subTest(variant=variant):
                loaded = B.load(EXAMPLES / variant)
                fresh = self.fx.connect("ca_engine")
                inv = C.create_in_database(self.db.roles, loaded, verify_db=fresh)
                self.assertIsInstance(inv, C.DatabaseInvestigation)
                self.assertIs(inv.verified, True)
                self.assertEqual(self.state(inv.run_id), "sealed")
                offline = C.investigate_offline(loaded)
                self.assertEqual(inv.result_bytes, offline.result_bytes)
                # the same records through the existing fixture pipeline give the same stored bytes
                run_id, _, _ = pipeline.persist_and_seal(self.db.roles, variant)
                _, investigation = pipeline.record_result(self.db.roles["ca_engine"], self.db.roles["ca_result_writer"], run_id)
                self.assertEqual(investigation.result_bytes, inv.result_bytes)
                # and the verify-on-read loader, as the API uses it, returns exactly these bytes
                again = pipeline.replay_stored(fresh, inv.run_id)
                self.assertEqual((again.result_digest, again.result_bytes), (inv.result_digest, inv.result_bytes))

    def test_failure_part_way_never_looks_successful(self):
        loaded = B.load(EXAMPLES / "no-symptom")
        for failing, stage, expected_state in (("ca_sealer", "seal", "collecting"),
                                               ("ca_result_writer", "record_result", "sealed")):
            with self.subTest(failing=failing):
                roles = dict(self.db.roles, **{failing: Boom()})
                with self.assertRaises(C.CreationFailed) as ctx:
                    C.create_in_database(roles, loaded)
                failed = ctx.exception
                self.assertEqual(failed.stage, stage)
                self.assertIsNotNone(failed.run_id)
                self.assertEqual(self.state(failed.run_id), expected_state)
                with self.assertRaises(results.StoredResultUnavailable):
                    results.load_verified_result(self.fx.connect("ca_engine"), failed.run_id)
        with self.assertRaises(TypeError):
            C.issue_private_grant([failed])  # nothing to grant: only DatabaseInvestigation objects are accepted

    def test_cli_creates_reports_refusals_and_failures(self):
        bad = self.tmp / "bad"
        shutil.copytree(EXAMPLES / "config-cause", bad)
        (bad / "ground-truth.json").write_bytes(b"{}")
        out = io.StringIO()
        with redirect_stdout(out):
            code = create_cli.main([str(EXAMPLES / "config-cause"), str(bad), "--json"], database_factory=lambda: self.db)
        rows = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual([r["status"] for r in rows], ["ok", "refused"])
        self.assertEqual((rows[0]["verified"], rows[1]["code"]), (True, "bundle_unexpected_entry"))
        self.assertIn("database-verified", rows[0]["label"])
        self.assertEqual(self.state(rows[0]["run_id"]), "sealed")

        class Broken(FixtureDatabase):
            def __init__(self, base):
                self.__dict__.update(base.__dict__)
                self.roles = dict(base.roles, ca_sealer=Boom())

        out = io.StringIO()
        with redirect_stdout(out):
            code = create_cli.main([str(EXAMPLES / "config-cause"), "--serve", "--json"],
                                   database_factory=lambda: Broken(self.db))
        row = json.loads(out.getvalue())[0]
        self.assertEqual(code, 1)  # and no server was started: --serve needs every bundle created
        self.assertEqual((row["status"], row["stage"], row["reason"]), ("failed", "seal", "RuntimeError"))

    def get(self, port, path, token):
        con = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        con.request("GET", path, headers={"Authorization": f"Bearer {token}"})
        response = con.getresponse()
        body = json.loads(response.read())
        con.close()
        return response.status, body

    @unittest.skipUnless(BROWSER_OK, "no Chromium-family browser installed (set CA_BROWSER)")
    def test_a_created_run_opens_in_the_existing_dashboards(self):
        loaded = B.load(EXAMPLES / "config-cause")
        inv = C.create_in_database(self.db.roles, loaded, verify_db=self.fx.connect("ca_engine"))
        holder = {}
        create_cli.serve(self.db, [inv], self.tmp / "grant", 0, ready=lambda api, files: holder.update(api=api, files=files))
        api, files = holder["api"], holder["files"]
        threading.Thread(target=api.serve_forever, daemon=True).start()
        token = files.token_path.read_text(encoding="ascii")
        try:
            status, body = self.get(api.port, "/v1/summaries/1", token)
            self.assertEqual(status, 200)
            self.assertEqual([(i["run_id"], i["state"]) for i in body["items"]], [(inv.run_id, "verified")])
            status, body = self.get(api.port, f"/v1/runs/{inv.run_id}/result", token)
            self.assertEqual((status, body["verified"], body["result_digest"]), (200, True, inv.result_digest))
            b = _cdp.Browser(1440, 900)
            try:
                b.navigate(f"http://127.0.0.1:{api.port}/")
                b.js(f"document.querySelector('#token').value = {json.dumps(token)};"
                     "document.querySelector('#connect-form').requestSubmit(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'home' && "
                           "document.querySelector('.h-granted .m-value')?.textContent === '1'", 30)
                b.wait_for("document.querySelector('#mode-chip').textContent === 'Verified on read'", 30)
                self.assertEqual(b.js("document.querySelector('.h-resolved .m-value').textContent"), "1")
                b.js("document.querySelector('[data-view=investigations]').click(); 1")
                b.wait_for(f"document.querySelector('.inv-row[data-run=\"{inv.run_id}\"] .inv-ver')?.textContent === 'Verified'", 30)
                b.js(f"document.querySelector('.inv-row[data-run=\"{inv.run_id}\"]').click(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'run' && "
                           "document.querySelector('#run-title').textContent === 'ca-scenario-001-config-cause' && "
                           "document.querySelector('.verify-title')?.textContent === 'Byte-identical replay'", 30)
                self.assertEqual(b.js("document.querySelector('#mode-chip').textContent"), "Verified on read")
                self.assertEqual(b.console_errors(), [])
            finally:
                b.close()
        finally:
            api.shutdown()
            api.server_close()


if __name__ == "__main__":
    unittest.main()
