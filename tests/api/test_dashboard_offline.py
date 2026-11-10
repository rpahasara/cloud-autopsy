"""CA-P2-006c dashboard: offline checks of the served assets, headers and the labelled preview.

No database and no browser: the asset table, the page CSP, the static safety properties of the
dashboard source, the preview envelope, and that the existing API behaviour is unchanged.
"""

import http.client
import json
import re
import shutil
import threading
import unittest

import _api_support as A
from cloud_autopsy.api import service as svc
from cloud_autopsy.api import ui
from cloud_autopsy.api.transport import LoopbackServer
from cloud_autopsy.app import preview
from test_api_offline import _Headers, call

UI_FILES = sorted(p for p in ui.UI_DIR.iterdir() if p.is_file())
SCRIPTS = [p for p in UI_FILES if p.suffix == ".js"]


def get(port, path, token=None, method="GET"):
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    con.request(method, path, headers={"Authorization": f"Bearer {token}"} if token else {})
    r = con.getresponse()
    body = r.read()
    con.close()
    return r.status, dict(r.getheaders()), body


class AssetRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service, cls.tokens, _ = A.service()
        service.ui = ui.load_assets()
        cls.server = LoopbackServer(service, quiet=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_every_asset_is_served_with_its_type_and_the_page_policy(self):
        types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
        for path, name in ui.ASSETS.items():
            with self.subTest(path=path):
                status, headers, body = get(self.server.port, path)
                self.assertEqual(status, 200)
                self.assertEqual(body, (ui.UI_DIR / name).read_bytes())
                self.assertEqual(headers["Content-Type"], types[(ui.UI_DIR / name).suffix])
                self.assertEqual(headers["Content-Security-Policy"], ui.UI_CSP)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Frame-Options"], "DENY")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_page_policy_is_same_origin_only_with_trusted_types(self):
        for directive in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
                          "img-src 'self'", "frame-ancestors 'none'", "form-action 'none'", "base-uri 'none'",
                          "require-trusted-types-for 'script'", "trusted-types 'none'"):
            self.assertIn(directive, ui.UI_CSP)
        self.assertNotIn("unsafe", ui.UI_CSP)
        self.assertNotIn("http", ui.UI_CSP)

    def test_the_asset_table_is_fixed(self):
        for path in ("/ui/", "/ui/missing.js", "/ui/../grants.json", "/ui/app.js.map", "/index.html", "/ui/APP.JS",
                     "/ui//app.js", "/favicon.ico"):
            with self.subTest(path=path):
                self.assertIn(get(self.server.port, path)[0], (400, 404))
        status, headers, _ = get(self.server.port, "/", method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(get(self.server.port, "/ui/app.js?x=1")[0], 400)

    def test_api_routes_and_json_policy_are_unchanged(self):
        status, headers, body = get(self.server.port, f"/v1/runs/{A.RUNS['config-cause']}/result", self.tokens["all"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Security-Policy"], "default-src 'none'")
        doc = json.loads(body)
        self.assertIs(doc["verified"], True)
        self.assertNotIn("data_source", doc)
        self.assertEqual(get(self.server.port, f"/v1/runs/{A.RUNS['config-cause']}/result")[0], 401)

    def test_access_log_names_asset_paths_from_the_fixed_table_only(self):
        service = self.server.service
        self.assertEqual(service.route_template("GET", "/"), ("GET", "/"))
        self.assertEqual(service.route_template("GET", "/ui/app.js"), ("GET", "/ui/app.js"))
        self.assertEqual(service.route_template("GET", "/ui/secret-guess.js"), ("GET", "<rejected>"))


class WithoutDashboardTests(unittest.TestCase):
    def test_a_service_without_assets_serves_no_page(self):
        service, _, _ = A.service()
        self.assertEqual(call(service, "/"), (404, {"error": "route_not_found"}))
        self.assertEqual(call(service, "/ui/app.js"), (404, {"error": "route_not_found"}))


class SourceSafetyTests(unittest.TestCase):
    """Static properties of the dashboard source that the browser tests exercise dynamically."""

    def text(self, path):
        return path.read_text(encoding="utf-8")

    def test_assets_are_ascii_only(self):
        for path in UI_FILES:
            with self.subTest(file=path.name):
                path.read_bytes().decode("ascii")

    def test_no_html_string_sinks_or_dynamic_code(self):
        banned = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                  "setAttribute(\"on", "srcdoc", "javascript:", "DOMParser", "createContextualFragment")
        for path in SCRIPTS:
            text = self.text(path)
            for needle in banned:
                with self.subTest(file=path.name, needle=needle):
                    self.assertNotIn(needle, text)

    def test_no_browser_storage_cookies_or_url_state(self):
        for path in SCRIPTS:
            text = self.text(path)
            for needle in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "caches.", "history.",
                           "location.hash", "location.search", "URLSearchParams", "postMessage", "BroadcastChannel"):
                with self.subTest(file=path.name, needle=needle):
                    self.assertNotIn(needle, text)

    def test_only_same_origin_requests(self):
        for path in UI_FILES:
            urls = set(re.findall(r"(?:https?:)?//[A-Za-z0-9.-]+", self.text(path)))
            with self.subTest(file=path.name):
                self.assertLessEqual(urls, {"http://www.w3.org"})
        app = self.text(ui.UI_DIR / "app.js")
        self.assertEqual(app.count("fetch("), 1)
        self.assertIn('credentials: "omit"', app)
        self.assertIn('mode: "same-origin"', app)
        self.assertIn("Authorization: `Bearer ${token}`", app)
        for request in re.findall(r"api\(`([^`]*)`\)", app):
            with self.subTest(request=request):
                self.assertTrue(request.startswith("/v1/runs/"))
                self.assertNotIn("token", request)

    def test_no_inline_script_style_or_event_handlers_in_the_page(self):
        page = self.text(ui.UI_DIR / "index.html")
        self.assertNotRegex(page, r"<script(?![^>]*\bsrc=)")
        self.assertNotIn("<style", page)
        self.assertNotRegex(page, r"\sstyle=")
        self.assertNotRegex(page, r"\son[a-z]+=")
        for ref in re.findall(r'(?:src|href)="([^"]+)"', page):
            with self.subTest(ref=ref):
                self.assertIn(ref, ui.ASSETS)

    def test_every_module_import_is_a_served_asset(self):
        for path in SCRIPTS:
            for target in re.findall(r'from "\./([a-z]+\.js)"', self.text(path)):
                with self.subTest(file=path.name, target=target):
                    self.assertIn(f"/ui/{target}", ui.ASSETS)


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.token, cls.secret_dir = preview.start(quiet=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.secret_dir, ignore_errors=True)

    def test_preview_is_loopback_and_labelled_not_verified(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for variant, run_id in preview.RUNS.items():
            with self.subTest(variant=variant):
                status, _, body = get(self.server.port, f"/v1/runs/{run_id}/result", self.token)
                doc = json.loads(body)
                self.assertEqual(status, 200)
                self.assertIs(doc["verified"], False)
                self.assertEqual(doc["data_source"], "synthetic-preview")
                self.assertIn("not read from or verified against", doc["verification"])

    def test_preview_keeps_authentication_and_run_grants(self):
        run_id = preview.RUNS["config-cause"]
        self.assertEqual(get(self.server.port, f"/v1/runs/{run_id}/result")[0], 401)
        self.assertEqual(get(self.server.port, f"/v1/runs/{run_id}/result", "x" * 43)[0], 401)
        self.assertEqual(get(self.server.port, f"/v1/runs/{A.UNKNOWN}/result", self.token)[0], 403)
        self.assertEqual(get(self.server.port, f"/v1/runs/{run_id}/result", self.token, "POST")[0], 405)

    def test_preview_secrets_live_outside_the_repository(self):
        self.assertFalse(str(self.secret_dir.resolve()).startswith(str(A.REPO.resolve())))
        self.assertEqual((self.secret_dir / "preview.token").read_text(encoding="ascii"), self.token)
        self.assertNotIn(self.token, (self.secret_dir / "grants.json").read_text(encoding="utf-8"))

    def test_preview_results_match_the_engine(self):
        for variant, run_id in preview.RUNS.items():
            with self.subTest(variant=variant):
                _, _, body = get(self.server.port, f"/v1/runs/{run_id}/result", self.token)
                self.assertEqual(json.loads(body)["result_digest"], A.verified(variant).result_digest)


class PreviewEnvelopeTests(unittest.TestCase):
    def test_preview_flag_only_relabels_the_envelope(self):
        grants_path, tokens = A.provision({"a": [A.RUNS["config-cause"]]})
        backend = A.FakeBackend()
        real = svc.ApiService(A.G.load(grants_path), backend.load_verified, backend.check_ready)
        fake = svc.ApiService(A.G.load(grants_path), backend.load_verified, backend.check_ready, preview=True)
        path = f"/v1/runs/{A.RUNS['config-cause']}/hypotheses"
        r = json.loads(real.handle("GET", path, _Headers({"Authorization": f"Bearer {tokens['a']}"})).body)
        p = json.loads(fake.handle("GET", path, _Headers({"Authorization": f"Bearer {tokens['a']}"})).body)
        self.assertEqual(r["data"], p["data"])
        self.assertEqual((r["verified"], p["verified"]), (True, False))
        self.assertEqual(p["data_source"], "synthetic-preview")


if __name__ == "__main__":
    unittest.main()
