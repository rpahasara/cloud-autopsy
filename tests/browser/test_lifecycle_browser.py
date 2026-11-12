"""CA-P2-004b: run lifecycle states in the existing dashboard (headless browser, 127.0.0.1 only).

Served by the real ``ApiService`` with the synthetic preview results plus a stand-in status
loader (no database). The token names one preview run for results and four runs for status only.
Lifecycle states appear with the existing status styles, never as verified and never as outcomes,
and opening one shows its status in the existing state panel.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import uuid
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


def run(tag):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ca-lifecycle-browser/{tag}"))


COLLECTING, SEALING, FAILED, SEALED = run("collecting"), run("sealing"), run("failed"), run("sealed")
VERIFIED = preview.RUNS["config-cause"]
LIFECYCLE = {COLLECTING: {"state": "collecting", "failure_reason": None, "lease_expired": None},
             SEALING: {"state": "sealing", "failure_reason": None, "lease_expired": True},
             FAILED: {"state": "failed", "failure_reason": "seal:attempts_exhausted", "lease_expired": None},
             SEALED: {"state": "sealed", "failure_reason": None, "lease_expired": None}}


def load_status(run_id):
    record = LIFECYCLE.get(run_id) or ({"state": "sealed", "failure_reason": None, "lease_expired": None}
                                       if run_id == VERIFIED else None)
    return record and SimpleNamespace(state=record["state"], to_record=lambda: dict(record))


@unittest.skipUnless(BROWSER or REQUIRED, "no Chromium-family browser installed (set CA_BROWSER)")
class LifecycleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load, ready = preview.backend()
        cls.secret_dir = Path(tempfile.mkdtemp(prefix="ca-lifecycle-browser-"))
        record, tokens = G.issue({"viewer": [VERIFIED]}, {"viewer": list(LIFECYCLE)})
        G.write_private(cls.secret_dir / "grants.json", json.dumps(record).encode("utf-8"))
        service = ApiService(G.load(cls.secret_dir / "grants.json"), load, ready, ui=ui.load_assets(), preview=True,
                             load_status=load_status)
        cls.server = LoopbackServer(service, quiet=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.token = tokens["viewer"]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.secret_dir, ignore_errors=True)

    def setUp(self):
        self.b = _cdp.Browser(1440, 900)
        self.addCleanup(self.b.close)
        self.b.navigate(f"http://127.0.0.1:{self.server.port}/")
        self.b.js(f"document.querySelector('#token').value = {json.dumps(self.token)};"
                  "document.querySelector('#connect-form').requestSubmit(); 1")
        self.b.wait_for("document.querySelector('#app').dataset.page === 'home' && "
                        "document.querySelector('.h-granted .m-value')?.textContent === '5'", 30)

    def text(self, selector):
        return self.b.js(f"document.querySelector({json.dumps(selector)})?.textContent ?? null")

    def test_lifecycle_states_use_existing_styles_and_never_count_as_outcomes(self):
        b = self.b
        self.assertEqual(self.text(".h-resolved .m-value"), "1")    # only the result-granted run has an outcome
        self.assertIn("in progress", self.text(".h-attention .m-foot"))
        b.js("document.querySelector('[data-view=investigations]').click(); 1")
        b.wait_for(f"document.querySelector('.inv-row[data-run=\"{FAILED}\"] .inv-ver') !== null", 30)
        expected = {COLLECTING: ("Collecting · not verified", "is-collecting"),
                    SEALING: ("Sealing · not verified", "is-sealing"),
                    SEALED: ("Sealed · status only", "is-sealed"),
                    FAILED: ("Run failed seal:attempts_exhausted", "is-run_failed")}
        for run_id, (label, cls) in expected.items():
            with self.subTest(state=cls):
                cell = f".inv-row[data-run=\"{run_id}\"] .inv-ver"
                self.assertEqual(self.text(cell).replace(" ", " ").strip(), label)
                self.assertEqual(b.js(f"document.querySelector({json.dumps(cell)}).className"), f"inv-ver {cls}")
                # existing tones only: in progress as preview (amber), failed as refusals (rose)
                colour = b.js(f"getComputedStyle(document.querySelector({json.dumps(cell)})).color")
                self.assertEqual(colour, "rgb(240, 188, 170)" if cls == "is-run_failed" else "rgb(240, 211, 155)")
                self.assertEqual(self.text(f".inv-row[data-run=\"{run_id}\"] .inv-title b"), "—")  # no plan, no outcome
        self.assertEqual(b.console_errors(), [])

    def test_opening_a_lifecycle_run_shows_its_status_and_nothing_verified(self):
        b = self.b
        cases = ((FAILED, "Run failed", "reason: seal:attempts_exhausted"),
                 (SEALING, "Sealing in progress", "lease has expired"),
                 (SEALED, "Sealed · status only", "lifecycle status only"))
        for run_id, title, detail in cases:
            with self.subTest(title=title):
                b.js(f"window.location.hash = ''; 1")
                b.js("document.querySelector('[data-view=investigations]')?.click(); 1")
                b.wait_for(f"document.querySelector('.inv-row[data-run=\"{run_id}\"]') !== null", 30)
                b.js(f"document.querySelector('.inv-row[data-run=\"{run_id}\"]').click(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'run' && "
                           f"document.querySelector('#state-panel h2')?.textContent === {json.dumps(title)}", 30)
                self.assertIn(detail, self.text("#state-panel"))
                self.assertNotIn("Verified", self.text("#mode-chip") or "")
                b.js("document.querySelector('#rail-overview').click(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'home'", 30)
        self.assertEqual(b.console_errors(), [])


if __name__ == "__main__":
    unittest.main()
