"""Loopback-only HTTP transport for ``ApiService`` (standard library ``http.server``).

The bind address is fixed to 127.0.0.1; any other host is refused. Every response closes the
connection, sockets time out, and the server banner carries no version.

Access log (PR #24 review): one line per request with a method from a fixed list, a fixed
route template (for example ``/v1/runs/{run_id}/result``) or ``<rejected>``, and the status.
Nothing user-supplied is ever written: no raw path, query string, run or evidence ID, header
(so no token), request line or error detail. An unexpected exception while handling a request
is answered with a bare ``500 {"error": "internal_error"}`` and logged by exception class only;
it is not hidden.
"""

import http.server
import sys

from .service import SECURITY_HEADERS, Response, canonical

LOOPBACK = "127.0.0.1"
REQUEST_TIMEOUT_SECONDS = 10
_INTERNAL_ERROR = Response(500, canonical.canonical_bytes({"error": "internal_error"}), SECURITY_HEADERS)


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ca-api"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT_SECONDS

    def version_string(self):
        return "ca-api"

    def _dispatch(self):
        service = self.server.service
        self._logged_route = service.route_template(self.command, self.path)
        header_bytes = sum(len(k) + len(v) + 4 for k, v in self.headers.items())
        self._discard_small_body()
        try:
            response = service.handle(self.command, self.path, self.headers, header_bytes)
        except Exception as exc:  # noqa: BLE001 -- answered and logged, never silently swallowed
            self.server.log_line(f"api internal_error {type(exc).__name__}")
            response = _INTERNAL_ERROR
        self.send_response(response.status)
        for name, value in response.headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)
        self.close_connection = True

    def _discard_small_body(self):
        """Every body is refused, but reading a small declared one first lets the refusal reach
        the client instead of a connection reset. Bounded: at most 64 KiB, under the socket timeout."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < length <= 65_536:
            try:
                self.rfile.read(length)
            except OSError:
                pass

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = _dispatch

    def send_error(self, code, message=None, explain=None):
        """Errors raised by the standard library's request parsing (malformed request line, an
        over-long line, too many headers, an unsupported method): a JSON code, never the
        default HTML page that echoes the request line back."""
        self._logged_route = ("-", "<rejected>")
        self.request_version = "HTTP/1.1"  # always answer with a status line and headers
        body = canonical.canonical_bytes({"error": f"http_{int(code)}"})
        self.close_connection = True
        self.send_response(code)
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if getattr(self, "command", None) != "HEAD":
            self.wfile.write(body)

    def log_request(self, code="-", size="-"):
        method, route = getattr(self, "_logged_route", ("-", "<rejected>"))
        status = int(code) if isinstance(code, int) else "-"
        self.server.log_line(f"api {method} {route} {status}")

    def log_error(self, format, *args):  # noqa: A002 -- would echo the raw request line; status is logged instead
        pass

    def log_message(self, format, *args):  # noqa: A002
        pass


class LoopbackServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, service, port=0, host=LOOPBACK, quiet=False, log=None):
        if host != LOOPBACK:
            raise ValueError("the local API binds to 127.0.0.1 only")
        self.service, self.quiet, self.log = service, quiet, log
        if getattr(service, "log", False) is None:
            service.log = self.log_line  # the service's safe per-item diagnostics share this log
        super().__init__((LOOPBACK, int(port)), _Handler)

    def log_line(self, line):
        if not self.quiet:
            (self.log or sys.stderr).write(line + "\n")

    def handle_error(self, request, client_address):
        # socketserver would print a traceback with exception details; record the class only.
        self.log_line(f"api connection_error {type(sys.exc_info()[1]).__name__}")

    @property
    def port(self):
        return self.server_address[1]
