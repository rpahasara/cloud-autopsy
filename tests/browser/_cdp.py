"""A minimal Chrome DevTools Protocol client on the Python standard library (test-only).

Launches a locally installed Chromium-family browser (Chrome, Chromium or Edge) headless with a
fresh temporary profile and remote debugging on 127.0.0.1, then speaks CDP over a small
RFC 6455 WebSocket client. No third-party package is involved; nothing leaves the machine.
"""

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CANDIDATES = (
    os.environ.get("CA_BROWSER", ""),
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def find_browser():
    for name in CANDIDATES:
        if not name:
            continue
        path = shutil.which(name) or (name if Path(name).is_file() else None)
        if path:
            return path
    return None


class WebSocket:
    def __init__(self, url, timeout=30):
        assert url.startswith("ws://127.0.0.1:"), "CDP is used on loopback only"
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
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

    def __init__(self, width=1440, height=900, reduced_motion=False):
        exe = find_browser()
        if not exe:
            raise RuntimeError("no Chromium-family browser found (set CA_BROWSER)")
        self.profile = tempfile.mkdtemp(prefix="ca-browser-")
        args = [exe, "--headless=new", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--disable-component-update", "--disable-default-apps", "--hide-scrollbars",
                "--force-color-profile=srgb", f"--window-size={width},{height}", "about:blank"]
        if os.environ.get("CA_BROWSER_NO_SANDBOX") == "1":
            args.insert(1, "--no-sandbox")  # CI runners whose kernel forbids the sandbox's namespaces
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(self.profile) / "DevToolsActivePort"
        deadline = time.time() + 30
        while not port_file.exists() or not port_file.read_text().strip():
            if time.time() > deadline or self.proc.poll() is not None:
                self.close()
                raise RuntimeError("browser did not start")
            time.sleep(0.1)
        port = int(port_file.read_text().split()[0])
        for _ in range(100):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                pages = [t for t in json.load(r) if t.get("type") == "page"]
            if pages:
                break
            time.sleep(0.1)
        self.ws = WebSocket(pages[0]["webSocketDebuggerUrl"])
        self._id = 0
        self.events = []
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=width < 760)
        if reduced_motion:
            self.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])

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
        deadline = time.time() + timeout
        while time.time() < deadline:
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
        if getattr(self, "ws", None):
            self.ws.close()
        if getattr(self, "proc", None) and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


if __name__ == "__main__":
    print(find_browser() or "none", file=sys.stderr)
