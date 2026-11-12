"""A fake Chromium for the startup-reliability tests (test-only, loopback only).

Accepts the real browser's command line, writes DevToolsActivePort into --user-data-dir and serves
just enough of /json/list and the CDP WebSocket to start a session. The failure modes seen on hosted
runners are reproduced on request:

  --fake-mode=OPTIONS[|OPTIONS...]   one option set per launch (the last repeats), e.g. "hang|ok"
      ok                    behave like a healthy browser
      port_delay=S          write DevToolsActivePort after S seconds
      refuse=S              write the port first, start listening S seconds later (connection refused)
      stall=S               accept /json/list but answer nothing until S seconds after start
      hang                  accept /json/list and never answer
      garbage=N             answer the first N /json/list requests with a truncated, then malformed, body
      empty=S               list no page target for S seconds
      exit_before_port=C    exit with code C before writing the port
      exit_after_port=C     write the port, then exit with code C
      ws_refuse             refuse the WebSocket upgrade
      noisy                 write a DevTools URL, the profile path and control characters to stderr
  --fake-state=DIR          each launch records its argv as DIR/launch-N.json

Exits by itself after two minutes so a leaked fake cannot outlive the test run for long.
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

START = time.monotonic()
SECRET = "0f1e2d3c-SECRET-BROWSER-ID"


def options(argv):
    mode = next((a.split("=", 1)[1] for a in argv if a.startswith("--fake-mode=")), "ok")
    state = Path(next(a.split("=", 1)[1] for a in argv if a.startswith("--fake-state=")))
    state.mkdir(parents=True, exist_ok=True)
    launch = len(list(state.glob("launch-*.json")))
    (state / f"launch-{launch}.json").write_text(json.dumps(argv))
    sets = mode.split("|")
    chosen = sets[min(launch, len(sets) - 1)]
    opts = {}
    for item in chosen.split(","):
        key, _, value = item.partition("=")
        opts[key] = float(value) if value else True
    return opts


def read_head(conn):
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = conn.recv(1)
        if not chunk:
            return None
        head += chunk
    return head.decode("latin-1")


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError
        buf += chunk
    return buf


def serve_ws(conn, opts):
    if opts.get("ws_refuse"):
        conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        return
    conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
    while True:
        b1, b2 = recv_exact(conn, 2)
        n = b2 & 0x7F
        if n == 126:
            n = int.from_bytes(recv_exact(conn, 2), "big")
        elif n == 127:
            n = int.from_bytes(recv_exact(conn, 8), "big")
        mask = recv_exact(conn, 4)
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(recv_exact(conn, n)))
        if b1 & 0x0F == 0x8:
            return
        reply = json.dumps({"id": json.loads(data)["id"], "result": {}}).encode()
        conn.sendall(bytes([0x81, len(reply)]) + reply if len(reply) < 126 else
                     bytes([0x81, 126]) + len(reply).to_bytes(2, "big") + reply)


class Fake:
    def __init__(self, opts, port):
        self.opts, self.port = opts, port
        self.lock = threading.Lock()
        self.garbage_left = int(opts.get("garbage", 0))

    def handle(self, conn):
        try:
            head = read_head(conn)
            if head is None:
                return
            path = head.split(" ", 2)[1]
            if path.startswith("/devtools/page/"):
                serve_ws(conn, self.opts)
                return
            if path != "/json/list":
                conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                return
            if self.opts.get("hang"):
                threading.Event().wait()
            if "stall" in self.opts:
                time.sleep(max(0.0, self.opts["stall"] - (time.monotonic() - START)))
            with self.lock:
                garbage = self.garbage_left
                self.garbage_left -= 1
            if garbage == 2 or (garbage == 1 and self.opts.get("garbage") == 1):
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 400\r\n\r\n[{\"type\": \"pa")
                return  # closes mid-body: an incomplete read
            if garbage == 1:
                body = b"<html>not json</html>"
            elif time.monotonic() - START < self.opts.get("empty", 0):
                body = b"[]"
            else:
                body = json.dumps([
                    {"type": "service_worker", "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/SW"},
                    {"type": "page", "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/PAGE1"},
                ]).encode()
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
        except OSError:
            pass
        finally:
            conn.close()


def main():
    argv = sys.argv[1:]
    watchdog = threading.Timer(120, lambda: os._exit(70))
    watchdog.daemon = True
    watchdog.start()
    opts = options(argv)
    profile = Path(next(a.split("=", 1)[1] for a in argv if a.startswith("--user-data-dir=")))
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    if opts.get("noisy"):
        sys.stderr.write(f"DevTools listening on ws://127.0.0.1:{port}/devtools/browser/{SECRET}\n")
        sys.stderr.write(f"[0101/000000.000:ERROR:fake] cannot lock {profile}{os.sep}SingletonLock \x1b[31mred\x07\n")
        sys.stderr.flush()
    time.sleep(opts.get("port_delay", 0))
    if "exit_before_port" in opts:
        sys.exit(int(opts["exit_before_port"]))
    if "refuse" in opts:
        sock.close()
    (profile / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/{SECRET}\n")
    if "exit_after_port" in opts:
        time.sleep(0.2)
        sys.exit(int(opts["exit_after_port"]))
    if "refuse" in opts:
        time.sleep(opts["refuse"])
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
    sock.listen(16)
    fake = Fake(opts, port)
    while True:
        conn, _ = sock.accept()
        threading.Thread(target=fake.handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
