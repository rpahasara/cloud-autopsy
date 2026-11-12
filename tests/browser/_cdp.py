"""A minimal Chrome DevTools Protocol client on the Python standard library (test-only).

Launches a locally installed Chromium-family browser (Chrome, Chromium or Edge) headless with a
fresh temporary profile and remote debugging on 127.0.0.1, then speaks CDP over a small
RFC 6455 WebSocket client. No third-party package is involved; nothing leaves the machine.

Startup is bounded on the monotonic clock. DevToolsActivePort and /json/list are polled; a refused,
reset, stalled, partial or malformed answer is retried until the deadline, and a browser exit ends
the wait at once. A failed attempt always stops the process and removes its profile, and one more
attempt is made with a fresh process and profile. If that also fails, ``BrowserStartError`` names
the phase, the exit code and the sanitized end of the browser's stderr.
"""

import base64
import http.client
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CANDIDATES = (
    os.environ.get("CA_BROWSER", ""),
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

# Startup budget and polling, in seconds on the monotonic clock. A cold first launch on a hosted
# runner has taken over 20 s to write DevToolsActivePort and then accepted the /json/list
# connection without answering for more than 5 s.
STARTUP_TIMEOUT = 60.0   # per attempt: process start to a page target with CDP enabled
REQUEST_TIMEOUT = 2.0    # one DevTools HTTP request; short, so a process exit is noticed promptly
POLL_INTERVAL = 0.05
START_ATTEMPTS = 2       # one more launch, with a fresh process and profile, after a failed start
STDERR_LINES = 20


class BrowserStartError(RuntimeError):
    """The browser never reached a usable DevTools page: a harness failure, not a test result."""


class _AttemptFailed(Exception):
    pass


def find_browser():
    for name in CANDIDATES:
        if not name:
            continue
        path = shutil.which(name) or (name if Path(name).is_file() else None)
        if path:
            return path
    return None


def _sanitize(raw, profile):
    """The last lines of browser stderr: printable ASCII only, DevTools URLs and the profile path redacted."""
    text = raw.decode("utf-8", "replace")
    if profile:
        text = text.replace(profile, "<profile>")
    text = re.sub(r"wss?://\S+", "ws://<redacted>", text)
    text = "".join(c if c == "\n" or " " <= c <= "~" else "?" for c in text)
    lines = [line[:200] for line in text.splitlines() if line.strip()]
    return lines[-STDERR_LINES:]


def _describe(error):
    reason = getattr(error, "reason", None)  # urllib-style wrappers carry the socket error here
    error = reason if isinstance(reason, BaseException) else error
    return f"{type(error).__name__}: {error}"[:200]


def _stop_group(pgid, timeout=5.0):
    """POSIX: kill what is left of the browser's process group and wait until it is gone."""
    import signal
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return []
    except OSError as error:
        return [f"process group: {_describe(error)}"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return []
        except OSError:
            break
        time.sleep(0.02)
    # Killed members waiting to be reaped by init still answer signal 0, so no problem is reported
    # here; the profile removal that follows is checked instead.
    return []


def _list_targets(port, timeout):
    """GET /json/list on 127.0.0.1 with plain http.client: no proxy environment is consulted."""
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        con.request("GET", "/json/list")
        response = con.getresponse()
        body = response.read(1_048_576)
        if response.status != 200:
            raise ValueError(f"/json/list answered {response.status}")
        targets = json.loads(body)
        if not isinstance(targets, list):
            raise ValueError("/json/list is not a list")
        return [t for t in targets if isinstance(t, dict)]
    finally:
        con.close()


class WebSocket:
    def __init__(self, url, timeout=30):
        assert url.startswith("ws://127.0.0.1:"), "CDP is used on loopback only"
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = self.sock.recv(1)
                if not chunk:
                    raise ConnectionError("websocket handshake failed")
                head += chunk
            if b" 101 " not in head.split(b"\r\n", 1)[0]:
                raise ConnectionError("websocket upgrade refused")
        except BaseException:
            self.close()
            raise

    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("websocket closed")
            buf += chunk
        return bytes(buf)

    def send(self, text):
        data = text.encode("utf-8")
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        message = bytearray()
        while True:
            b1, b2 = self._recv_exact(2)
            opcode, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            payload = self._recv_exact(n)
            if opcode == 0x8:
                raise ConnectionError("websocket closed by peer")
            if opcode == 0x9:
                continue
            message += payload
            if b1 & 0x80:
                return message.decode("utf-8")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    """Headless browser with one page; ``call`` sends a CDP command and returns its result."""

    def __init__(self, width=1440, height=900, reduced_motion=False, hide_scrollbars=True):
        exe = find_browser()
        if not exe:
            raise RuntimeError("no Chromium-family browser found (set CA_BROWSER)")
        failures = []
        for attempt in range(1, max(1, START_ATTEMPTS) + 1):
            try:
                self._start(exe, width, height, reduced_motion, hide_scrollbars)
                self.start_attempts = attempt
                return
            except _AttemptFailed as failed:
                failures.append(f"attempt {attempt}: {failed}")
        raise BrowserStartError("browser did not start\n" + "\n".join(failures))

    def _start(self, exe, width, height, reduced_motion, hide_scrollbars):
        """One launch attempt. On any failure, everything it created is removed before it raises."""
        self.ws = self.proc = self._stderr = None
        self.profile = tempfile.mkdtemp(prefix="ca-browser-")
        started = time.monotonic()
        deadline = started + STARTUP_TIMEOUT
        phase = "launch"
        try:
            args = [exe, "--headless=new", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                    f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                    "--disable-extensions", "--disable-background-networking", "--disable-sync",
                    "--disable-component-update", "--disable-default-apps",
                    "--force-color-profile=srgb", f"--window-size={width},{height}", "about:blank"]
            if hide_scrollbars:
                args.insert(1, "--hide-scrollbars")
            if os.environ.get("CA_BROWSER_NO_SANDBOX") == "1":
                args.insert(1, "--no-sandbox")  # CI runners whose kernel forbids the sandbox's namespaces
            self._stderr = tempfile.TemporaryFile()
            # POSIX: its own process group, so helpers that outlive the main process can be stopped
            # before the profile is removed (otherwise they recreate it).
            group = {"start_new_session": True} if os.name == "posix" else {}
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=self._stderr, **group)
            phase = "DevToolsActivePort"
            port = self._wait_for_port(deadline)
            phase = "/json/list"
            ws_url = self._wait_for_page(port, deadline)
            phase = "CDP setup"
            self.ws = WebSocket(ws_url, timeout=max(0.1, min(30.0, deadline - time.monotonic())))
            self.ws.sock.settimeout(30)
            self._id = 0
            self.events = []
            self.call("Page.enable")
            self.call("Runtime.enable")
            self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=width < 760)
            if reduced_motion:
                self.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        except BaseException as error:
            exit_code = self.proc.poll() if self.proc else None
            stderr = self._stderr_tail()
            cleanup = self.close()
            if not isinstance(error, Exception):
                raise  # KeyboardInterrupt and the like, after cleanup
            parts = [f"{phase} failed after {time.monotonic() - started:.1f}s: {_describe(error)}",
                     "browser exit code: " + (str(exit_code) if exit_code is not None else "none (was running; stopped)")]
            if cleanup:
                parts.append("cleanup problems: " + "; ".join(cleanup))
            if stderr:
                parts.append("browser stderr (last lines, sanitized):\n    " + "\n    ".join(stderr))
            raise _AttemptFailed("\n  ".join(parts)) from error

    def _check_alive(self):
        code = self.proc.poll()
        if code is not None:
            raise ConnectionError(f"browser process exited with code {code}")

    def _wait_for_port(self, deadline):
        port_file = Path(self.profile) / "DevToolsActivePort"
        while True:
            self._check_alive()
            try:  # the browser may still be writing (or holding) the file; Windows then denies the read
                port = int(port_file.read_text().split()[0])
                if 0 < port < 65536:
                    return port
            except (OSError, ValueError, IndexError):
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"DevToolsActivePort not written within {STARTUP_TIMEOUT:g}s")
            time.sleep(POLL_INTERVAL)

    def _wait_for_page(self, port, deadline):
        """Poll /json/list until a page target on this port exists. Refused, reset, stalled, partial or
        malformed answers are retried until the deadline; a browser exit ends the wait at once."""
        last = "no answer yet"
        while True:
            self._check_alive()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no DevTools page target within {STARTUP_TIMEOUT:g}s (last: {last})")
            try:
                for target in _list_targets(port, min(REQUEST_TIMEOUT, remaining)):
                    url = target.get("webSocketDebuggerUrl")
                    if target.get("type") == "page" and isinstance(url, str) and url.startswith(f"ws://127.0.0.1:{port}/"):
                        return url
                last = "no page target yet"
            except (OSError, http.client.HTTPException, ValueError) as error:
                last = _describe(error)
            time.sleep(max(0.0, min(POLL_INTERVAL, deadline - time.monotonic())))

    def _stderr_tail(self):
        if not self._stderr:
            return []
        try:
            self._stderr.flush()
            size = self._stderr.seek(0, 2)
            self._stderr.seek(max(0, size - 16384))
            return _sanitize(self._stderr.read(), getattr(self, "profile", None))
        except (OSError, ValueError):
            return []

    def call(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.events.append(msg)

    def navigate(self, url, settle=0.5):
        self.call("Page.navigate", url=url)
        self.wait_for(f"location.href === {json.dumps(url)} && document.readyState === 'complete'")
        time.sleep(settle)

    def js(self, expression, await_promise=True):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in result:
            raise RuntimeError(f"page exception: {result['exceptionDetails'].get('exception', {}).get('description', result['exceptionDetails'])}")
        return result.get("result", {}).get("value")

    def wait_for(self, expression, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(f"Boolean({expression})"):
                return True
            time.sleep(0.05)
        raise TimeoutError(f"timed out waiting for: {expression}")

    def screenshot(self, path):
        data = self.call("Page.captureScreenshot", format="png")["data"]
        Path(path).write_bytes(base64.b64decode(data))

    def console_errors(self):
        out = []
        for e in self.events:
            if e.get("method") == "Runtime.exceptionThrown":
                out.append(e["params"]["exceptionDetails"].get("text", "exception"))
            elif e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error":
                out.append(" ".join(str(a.get("value", a.get("description", ""))) for a in e["params"]["args"]))
        return out

    def close(self):
        """Close the socket, stop the process, drop the stderr log and remove the profile. Every step
        runs even if an earlier one fails; returns the problems (empty when all was cleaned up)."""
        problems = []
        ws, self.ws = getattr(self, "ws", None), None
        if ws:
            try:
                ws.close()
            except Exception as error:
                problems.append(f"socket: {_describe(error)}")
        proc = getattr(self, "proc", None)
        if proc:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(10)
            except Exception as error:
                problems.append(f"terminate: {_describe(error)}")
                try:
                    proc.kill()
                    proc.wait(10)
                except Exception as error2:
                    problems.append(f"kill: {_describe(error2)}")
            if os.name == "posix":
                problems += _stop_group(proc.pid)
        stderr, self._stderr = getattr(self, "_stderr", None), None
        if stderr:
            try:
                stderr.close()
            except Exception as error:
                problems.append(f"stderr log: {_describe(error)}")
        profile = getattr(self, "profile", None)
        if profile:
            for _ in range(40):  # Windows keeps files locked briefly after the process ends
                shutil.rmtree(profile, ignore_errors=True)
                if not os.path.exists(profile):
                    break
                time.sleep(0.05)
            else:
                problems.append("profile directory could not be removed")
        return problems


if __name__ == "__main__":
    print(find_browser() or "none", file=sys.stderr)
