"""CA-P2-006c dashboard in a real headless browser (Chrome/Chromium/Edge over CDP, 127.0.0.1 only).

The page is served by the real ``ApiService`` with the dashboard assets and the labelled
synthetic preview backend (no database). One extra run carries a hostile log message to prove
that untrusted evidence text is rendered as text. Skipped when no browser is installed, unless
``CA_BROWSER_REQUIRE=1`` (CI), where a missing browser fails the run.
"""

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
MISSING_RUN = str(uuid.uuid5(uuid.NAMESPACE_URL, "ca-dashboard-browser/missing"))  # granted, no stored result
CSP_RECORDER = ("window.__csp = []; document.addEventListener('securitypolicyviolation', "
                "e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")
HOME_SETTLED = ("[...document.querySelectorAll('.h-card, .h-layer')].every(e => e.getAnimations().length === 0)"
                " && !document.querySelector('.h-card.is-morphing')")
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
    record, tokens = G.issue({"viewer": list(preview.RUNS.values()) + [HOSTILE_RUN, MISSING_RUN]})
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

    # ---- Gaps & uncertainty morph (PR #25 review: compact and expanded content overlapped on collapse)

    CARD_STATE = ("(() => { const c = document.querySelector('[data-card=%s]'); const r = c.getBoundingClientRect();"
                  "const o = e => Number(getComputedStyle(e).opacity);"
                  "return {x: r.x, y: r.y, w: r.width, h: r.height, compact: o(c.querySelector('.layer-compact')),"
                  "expanded: o(c.querySelector('.layer-expanded')), morph: c.classList.contains('is-morphing'),"
                  "z: Number(getComputedStyle(c).zIndex) || 0, inspZ: Number(getComputedStyle(document.querySelector('#inspector')).zIndex),"
                  "inline: [...c.querySelectorAll('.layer')].filter(l => l.style.width || l.style.height).length,"
                  "held: [...c.querySelectorAll('.layer')].reduce((n, l) => n + l.getAnimations().length, 0),"
                  "transform: getComputedStyle(c).transform}; })()")

    @property
    def GAPS_STATE(self):
        return self.CARD_STATE % "gaps"

    def step_through(self, trigger, card="gaps"):
        """Run a transition with its animations paused and sampled every 30 ms (timers above 300 ms deferred)."""
        b = self.b
        b.js("window.__st = window.__st || window.setTimeout; window.setTimeout = (f, ms) => window.__st(f, ms > 300 ? 1e8 : ms); 1")
        # Keep the transition's own animations: a paused, unfilled animation sought past its end
        # drops out of document.getAnimations() but must still be finished.
        b.js(f"{trigger}; window.__anims = document.getAnimations(); window.__anims.forEach(a => a.pause()); 1")
        frames = []
        for t in range(0, 900, 30):
            b.js(f"window.__anims.forEach(a => {{ a.currentTime = {t}; }}); 1")
            frames.append((t, b.js(self.CARD_STATE % card)))
        b.js("window.__anims.forEach(a => a.finish()); window.setTimeout = window.__st; 1")
        return frames

    def settle_gaps(self):
        self.b.wait_for(SETTLED)
        return self.b.js(self.GAPS_STATE)

    def assert_overview_gaps(self, state, original):
        for key in ("x", "y", "w", "h"):
            self.assertAlmostEqual(state[key], original[key], delta=0.5, msg=key)
        self.assertEqual((state["compact"], state["morph"], state["inline"], state["held"], state["transform"]),
                         (1, False, 0, 0, "none"))

    def test_gaps_card_layers_never_show_together_while_morphing(self):
        b = self.b
        self.connect(list(preview.RUNS.values()))
        for card in ("gaps", "hyps", "timeline", "evidence"):  # gaps first: the reported defect
            original = b.js(self.CARD_STATE % card)
            for name, trigger in (("expand", f"document.querySelector('[data-card={card}]').click()"),
                                  ("collapse", "document.querySelector('#insp-close').click()")):
                frames = self.step_through(trigger, card)
                for t, s in frames:
                    with self.subTest(card=card, phase=name, t=t):
                        if s["morph"]:
                            self.assertLessEqual(min(s["compact"], s["expanded"]), 0.25,
                                                 "compact and expanded content visible at the same time")
                            self.assertGreater(s["z"], s["inspZ"], "card in flight drawn under the inspector")
                b.wait_for(f"!document.querySelector('[data-card={card}]').classList.contains('is-morphing')", 5)
            b.wait_for(SETTLED)
            self.assert_overview_gaps(b.js(self.CARD_STATE % card), original)

    def test_gaps_card_survives_rapid_toggling_switching_and_resizing(self):
        b = self.b
        self.connect(list(preview.RUNS.values()))
        original = b.js(self.GAPS_STATE)
        for _ in range(3):  # expand and collapse in quick succession, interrupting each transition
            b.js("document.querySelector('[data-card=gaps] .expand').click(); 1")
            time.sleep(0.08)
            b.js("document.querySelector('[data-card=gaps] .expand').click(); 1")
            time.sleep(0.05)
        self.assert_overview_gaps(self.settle_gaps(), original)
        b.js("document.querySelector('[data-card=gaps]').click(); 1")  # gaps -> hypotheses -> overview
        time.sleep(0.15)
        b.js("document.querySelector('[data-view=hypotheses]').click(); 1")
        b.wait_for(SETTLED)
        self.assertEqual(b.js("document.querySelector('#stage').dataset.focus"), "hyps")
        self.assertFalse(self.visible("[data-card=gaps]"))
        self.click('[data-view="overview"]')
        self.assert_overview_gaps(self.settle_gaps(), original)
        b.js("document.querySelector('[data-card=gaps]').click(); 1")  # resize while expanding, then collapse
        time.sleep(0.12)
        b.call("Emulation.setDeviceMetricsOverride", width=1280, height=860, deviceScaleFactor=1, mobile=False)
        b.wait_for(SETTLED)
        focused = b.js(self.GAPS_STATE)
        self.assertEqual((focused["inline"], focused["morph"], focused["expanded"]), (0, False, 1))
        b.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
        self.key("Escape", 27)
        self.assert_overview_gaps(self.settle_gaps(), original)

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
        b.js(f"document.querySelector('.run-item[data-run=\"{preview.RUNS['configmap-unavailable']}\"]').click(); 1")
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
        b.js(f"document.querySelector('.run-item[data-run=\"{UNGRANTED_RUN}\"]').click(); 1")
        b.wait_for("document.querySelector('#state-panel') && !document.querySelector('#state-panel').hidden")
        self.assertEqual(self.text(".state-card h2"), "Run not granted")
        self.assertEqual(b.js("[...document.querySelectorAll('.layer')].filter(l => l.childElementCount).length"), 0)
        self.assertEqual(self.text("#mode-chip"), "No data")

    def test_run_switcher_lists_typed_and_granted_runs_once_each(self):  # CA-P2-006d
        b = self.b
        typed = [preview.RUNS["configmap-unavailable"], UNGRANTED_RUN, preview.RUNS["config-cause"]]
        self.connect(typed)
        granted = set(preview.RUNS.values()) | {HOSTILE_RUN, MISSING_RUN}
        b.wait_for(f"document.querySelectorAll('.run-item').length === {len(granted | set(typed))}", 20)
        listed = b.js("[...document.querySelectorAll('.run-item')].map(e => e.dataset.run)")
        self.assertEqual(len(listed), len(set(listed)), "duplicate switcher entries")
        self.assertEqual(set(listed), granted | set(typed))  # nothing beyond the grant and what was typed
        self.assertEqual(listed[:3], typed)  # typed runs first, in the order given
        state = b.js(f"document.querySelector('.run-item[data-run=\"{UNGRANTED_RUN}\"] .run-state').textContent")
        self.assertEqual(state, "Run not granted")  # refused by the API (403); never filled from the summaries
        self.assertNotIn(UNGRANTED_RUN, [i["run_id"] for i in self.b.js(
            "fetch('/v1/summaries/1', {headers: {Authorization: 'Bearer ' + " + json.dumps(self.token) + "}}).then(r => r.json())"
            ".then(d => d.items)")])

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


@unittest.skipUnless(BROWSER or REQUIRED, "no Chromium-family browser installed (set CA_BROWSER)")
class HomeBrowserTests(unittest.TestCase):
    """CA-P2-006d Home: token-only sign-in, figures equal to the API's, Investigations, navigation."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.token, cls.secret_dir, _ = serve()
        cls.url = f"http://127.0.0.1:{cls.server.port}/"
        con = http.client.HTTPConnection("127.0.0.1", cls.server.port, timeout=30)
        con.request("GET", "/v1/summaries/1", headers={"Authorization": f"Bearer {cls.token}"})
        cls.summaries = json.loads(con.getresponse().read())
        con.close()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.secret_dir, ignore_errors=True)

    def setUp(self):
        self.b = _cdp.Browser(1440, 900)
        self.b.call("Page.addScriptToEvaluateOnNewDocument", source=CSP_RECORDER)
        self.b.navigate(self.url)
        self.b.js(f"document.querySelector('#token').value = {json.dumps(self.token)};"
                  "document.querySelector('#connect-form').requestSubmit(); 1")
        self.b.wait_for("document.querySelector('#app').dataset.page === 'home' && document.querySelector('#connect').hidden"
                        " && document.querySelector('.h-granted .m-value')?.textContent === String("
                        f"{self.summaries['granted_total']})", 20)
        self.b.wait_for(HOME_SETTLED)

    def tearDown(self):
        try:
            self.assertEqual(self.b.js("window.__csp"), [], "CSP violations")
            self.assertEqual(self.b.console_errors(), [], "console errors")
        finally:
            self.b.close()

    def text(self, selector):
        return self.b.js(f"document.querySelector({json.dumps(selector)})?.textContent ?? null")

    def test_token_only_sign_in_opens_home_with_the_apis_own_figures(self):
        items = self.summaries["items"]
        results = [i for i in items if i["state"] in ("verified", "preview")]
        resolved = sum(1 for i in results if i["outcome"]["status"] == "resolved")
        figures = {".h-granted .m-value": str(self.summaries["granted_total"]),
                   ".h-resolved .m-value": str(resolved),
                   ".h-abstained .m-value": str(len(results) - resolved),
                   ".h-attention .m-value": str(sum(1 for i in items if i["state"] == "unverifiable"))}
        for selector, expected in figures.items():
            with self.subTest(selector=selector):
                self.assertEqual(self.text(selector), expected)
        self.assertEqual(self.text("#run-title"), "Cloud Autopsy")
        self.assertIn("not verified", self.text("#mode-chip"))
        self.assertIn("1 not found", self.text(".h-attention .m-foot"))  # MISSING_RUN, never counted as an outcome
        self.assertEqual(self.text(".orb-value"), f"{len(items)}/{self.summaries['granted_total']}")
        self.assertTrue(self.text(".h-hero .gauge-value").startswith("0"))  # preview: nothing is verified
        self.assertEqual(self.b.js("[...document.querySelectorAll('#nav [data-view]')].filter(b => b.getAttribute('aria-disabled') === 'true')"
                                   ".map(b => b.dataset.view)"), ["overview", "investigation", "timeline", "hypotheses", "evidence"])
        self.assertEqual(self.b.js("[localStorage.length, sessionStorage.length, document.cookie]"), [0, 0, ""])

    def test_investigations_filter_sort_and_open_a_run(self):
        b = self.b
        b.js("document.querySelector('[data-view=investigations]').click(); 1")
        b.wait_for("document.querySelector('#home').dataset.focus === 'band'")
        b.wait_for(HOME_SETTLED)
        rows = b.js("document.querySelectorAll('.inv-row[data-run]').length")
        self.assertEqual(rows, len(self.summaries["items"]))
        b.js("document.querySelector('[data-filter=resolved]').click(); 1")
        resolved = [i for i in self.summaries["items"] if i.get("outcome", {}).get("status") == "resolved"]
        self.assertEqual(b.js("document.querySelectorAll('.inv-row[data-run]').length"), len(resolved))
        b.js("document.querySelector('[data-filter=all]').click(); document.querySelector('[data-sort=title]').click(); 1")
        titles = b.js("[...document.querySelectorAll('.inv-row[data-run] .inv-title b')].map(e => e.textContent).filter(t => t !== '\u2014')")
        self.assertEqual(titles, sorted(titles))
        missing = b.js(f"document.querySelector('.inv-row[data-run=\"{MISSING_RUN}\"] .inv-ver').textContent")
        self.assertEqual(missing, "Not found")
        target = next(i for i in self.summaries["items"] if i.get("plan_id") == "ca-scenario-001-configmap-unavailable")
        b.js(f"document.querySelector('.inv-row[data-run=\"{target['run_id']}\"]').click(); 1")
        b.wait_for("document.querySelector('#app').dataset.page === 'run' && "
                   "document.querySelector('#run-title').textContent === 'ca-scenario-001-configmap-unavailable'", 20)
        self.assertEqual(self.text(".outcome-word"), "Abstained")
        self.assertEqual(b.js("document.querySelectorAll('#nav [data-view][aria-disabled=true]').length"), 0)
        b.js("document.querySelector('[data-view=home]').click(); 1")
        b.wait_for("document.querySelector('#app').dataset.page === 'home' && !document.querySelector('#home').hidden")
        b.wait_for(HOME_SETTLED)
        self.assertIsNone(b.js("document.querySelector('#home').dataset.focus ?? null"))
        self.assertEqual(self.text("#nav .is-on"), "Home")

    def test_investigations_view_reverses_and_escape_returns_home(self):
        b = self.b
        before = b.js("(() => { const r = document.querySelector('.h-band').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
        b.js("document.querySelector('.band-notch').click(); 1")
        b.wait_for("document.querySelector('.h-band').getAnimations().length > 0")
        b.wait_for(HOME_SETTLED)
        self.assertTrue(b.js("document.querySelector('.h-band').hasAttribute('data-focused')"))
        self.assertEqual(b.js("getComputedStyle(document.querySelector('.h-trend')).visibility"), "hidden")
        for kind, code in (("keyDown", 27), ("keyUp", 27)):
            b.call("Input.dispatchKeyEvent", type=kind, key="Escape", code="Escape", windowsVirtualKeyCode=code)
        b.wait_for("!document.querySelector('#home').dataset.focus")
        b.wait_for(HOME_SETTLED)
        after = b.js("(() => { const r = document.querySelector('.h-band').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
        for a, c in zip(before, after):
            self.assertAlmostEqual(a, c, delta=0.5)
        self.assertEqual(b.js("[...document.querySelectorAll('.h-layer')].filter(l => l.style.width || l.getAnimations().length).length"), 0)

    # ---- PR #26 polish: page transitions, content visibility

    PAGE_STATE = ("(() => { const home = document.querySelector('#home'), stage = document.querySelector('#stage');"
                  "const op = e => e.hidden ? 0 : Number(getComputedStyle(e).opacity);"
                  "return {page: document.querySelector('#app').dataset.page, focus: home.dataset.focus || null,"
                  "home: op(home), stage: op(stage), pending: stage.hasAttribute('data-pending'),"
                  "title: document.querySelector('#run-title').textContent}; })()")
    PAGES_SETTLED = (HOME_SETTLED + " && [document.querySelector('#home'), document.querySelector('#stage')]"
                     ".every(e => e.getAnimations().length === 0 && !e.style.position)")

    def step_page_change(self, trigger):
        """Step a page change with its animations paused (timers above 300 ms deferred); return per-frame states."""
        b = self.b
        b.js("window.__st = window.__st || window.setTimeout; window.setTimeout = (f, ms) => window.__st(f, ms > 300 ? 1e8 : ms); 1")
        b.js(f"{trigger}; window.__anims = document.getAnimations().filter(a => isFinite(a.effect.getComputedTiming().endTime));"
             "window.__anims.forEach(a => a.pause()); 1")
        frames = []
        for t in range(0, 900, 30):
            b.js(f"window.__anims.forEach(a => {{ a.currentTime = {t}; }}); 1")
            frames.append((t, b.js(self.PAGE_STATE)))
        b.js("window.__anims.forEach(a => a.finish()); window.setTimeout = window.__st; 1")
        b.wait_for(self.PAGES_SETTLED, 10)
        return frames

    def click(self, selector):
        rect = self.b.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); e.scrollIntoView({{block: 'center'}});"
                         "const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + Math.min(r.height / 2, 40)]; })()")
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.b.call("Input.dispatchMouseEvent", type=kind, x=rect[0], y=rect[1], button="left", clickCount=1)

    def open_run_from_investigations(self, plan):
        b = self.b
        b.js("document.querySelector('[data-view=investigations]').click(); 1")
        b.wait_for("document.querySelector('#home').dataset.focus === 'band'")
        b.wait_for(self.PAGES_SETTLED)
        run = next(i for i in self.summaries["items"] if i.get("plan_id") == plan)["run_id"]
        b.js(f"document.querySelector('.inv-row[data-run=\"{run}\"]').click(); 1")
        b.wait_for(f"document.querySelector('#run-title').textContent === {json.dumps(plan)} && document.querySelector('.outcome-word')", 20)
        b.wait_for(self.PAGES_SETTLED)
        b.wait_for(SETTLED)
        return run

    def assert_direct(self, frames, page, focus):
        for t, f in frames:
            with self.subTest(t=t):
                self.assertEqual(f["page"], page)
                if page == "home":
                    self.assertEqual(f["focus"], focus, "Home revealed in a different view than requested")
                self.assertGreater(max(f["home"], f["stage"]), 0.6 if 120 <= t <= 600 else 0.0,
                                   "both pages nearly invisible: a blank frame")

    def test_detail_to_home_goes_straight_to_the_overview(self):
        self.open_run_from_investigations("ca-scenario-001-config-cause")
        self.click('[data-view="overview"]')
        frames = self.step_page_change("document.querySelector('[data-view=home]').click()")
        self.assert_direct(frames, "home", None)
        final = self.b.js(self.PAGE_STATE)
        self.assertEqual((final["page"], final["focus"], final["home"], final["stage"]), ("home", None, 1, 0))
        self.assertEqual(self.text("#nav .is-on"), "Home")

    def test_detail_to_investigations_goes_straight_to_the_table(self):
        self.open_run_from_investigations("ca-scenario-001-no-symptom")
        frames = self.step_page_change("document.querySelector('[data-view=investigations]').click()")
        self.assert_direct(frames, "home", "band")
        self.assertEqual(self.text("#nav .is-on"), "Investigations")
        self.assertTrue(self.b.js("document.querySelectorAll('.inv-row[data-run]').length > 0"))

    def test_switching_cases_never_shows_the_previous_case(self):
        b = self.b
        self.open_run_from_investigations("ca-scenario-001-config-cause")
        b.js("document.querySelector('[data-view=home]').click(); 1")
        b.wait_for(self.PAGES_SETTLED)
        other = next(i for i in self.summaries["items"] if i.get("plan_id") == "ca-scenario-001-symptom-before-change")["run_id"]
        b.js("document.querySelector('[data-view=investigations]').click(); 1")
        b.wait_for(self.PAGES_SETTLED)
        frames = self.step_page_change(f"document.querySelector('.inv-row[data-run=\"{other}\"]').click()")
        for t, f in frames:
            with self.subTest(t=t):
                self.assertEqual(f["page"], "run")
                if f["stage"] > 0.05:  # whenever the workspace is visible, it is the new case or a neutral skeleton
                    self.assertTrue(f["pending"] or f["title"] == "ca-scenario-001-symptom-before-change",
                                    f"previous case shown while opening another: {f['title']}")
        b.wait_for("document.querySelector('#run-title').textContent === 'ca-scenario-001-symptom-before-change'", 20)
        b.wait_for("!document.querySelector('#stage').hasAttribute('data-pending')")

    def test_rapid_navigation_and_resizing_settle_consistently(self):
        b = self.b
        run = self.open_run_from_investigations("ca-scenario-001-clock-unknown")
        for js in ("document.querySelector('[data-view=home]').click()", "document.querySelector('[data-view=investigations]').click()",
                   f"document.querySelector('.inv-row[data-run=\"{run}\"]')?.click()", "document.querySelector('[data-view=home]').click()",
                   "document.querySelector('[data-view=timeline]').click()", "document.querySelector('[data-view=home]').click()"):
            b.js(f"{js}; 1")
            time.sleep(0.07)
        b.call("Emulation.setDeviceMetricsOverride", width=1280, height=820, deviceScaleFactor=1, mobile=False)
        b.wait_for(self.PAGES_SETTLED, 15)
        time.sleep(1.2)
        b.wait_for(self.PAGES_SETTLED, 15)
        final = b.js(self.PAGE_STATE)
        self.assertEqual((final["page"], final["focus"]), ("home", None))
        self.assertEqual((final["home"], final["stage"]), (1, 0))
        self.assertEqual(self.text("#nav .is-on"), "Home")
        self.assertEqual(b.js("[document.querySelector('#home').hidden, document.querySelector('#stage').hidden]"), [False, True])

    def test_home_cards_are_fully_visible_at_desktop_sizes_and_zoom(self):
        b = self.b
        visible = ("(sel => { const el = document.querySelector(sel); el.scrollIntoView({block: 'nearest'});"
                   "const r = el.getBoundingClientRect(); let top = r.top, bottom = r.bottom;"
                   "for (let p = el.parentElement; p; p = p.parentElement) { const cs = getComputedStyle(p);"
                   "if (/(hidden|clip|auto|scroll)/.test(cs.overflow + cs.overflowY)) { const q = p.getBoundingClientRect();"
                   "top = Math.max(top, q.top); bottom = Math.min(bottom, q.bottom); } }"
                   "return {cut: Math.max(0, r.bottom - Math.min(bottom, innerHeight)) + Math.max(0, Math.max(top, 0) - r.top), h: r.height}; })")
        targets = [f"{c} .m-foot" for c in (".h-granted", ".h-resolved", ".h-abstained", ".h-attention")] + \
                  [f"{c} .m-value" for c in (".h-granted", ".h-attention")] + \
                  [f".tile.is-{k}" for k in ("resolved", "abstained", "attention")] + \
                  [".tile.is-attention .tile-line:last-child", ".chips-dark", ".recent li:last-child"]
        for w, h, dpr in ((1440, 900, 1), (1694, 900, 1), (1920, 1042, 1), (1152, 720, 1.25), (1694, 780, 1), (1366, 768, 1), (1024, 900, 1), (768, 1024, 1)):
            b.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=dpr, mobile=False)
            time.sleep(0.5)
            for sel in targets:
                with self.subTest(size=f"{w}x{h}@{dpr}", target=sel):
                    got = b.js(f"{visible}({json.dumps(sel)})")
                    self.assertGreater(got["h"], 0)
                    self.assertLessEqual(got["cut"], 0.5, "content clipped")
            if w >= 1440 and h >= 900:  # full desktop heights fit without any scrolling
                with self.subTest(size=f"{w}x{h}", check="fits"):
                    self.assertLessEqual(b.js("(m => m.scrollHeight - m.clientHeight)(document.querySelector('.main'))"), 1)

    def test_reduced_motion_page_changes_land_directly(self):
        server, token, secret_dir, _ = serve()
        b = _cdp.Browser(1440, 900, reduced_motion=True)
        try:
            b.navigate(f"http://127.0.0.1:{server.port}/")
            b.js(f"document.querySelector('#token').value = {json.dumps(token)}; document.querySelector('#connect-form').requestSubmit(); 1")
            b.wait_for("document.querySelector('#app').dataset.page === 'home' && document.querySelector('#connect').hidden", 20)
            b.js("document.querySelector('[data-view=investigations]').click(); 1")
            b.wait_for("document.querySelector('#home').dataset.focus === 'band'")
            b.js("document.querySelector('.inv-row[data-run]').click(); 1")
            b.wait_for("document.querySelector('#app').dataset.page === 'run' && document.querySelector('.outcome-word')", 20)
            b.js("document.querySelector('[data-view=home]').click(); 1")
            moving = b.js("document.getAnimations().flatMap(a => a.effect.getKeyframes().flatMap(k => Object.keys(k)))"
                          ".filter(p => ['transform', 'width', 'height'].includes(p))")
            self.assertEqual(moving, [])
            b.wait_for("document.querySelector('#app').dataset.page === 'home' && !document.querySelector('#home').dataset.focus", 10)
            self.assertEqual(b.console_errors(), [])
        finally:
            b.close()
            server.shutdown()
            server.server_close()
            shutil.rmtree(secret_dir, ignore_errors=True)

    def test_home_fits_small_screens(self):
        for width in (390, 768, 1024):
            with self.subTest(width=width):
                self.b.call("Emulation.setDeviceMetricsOverride", width=width, height=844, deviceScaleFactor=1, mobile=width < 760)
                time.sleep(0.4)
                self.assertLessEqual(self.b.js("document.documentElement.scrollWidth"), width)


if __name__ == "__main__":
    unittest.main()
