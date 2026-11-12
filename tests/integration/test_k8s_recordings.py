"""CA-P2-004c end to end against a real disposable PostgreSQL: recorded Kubernetes responses ->
converted bundles -> database-verified investigations -> the existing dashboard. Synthetic only.
"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import _db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser"))
import _cdp  # noqa: E402

BROWSER_OK = bool(_cdp.find_browser()) or os.environ.get("CA_BROWSER_REQUIRE") == "1"
RECORDINGS = _db.REPO / "examples" / "k8s-recordings"

if _db.AVAILABLE:
    from cloud_autopsy.app import bundle as B
    from cloud_autopsy.app import create as C
    from cloud_autopsy.app import create_cli
    from cloud_autopsy.app import k8s_recording as K
    from test_bundles import FixtureDatabase


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class RecordedKubernetesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        cls.db = FixtureDatabase(cls.fx)
        cls.tmp = Path(tempfile.mkdtemp(prefix="ca-k8s-it-"))
        cls.created = {}
        for name in ("rollout-complete", "degraded", "events-only"):
            conversion = K.convert(RECORDINGS / name)
            out = cls.tmp / name
            conversion.write_bundle(out)
            loaded = B.load(out)
            cls.created[name] = (conversion, loaded, C.create_in_database(cls.db.roles, loaded,
                                                                          verify_db=cls.fx.connect("ca_engine")))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.fx.close()

    def test_converted_bundles_are_database_verified_and_equal_offline(self):
        for name, (conversion, loaded, inv) in self.created.items():
            with self.subTest(recording=name):
                self.assertIs(inv.verified, True)
                self.assertEqual(inv.result_bytes, C.investigate_offline(loaded).result_bytes)
                result = json.loads(inv.result_bytes)
                self.assertEqual(result["outcome"]["status"], "abstained")
                self.assertEqual(result["inputs"]["plan_id"], conversion.report["recording_id"])

    def get(self, port, path, token):
        con = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        con.request("GET", path, headers={"Authorization": f"Bearer {token}"})
        response = con.getresponse()
        body = json.loads(response.read())
        con.close()
        return response.status, body

    @unittest.skipUnless(BROWSER_OK, "no Chromium-family browser installed (set CA_BROWSER)")
    def test_converted_runs_open_in_the_existing_dashboard(self):
        invs = [inv for _, _, inv in self.created.values()]
        holder = {}
        create_cli.serve(self.db, invs, self.tmp / "grant", 0, ready=lambda api, files: holder.update(api=api, files=files))
        api, files = holder["api"], holder["files"]
        threading.Thread(target=api.serve_forever, daemon=True).start()
        token = files.token_path.read_text(encoding="ascii")
        rollout = self.created["rollout-complete"][2]
        try:
            status, body = self.get(api.port, f"/v1/runs/{rollout.run_id}/timeline", token)
            self.assertEqual(status, 200)
            names = {e["entity"]["name"] for e in body["data"]["entries"]}
            self.assertIn("checkout-api", names)                  # the rollout
            self.assertIn("checkout-api-7c9f8-b1", names)         # a pod
            self.assertNotIn("debug-shell", names)                # out of scope: counted, not evidence
            b = _cdp.Browser(1440, 900)
            try:
                b.navigate(f"http://127.0.0.1:{api.port}/")
                b.js(f"document.querySelector('#token').value = {json.dumps(token)};"
                     "document.querySelector('#connect-form').requestSubmit(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'home' && "
                           "document.querySelector('.h-granted .m-value')?.textContent === '3'", 30)
                b.wait_for("document.querySelector('#mode-chip').textContent === 'Verified on read'", 30)
                self.assertEqual(b.js("document.querySelector('.h-resolved .m-value').textContent"), "0")
                b.js("document.querySelector('[data-view=investigations]').click(); 1")
                b.wait_for(f"document.querySelector('.inv-row[data-run=\"{rollout.run_id}\"] .inv-ver')?.textContent === 'Verified'", 30)
                b.js(f"document.querySelector('.inv-row[data-run=\"{rollout.run_id}\"]').click(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'run' && "
                           "document.querySelector('#run-title').textContent === 'ca-k8s-rec-rollout-complete' && "
                           "document.querySelector('.verify-title')?.textContent === 'Byte-identical replay'", 30)
                self.assertEqual(b.console_errors(), [])
            finally:
                b.close()
        finally:
            api.shutdown()
            api.server_close()


if __name__ == "__main__":
    unittest.main()
