"""Loopback-only HTTP transport for ``ApiService`` (standard library ``http.server``).

The bind address is fixed to 127.0.0.1; any other host is refused. Every response closes the
connection, sockets time out, the server banner carries no version, and the access log records
method, path and status only (never headers, so never tokens).
"""

import http.server
import sys

from .service import MAX_PATH

LOOPBACK = "127.0.0.1"
REQUEST_TIMEOUT_SECONDS = 10


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ca-api"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT_SECONDS

    def version_string(self):
        return "ca-api"

    def _dispatch(self):
        header_bytes = sum(len(k) + len(v) + 4 for k, v in self.headers.items())
        response = self.server.service.handle(self.command, self.path, self.headers, header_bytes)
        self.send_response(response.status)
        for name, value in response.headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)
        self.close_connection = True

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = _dispatch

    def log_message(self, format, *args):  # noqa: A002 -- signature fixed by the base class
        if self.server.quiet:
            return
        status = args[1] if len(args) > 1 else ""
        sys.stderr.write(f"api {getattr(self, 'command', '-')} {getattr(self, 'path', '-')[:MAX_PATH]} {status}\n")


class LoopbackServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, service, port=0, host=LOOPBACK, quiet=False):
        if host != LOOPBACK:
            raise ValueError("the local API binds to 127.0.0.1 only")
        self.service, self.quiet = service, quiet
        super().__init__((LOOPBACK, int(port)), _Handler)

    @property
    def port(self):
        return self.server_address[1]
