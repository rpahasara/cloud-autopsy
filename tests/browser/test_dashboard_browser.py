"""CA-P2-006c dashboard in a real headless browser (Chrome/Chromium/Edge over CDP, 127.0.0.1 only).

The page is served by the real ``ApiService`` with the dashboard assets and the labelled
synthetic preview backend (no database). One extra run carries a hostile log message to prove
that untrusted evidence text is rendered as text. Skipped when no browser is installed, unless
``CA_BROWSER_REQUIRE=1`` (CI), where a missing browser fails the run.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import _cdp  # noqa: E402
from cloud_autopsy.api import grants as G  # noqa: E402
from cloud_autopsy.api import ui  # noqa: E402
from cloud_autopsy.api.service import ApiService  # noqa: E402
from cloud_autopsy.api.transport import LoopbackServer  # noqa: E402
from cloud_autopsy.app import preview  # noqa: E402

BROWSER = _cdp.find_browser()
REQUIRED = os.environ.get("CA_BROWSER_REQUIRE") == "1"
HOSTILE = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>&lt;b&gt;bold'
HOSTILE_RUN = str(uuid.uuid5(uuid.NAMESPACE_URL, "ca-dashboard-browser/hostile"))
UNGRANTED_RUN = str(uuid.uuid5(uuid.NAMESPACE_URL, "ca-dashboard-browser/ungranted"))
CSP_RECORDER = ("window.__csp = []; document.addEventListener('securitypolicyviolation', "
                "e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")
SETTLED = ("[...document.querySelectorAll('.card, .inspector, .layer')].every(e => e.getAnimations().length === 0)"
           " && !document.querySelector('.card.is-lifted, .card.is-morphing')")


def serve():
    load, ready = preview.backend()
    base = load(preview.RUNS["config-cause"])
    evidence = deepcopy(base.evidence)
    target = next(k for k, v in sorted(evidence.items()) if isinstance(v["record"]["attributes"].get("message"), str))
    evidence[target]["record"]["attributes"]["message"] = HOSTILE
    hostile = SimpleNamespace(result_digest=base.result_digest, result=base.result, evidence=evidence)

    def load_with_hostile(run_id):
        return hostile if run_id == HOSTILE_RUN else load(run_id)

    secret_dir = Path(tempfile.mkdtemp(prefix="ca-dashboard-browser-"))
    record, tokens = G.issue({"viewer": list(preview.RUNS.values()) + [HOSTILE_RUN]})
    G.write_private(secret_dir / "grants.json", json.dumps(record).encode("utf-8"))
    service = ApiService(G.load(secret_dir / "grants.json"), load_with_hostile, ready, ui=ui.load_assets(), preview=True)
    server = LoopbackServer(service, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, tokens["viewer"], secret_dir, target


@unittest.skipUnless(BROWSER or REQUIRED, "no Chromium-family browser installed (set CA_BROWSER)")
class DashboardBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.token, cls.secret_dir, cls.hostile_id = serve()
        cls.url = f"http://127.0.0.1:{cls.server.port}/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.secret_dir, ignore_errors=True)

    def setUp(self):
        self.b = _cdp.Browser(1440, 900)
        self.b.call("Page.addScriptToEvaluateOnNewDocument", source=CSP_RECORDER)
        self.b.navigate(self.url)

    def tearDown(self):
        try:
            self.assertEqual(self.b.js("window.__csp"), [], "CSP violations")
            self.assertEqual(self.b.console_errors(), [], "console errors")
            self.assertIsNone(self.b.js("window.__pwned ?? null"))
        finally:
            self.b.close()

    # ---- helpers

    def connect(self, runs, token=None):
        b = self.b
        b.js(f"document.querySelector('#token').value = {json.dumps(token or self.token)};"
             f"document.querySelector('#run-ids').value = {json.dumps(chr(10).join(runs))}; 1")
        self.click("#connect-form button[type=submit]")
        b.wait_for("document.querySelector('#app').dataset.state === 'ready' || "
                   "(!document.querySelector('#connect').hidden && document.querySelector('#connect-error').textContent)")
        if b.js("document.querySelector('#app').dataset.state === 'ready'"):
            b.wait_for("document.querySelector('#connect').hidden")  # the sheet has faded out
        b.wait_for(SETTLED)

    def click(self, selector):
        rect = self.b.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); e.scrollIntoView({{block: 'center'}});"
                         "const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + Math.min(r.height / 2, 40)]; })()")
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.b.call("Input.dispatchMouseEvent", type=kind, x=rect[0], y=rect[1], button="left", clickCount=1)

    def key(self, name, code):
        for kind in ("keyDown", "keyUp"):
            self.b.call("Input.dispatchKeyEvent", type=kind, key=name, code=name, windowsVirtualKeyCode=code)

    def text(self, selector):
        return self.b.js(f"document.querySelector({json.dumps(selector)})?.textContent ?? null")

    def visible(self, selector):
        return self.b.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return false;"
                         "const s = getComputedStyle(e); return s.visibility === 'visible' && Number(s.opacity) > 0.99; })()")

    # ---- workflows

    def test_sign_in_validates_and_keeps_the_token_out_of_storage_and_urls(self):
        b = self.b
        self.assertTrue(b.js("document.querySelector('.main').inert"))
        self.connect([preview.RUNS["config-cause"]], token="short")
        self.assertIn("does not look like an API token", self.text("#connect-error"))
        self.connect([preview.RUNS["config-cause"]], token="A" * 43)  # well-formed, not issued
        b.wait_for("document.querySelector('#connect-error').textContent.includes('cleared')")
        self.assertEqual(b.js("document.querySelector('#token').value"), "")
        self.connect(list(preview.RUNS.values()))
        self.assertEqual(b.js("document.querySelector('#app').dataset.state"), "ready")
        self.assertEqual(b.js("[localStorage.length, sessionStorage.length, document.cookie]"), [0, 0, ""])
        self.assertNotIn(self.token, b.js("location.href"))
        self.assertNotIn(self.token, b.js("document.documentElement.outerHTML"))
        self.assertEqual(b.js("document.querySelector('#token').value"), "")
        self.assertFalse(b.js("document.querySelector('.main').inert"))

    def test_overview_shows_the_preview_label_and_never_a_verified_badge(self):
        self.connect(list(preview.RUNS.values()))
        self.assertEqual(self.text("#run-title"), "ca-scenario-001-config-cause")
        self.assertIn("not verified", self.text("#mode-chip"))
        self.assertEqual(self.text(".outcome-word"), "Resolved")
        self.assertTrue(self.b.js("document.querySelector('.card-outcome').classList.contains('is-sage')"))
        self.assertEqual(self.text(".card-outcome .chip"), "Synthetic preview")
        self.assertEqual(self.text(".verify-title"), "Preview only")
        self.assertEqual(self.b.js("document.querySelectorAll('.marker').length"), 5)

    def test_hero_expands_into_the_investigation_and_reverses(self):
        b = self.b
        self.connect(list(preview.RUNS.values()))
        before = b.js("(() => { const r = document.querySelector('.card-hero').getBoundingClientRect(); return [r.width, r.height]; })()")
        self.click(".card-hero .hero-label")
        b.wait_for("document.querySelector('.card-hero').getAnimations().length > 0")  # a real layout animation runs
        b.wait_for(SETTLED)
        after = b.js("(() => { const r = document.querySelector('.card-hero').getBoundingClientRect(); return [r.width, r.height]; })()")
        self.assertGreater(after[0], before[0] * 1.4)
        self.assertGreater(after[1], before[1] * 1.4)
        self.assertEqual(b.js("document.querySelector('#stage').dataset.focus"), "hero")
        self.assertTrue(self.visible(".inspector"))
        self.assertFalse(self.visible(".card-outcome"))
        self.assertEqual(self.text("#nav .is-on"), "Investigation")
        self.assertEqual(self.text(".insp-title"), "Config limit reduction")
        self.key("Escape", 27)
        b.wait_for(SETTLED)
        self.assertIsNone(b.js("document.querySelector('#stage').dataset.focus ?? null"))
        self.assertTrue(self.visible(".card-outcome"))
        self.assertFalse(self.visible(".inspector"))
        restored = b.js("(() => { const r = document.querySelector('.card-hero').getBoundingClientRect(); return [r.width, r.height]; })()")
        self.assertAlmostEqual(restored[0], before[0], delta=1)
        self.assertAlmostEqual(restored[1], before[1], delta=1)

    def test_interrupted_transitions_settle_in_a_consistent_layout(self):
        b = self.b
        self.connect(list(preview.RUNS.values()))
        b.js("document.querySelector('.card-hero').click(); document.querySelector('[data-view=timeline]').click();"
             "document.querySelector('[data-view=overview]').click(); document.querySelector('[data-view=hypotheses]').click(); 1")
        b.wait_for(SETTLED)
        self.assertEqual(b.js("document.querySelector('#stage').dataset.focus"), "hyps")
        self.assertEqual(b.js("[...document.querySelectorAll('.card[data-focused]')].map(c => c.dataset.card)"), ["hyps"])
        self.assertTrue(self.visible(".card-hyps"))
        self.assertTrue(self.visible(".inspector"))
        self.assertEqual(b.js("[...document.querySelectorAll('.layer')].filter(l => l.style.width).length"), 0)

    def test_timeline_selection_opens_the_evidence_inspector(self):
        b = self.b
        self.connect(list(preview.RUNS.values()))
        self.click('[data-view="timeline"]')
        b.wait_for(SETTLED)
        self.assertGreater(b.js("document.querySelectorAll('.card-timeline .layer-expanded button.tick').length"), 5)
        self.click(".card-timeline .layer-expanded button.tick.is-change")
        b.wait_for("document.querySelector('.insp-body .eyebrow')?.textContent.startsWith('K8S-CONFIG')")
        self.assertEqual(self.text(".insp-title"), "checkout-db-pool")
        self.assertTrue(b.js("document.querySelector('.card-timeline .layer-expanded .tick.is-selected') !== null"))

    def test_hypotheses_link_conclusions_to_their_evidence(self):
        b = self.b
        self.connect(list(preview.RUNS.values()))
        self.click('[data-view="hypotheses"]')
        b.wait_for(SETTLED)
        self.assertEqual(b.js("document.querySelectorAll('.hyp-card').length"), 2)
        self.assertEqual(b.js("document.querySelectorAll('.hyp-card.st-supported').length"), 1)
        self.click(".hyp-card.st-supported .ev-chip")
        b.wait_for("document.querySelector('.insp-body .badges')")
        self.assertEqual(self.text("#insp-eyebrow"), "Evidence")
        self.assertTrue(b.js("document.querySelector('#insp-back').hidden === false"))
        self.click("#insp-back")
        b.wait_for("document.querySelector('#insp-eyebrow').textContent === 'Summary'")

    def test_abstained_run_never_looks_like_a_confirmed_cause(self):
        b = self.b
        self.connect([preview.RUNS["config-cause"], preview.RUNS["configmap-unavailable"]])
        self.click("#run-pill")
        b.wait_for("!document.querySelector('#runs-popover').hidden")
        b.js("document.querySelectorAll('.run-item')[1].click(); 1")
        b.wait_for("document.querySelector('#run-title').textContent === 'ca-scenario-001-configmap-unavailable'")
        b.wait_for(SETTLED)
        self.assertEqual(self.text(".outcome-word"), "Abstained")
        self.assertEqual(b.js("document.querySelector('.card-outcome').className.includes('is-sage')"), False)
        self.assertEqual(b.js("document.querySelectorAll('.node.is-supported, .rel-supported').length"), 0)
        self.assertEqual(b.js("document.querySelectorAll('.marker.is-ghost').length"), 1)
        self.click(".marker.is-ghost")
        b.wait_for(SETTLED)
        self.assertEqual(self.text("#insp-eyebrow"), "Gap")
        self.assertIn("k8s.configmaps", self.text(".insp-title"))

    def test_untrusted_evidence_text_is_rendered_as_text(self):
        b = self.b
        self.connect([HOSTILE_RUN])
        self.click('[data-view="evidence"]')
        b.wait_for(SETTLED)
        rows = b.js("document.querySelectorAll('.ev-row').length")  # find the hostile record via the table
        self.assertGreater(rows, 0)
        for i in range(rows):
            b.js(f"document.querySelectorAll('.ev-row')[{i}].click(); 1")
            b.wait_for("document.querySelector('.insp-body .badges')")
            if b.js("document.querySelector('.source-text pre')?.textContent") == HOSTILE:
                break
        pre = ".source-text pre"
        self.assertEqual(self.text(pre), HOSTILE)
        self.assertEqual(b.js(f"document.querySelector('{pre}').children.length"), 0)
        self.assertEqual(b.js("document.querySelectorAll('.insp-content img, .insp-content script').length"), 0)
        time.sleep(0.3)
        self.assertIsNone(b.js("window.__pwned ?? null"))

    def test_refusals_are_shown_without_any_run_content(self):
        b = self.b
        self.connect([preview.RUNS["config-cause"], UNGRANTED_RUN])
        b.js("document.querySelector('#run-pill').click(); 1")
        b.wait_for("!document.querySelector('#runs-popover').hidden")
        b.js("document.querySelectorAll('.run-item')[1].click(); 1")
        b.wait_for("document.querySelector('#state-panel') && !document.querySelector('#state-panel').hidden")
        self.assertEqual(self.text(".state-card h2"), "Run not granted")
        self.assertEqual(b.js("[...document.querySelectorAll('.layer')].filter(l => l.childElementCount).length"), 0)
        self.assertEqual(self.text("#mode-chip"), "No data")

    def test_small_screens_have_no_horizontal_scroll(self):
        b = self.b
        for width in (390, 768, 1024):
            with self.subTest(width=width):
                b.call("Emulation.setDeviceMetricsOverride", width=width, height=844, deviceScaleFactor=1, mobile=width < 760)
                if width == 390:
                    self.connect(list(preview.RUNS.values()))
                time.sleep(0.3)
                self.assertLessEqual(b.js("document.documentElement.scrollWidth"), width)


@unittest.skipUnless(BROWSER or REQUIRED, "no Chromium-family browser installed (set CA_BROWSER)")
class ReducedMotionTests(unittest.TestCase):
    def test_reduced_motion_switches_views_without_movement(self):
        server, token, secret_dir, _ = serve()
        b = _cdp.Browser(1440, 900, reduced_motion=True)
        try:
            b.navigate(f"http://127.0.0.1:{server.port}/")
            b.js(f"document.querySelector('#token').value = {json.dumps(token)};"
                 f"document.querySelector('#run-ids').value = {json.dumps(preview.RUNS['config-cause'])};"
                 "document.querySelector('#connect-form').requestSubmit(); 1")
            b.wait_for("document.querySelector('#app').dataset.state === 'ready'")
            b.js("document.querySelector('.card-hero').click(); 1")
            moving = b.js("document.getAnimations().flatMap(a => a.effect.getKeyframes().flatMap(k => Object.keys(k)))"
                          ".filter(p => ['transform', 'width', 'height', 'translate', 'scale'].includes(p))")
            self.assertEqual(moving, [])
            b.wait_for("document.querySelector('#stage').dataset.focus === 'hero'")
            self.assertEqual(b.console_errors(), [])
        finally:
            b.close()
            server.shutdown()
            server.server_close()
            shutil.rmtree(secret_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
