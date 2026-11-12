"""Browser startup reliability of the CDP test harness, against a fake browser (no Chrome needed).

Reproduces what failed on hosted runners: the first launch of a job wrote DevToolsActivePort after
more than 20 s and then accepted /json/list without answering within the harness's single 5 s read,
so setUp raised and the browser process and its profile were left behind. Also covered: refused
connections, partial and malformed answers, no page target yet, process exits before and after the
port, a launch that never becomes ready, a failing terminate, a refused WebSocket, sanitized
diagnostics and the unchanged loopback-only command line.

The fake browser (``_fake_devtools.py``) is launched through the harness's own ``find_browser`` and
``subprocess.Popen`` calls, so the harness code under test is exactly what launches Chrome.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cdp  # noqa: E402
import _fake_devtools  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "_fake_devtools.py")


class StartupReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="ca-fake-state-")
        self.procs = []
        self.terminate_fails = False
        self.mode = "ok"
        self.patches = [
            mock.patch.object(_cdp, "find_browser", lambda: sys.executable),
            mock.patch.object(_cdp, "subprocess", SimpleNamespace(
                Popen=self._popen, DEVNULL=subprocess.DEVNULL, PIPE=subprocess.PIPE,
                TimeoutExpired=subprocess.TimeoutExpired)),
            mock.patch.object(_cdp, "STARTUP_TIMEOUT", 15.0, create=True),
            mock.patch.object(_cdp, "REQUEST_TIMEOUT", 0.5, create=True),
            mock.patch.object(_cdp, "START_ATTEMPTS", 2, create=True),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        for proc in self.procs:  # never leak a fake, even when the harness under test did
            if proc.poll() is None:
                subprocess.Popen.kill(proc)
                proc.wait(10)
        for profile in self.profiles():
            _rmtree(profile)
        _rmtree(self.state)

    def _popen(self, args, **kwargs):
        argv = [sys.executable, "-I", FAKE, f"--fake-mode={self.mode}", f"--fake-state={self.state}", *args[1:]]
        proc = _FlakyTerminate(argv, **kwargs) if self.terminate_fails else subprocess.Popen(argv, **kwargs)
        self.procs.append(proc)
        return proc

    def launches(self):
        return [json.loads(p.read_text()) for p in sorted(Path(self.state).glob("launch-*.json"))]

    def profiles(self):
        return [a.split("=", 1)[1] for argv in self.launches() for a in argv if a.startswith("--user-data-dir=")]

    def assert_nothing_left(self):
        for proc in self.procs:
            self.assertIsNotNone(proc.poll(), "a browser process was left running")
        for profile in self.profiles():
            self.assertFalse(os.path.exists(profile), "a browser profile directory was left behind")

    def start(self, mode, **settings):
        self.mode = mode
        with mock.patch.multiple(_cdp, create=True, POLL_INTERVAL=0.05, **settings):
            return _cdp.Browser(800, 600)

    def start_fails(self, mode, **settings):
        self.mode = mode
        began = time.monotonic()
        with mock.patch.multiple(_cdp, create=True, POLL_INTERVAL=0.05, **settings):
            with self.assertRaises(getattr(_cdp, "BrowserStartError", ())) as caught:
                _cdp.Browser(800, 600)
        return str(caught.exception), time.monotonic() - began

    # ---- readiness races

    def test_a_slow_cold_start_is_waited_for(self):
        """The CI failure: the port appears late and /json/list stays silent for longer than 5 s."""
        b = self.start("port_delay=1,stall=6.5")
        try:
            self.assertEqual(b.call("Runtime.evaluate", expression="1"), {})
            self.assertEqual(len(self.launches()), 1, "a slow start is waited for, not relaunched")
        finally:
            self.assertFalse(b.close())
        self.assert_nothing_left()

    def test_refused_connections_are_retried_until_the_browser_listens(self):
        b = self.start("refuse=3")
        self.assertFalse(b.close())
        self.assert_nothing_left()

    def test_partial_and_malformed_answers_are_retried(self):
        b = self.start("garbage=2")
        self.assertFalse(b.close())
        self.assert_nothing_left()

    def test_no_page_target_yet_is_retried(self):
        b = self.start("empty=1")
        self.assertFalse(b.close())
        self.assert_nothing_left()

    # ---- failures are bounded, prompt and clean

    def test_an_exit_after_the_port_is_detected_promptly(self):
        message, took = self.start_fails("exit_after_port=3", STARTUP_TIMEOUT=30.0)
        self.assertLess(took, 10, "an exited browser must not be waited on until the deadline")
        self.assertIn("exited with code 3", message)
        self.assertIn("attempt 2", message)
        self.assertEqual(len(self.launches()), 2)
        self.assert_nothing_left()

    def test_an_exit_before_the_port_is_detected_promptly(self):
        message, took = self.start_fails("exit_before_port=4", STARTUP_TIMEOUT=30.0)
        self.assertLess(took, 10)
        self.assertIn("DevToolsActivePort failed", message)
        self.assertIn("exited with code 4", message)
        self.assert_nothing_left()

    def test_a_launch_that_never_answers_is_bounded_and_cleaned_up(self):
        message, took = self.start_fails("hang", STARTUP_TIMEOUT=2.0)
        self.assertLess(took, 12, "two bounded attempts")
        self.assertIn("/json/list failed", message)
        self.assertIn("browser exit code: none (was running; stopped)", message)
        profiles = self.profiles()
        self.assertEqual(len(profiles), 2)
        self.assertNotEqual(profiles[0], profiles[1], "the retry uses a fresh profile")
        self.assert_nothing_left()

    def test_a_wedged_first_launch_is_replaced_by_a_fresh_one(self):
        b = self.start("hang|ok", STARTUP_TIMEOUT=2.0)
        try:
            self.assertEqual(b.start_attempts, 2)
            first = self.procs[0]
            self.assertIsNotNone(first.poll(), "the wedged process was stopped before the retry")
            self.assertFalse(os.path.exists(self.profiles()[0]), "its profile was removed")
        finally:
            self.assertFalse(b.close())
        self.assert_nothing_left()

    def test_a_single_attempt_is_honoured(self):
        message, _ = self.start_fails("hang", STARTUP_TIMEOUT=1.0, START_ATTEMPTS=1)
        self.assertNotIn("attempt 2", message)
        self.assertEqual(len(self.launches()), 1)
        self.assert_nothing_left()

    def test_cleanup_continues_when_terminate_fails(self):
        self.terminate_fails = True
        message, _ = self.start_fails("hang", STARTUP_TIMEOUT=1.0, START_ATTEMPTS=1)
        self.assertIn("cleanup problems: terminate: OSError", message)
        self.assert_nothing_left()  # killed instead, and the profile still removed

    def test_a_refused_websocket_is_a_cleaned_up_start_failure(self):
        message, _ = self.start_fails("ws_refuse")
        self.assertIn("CDP setup failed", message)
        self.assert_nothing_left()

    def test_close_is_idempotent(self):
        b = self.start("ok")
        self.assertFalse(b.close())
        self.assertFalse(b.close())
        self.assert_nothing_left()

    # ---- diagnostics and security settings

    def test_failure_diagnostics_are_sanitized(self):
        message, _ = self.start_fails("noisy,exit_after_port=3", START_ATTEMPTS=1)
        self.assertIn("browser stderr (last lines, sanitized)", message)
        self.assertIn("ws://<redacted>", message)
        self.assertIn("<profile>", message)
        self.assertNotIn(_fake_devtools.SECRET, message)
        for profile in self.profiles():
            self.assertNotIn(profile, message)
        self.assertNotIn("\x1b", message)
        self.assertNotIn("\x07", message)
        self.assert_nothing_left()

    def test_the_browser_stays_on_loopback_with_unchanged_flags(self):
        b = self.start("ok")
        b.close()
        (argv,) = self.launches()
        flags = [a for a in argv if not a.startswith("--fake-")]
        for flag in ("--headless=new", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                     "--no-first-run", "--disable-extensions", "--disable-background-networking",
                     "--disable-sync", "--disable-component-update", "--hide-scrollbars"):
            self.assertIn(flag, flags)
        self.assertFalse([a for a in flags if a.startswith("--remote-allow-origins")])
        profile = Path(self.profiles()[0])
        self.assertTrue(profile.name.startswith("ca-browser-"))
        self.assertEqual(profile.parent.resolve(), Path(tempfile.gettempdir()).resolve())
        self.assertEqual(flags[-1], "about:blank")
        self.assert_nothing_left()

    def test_only_loopback_websocket_urls_are_accepted(self):
        with self.assertRaises(AssertionError):
            _cdp.WebSocket("ws://example.invalid:9222/devtools/page/X")


class _FlakyTerminate(subprocess.Popen):
    def terminate(self):
        raise OSError("terminate refused (simulated)")


def _rmtree(path):
    import shutil
    for _ in range(40):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
