"""Allowlisted, read-only HTTPS client and paginated list collection (CA-P2-004e).

Requests are built only from fixed templates: four namespaced list paths, with ``limit`` and an
opaque ``continue`` token as the only query parameters, method GET only. Everything else is
refused before a byte is sent. TLS is verified against the configured cluster CA with hostname
checking; there are no proxies, redirects, kubeconfig files, plugins or environment lookups.

Errors carry a fixed code and the HTTP status only: response bodies (including Kubernetes Status
messages, which can quote request data), tokens and continue tokens are never put into an
exception, a log line or a report.

A list collection (``collect_list``):
- every page must report the same *collection-level* ``metadata.resourceVersion``; otherwise every
  page is discarded (``rv_changed``). Item resourceVersions play no part in this;
- continue tokens are opaque: bounded, free of control characters, URL-encoded as one value, used
  only within the same attempt, never stored;
- after HTTP 410 (an expired continue token) the attempt's pages and token, and any token in the
  410 body, are discarded and the list restarts from the beginning, at most ``max_restarts`` times;
- ``max_pages`` bounds an attempt; a remaining token then makes the result ``truncated``;
- client wall-clock times of the attempt's first request and last response, and its monotonic
  elapsed time, are recorded. They are client facts only: nothing places the collection at an
  API-server instant.

CA-P2-004f adds, for the watch collector only:
- ``build_watch_path``: the same four namespaced paths with exactly ``watch=1``, a decimal
  ``resourceVersion`` (F3 rule), ``allowWatchBookmarks=true`` and ``timeoutSeconds`` (1..600);
- ``HttpsTransport.open_stream``: a GET whose body is read line by line under a size bound; a
  non-200 body is discarded unread beyond a small bound and never surfaced;
- ``collect_list(..., clock_ns=...)``: the send time of the first request, and the receipt times of
  the first and last pages, on the collector's session clock.
"""

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

from ..contracts import canonical
from ..contracts import resourceversion as rv
from ..contracts.errors import ContractError
from ..contracts.sources import NAMESPACE
from . import project

LIST_PATHS = {
    "pods": ("/api/v1/namespaces/{ns}/pods", "v1", "PodList"),
    "deployments": ("/apis/apps/v1/namespaces/{ns}/deployments", "apps/v1", "DeploymentList"),
    "replicasets": ("/apis/apps/v1/namespaces/{ns}/replicasets", "apps/v1", "ReplicaSetList"),
    "events": ("/api/v1/namespaces/{ns}/events", "v1", "EventList"),
}
MAX_PAGE_BYTES = canonical.CEILING_BYTES
MAX_TOKEN_CHARS = 8192
MAX_RV_CHARS = 256
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
USER_AGENT = "cloud-autopsy-collector/0.1"
OUTCOMES = ("consistent", "truncated", "rv_changed", "expired", "denied", "rate_limited", "timeout", "unavailable",
            "invalid")


class CollectorError(Exception):
    """A refused request or a failed response. ``code`` is fixed; ``status`` is the HTTP status or None."""

    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code if status is None else f"{code} (HTTP {status})")


def _printable(text, max_len):
    return isinstance(text, str) and 0 < len(text) <= max_len and all(0x20 <= ord(c) < 0x7f for c in text)


def build_path(resource, namespace, limit, continue_token=None):
    """The only request paths this collector can form."""
    if resource not in LIST_PATHS:
        raise CollectorError("resource_not_allowed")
    if not isinstance(namespace, str) or not NAMESPACE.fullmatch(namespace):
        raise CollectorError("namespace_invalid")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise CollectorError("limit_invalid")
    path = LIST_PATHS[resource][0].format(ns=namespace) + f"?limit={limit}"
    if continue_token is not None:
        if not _printable(continue_token, MAX_TOKEN_CHARS):
            raise CollectorError("continue_token_invalid")
        path += "&continue=" + quote(continue_token, safe="")
    return path


def build_watch_path(resource, namespace, resource_version, timeout_seconds):
    """The only watch paths this collector can form (CA-P2-004f)."""
    if resource not in LIST_PATHS:
        raise CollectorError("resource_not_allowed")
    if not isinstance(namespace, str) or not NAMESPACE.fullmatch(namespace):
        raise CollectorError("namespace_invalid")
    if not rv.is_valid(resource_version):
        raise CollectorError("resource_version_invalid")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise CollectorError("timeout_invalid")
    return (LIST_PATHS[resource][0].format(ns=namespace) + f"?watch=1&resourceVersion={resource_version}"
            f"&allowWatchBookmarks=true&timeoutSeconds={timeout_seconds}")


class Stream:
    """An open watch response. ``readline(limit)`` returns bytes ('' at the end of the stream)."""

    def __init__(self, connection, response):
        self._con, self._response = connection, response

    def readline(self, limit):
        try:
            return self._response.readline(limit)
        except (socket.timeout, TimeoutError):
            raise CollectorError("timeout") from None
        except (ssl.SSLError, ConnectionError, OSError, ValueError, http.client.HTTPException):
            raise CollectorError("unavailable") from None
        except Exception:  # noqa: BLE001 -- seen on kind: http.client's chunked reader raised AttributeError
            # when the API server restarted mid-chunk. Any failure while reading is "unavailable".
            raise CollectorError("unavailable") from None

    def close(self):
        """Close from any thread: unblocks a pending ``readline``."""
        try:
            sock = self._con.sock
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._con.close()
        except OSError:
            pass


def check_server(server):
    """(host, port) of an ``https`` API server on the loopback interface only (synthetic, local ``kind``)."""
    parts = urlsplit(server) if isinstance(server, str) else None
    if parts is None or parts.scheme != "https" or parts.path not in ("", "/") or parts.query or parts.fragment \
            or parts.username or parts.password or not parts.hostname:
        raise CollectorError("server_invalid")
    host = parts.hostname
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise CollectorError("server_not_loopback")
    try:
        port = parts.port or 443
    except ValueError:
        raise CollectorError("server_invalid") from None
    return host, port


class HttpsTransport:
    """GET over verified TLS to a loopback API server. ``get(path) -> (status, body bytes)``."""

    def __init__(self, server, ca_file, token_file, timeout=10.0):
        self.host, self.port = check_server(server)
        try:
            self._context = ssl.create_default_context(cafile=str(Path(ca_file)))
            token = Path(token_file).read_text(encoding="ascii").strip()
        except (OSError, ssl.SSLError, UnicodeError):
            raise CollectorError("credentials_unreadable") from None
        if not _printable(token, 16_384):
            raise CollectorError("credentials_unreadable")
        self._context.check_hostname = True
        self._context.verify_mode = ssl.CERT_REQUIRED
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._token = token
        self.timeout = timeout

    def __repr__(self):  # never shows the token
        return f"HttpsTransport({self.host}:{self.port})"

    def get(self, path):
        if not isinstance(path, str) or not path.startswith("/") or not _printable(path, 9000):
            raise CollectorError("path_invalid")
        con = http.client.HTTPSConnection(self.host, self.port, context=self._context, timeout=self.timeout)
        try:
            con.request("GET", path, headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json",
                                              "User-Agent": USER_AGENT})
            response = con.getresponse()
            body = response.read(MAX_PAGE_BYTES + 1)
            return response.status, body
        except (socket.timeout, TimeoutError):
            raise CollectorError("timeout") from None
        except (ssl.SSLError, ConnectionError, OSError, http.client.HTTPException):
            raise CollectorError("unavailable") from None
        finally:
            con.close()

    def open_stream(self, path, idle_timeout):
        """(status, Stream or None). Non-200 bodies are discarded; nothing of them is returned."""
        if not isinstance(path, str) or not path.startswith("/") or not _printable(path, 9000):
            raise CollectorError("path_invalid")
        con = http.client.HTTPSConnection(self.host, self.port, context=self._context, timeout=idle_timeout)
        try:
            con.request("GET", path, headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json",
                                              "User-Agent": USER_AGENT})
            response = con.getresponse()
        except (socket.timeout, TimeoutError):
            con.close()
            raise CollectorError("timeout") from None
        except (ssl.SSLError, ConnectionError, OSError, http.client.HTTPException):
            con.close()
            raise CollectorError("unavailable") from None
        if response.status != 200:
            try:
                response.read(65_536)
            except (OSError, http.client.HTTPException):
                pass
            con.close()
            return response.status, None
        return 200, Stream(con, response)


def _wall_ms():
    return time.time_ns() // 1_000_000


@dataclass
class Collection:
    resource: str
    outcome: str
    http_status: object = None
    items: list = field(default_factory=list)       # projected items only
    collection_resource_version: object = None
    pages: int = 0
    restarts: int = 0
    first_request_ms: object = None                  # client wall clock
    last_response_ms: object = None
    elapsed_ms: object = None                        # client monotonic
    remaining_item_count: object = None
    error: object = None                             # a fixed code
    counts: dict = field(default_factory=dict)       # withheld / dropped counts from the projection
    first_request_ns: object = None                  # CA-P2-004f session clock (only with clock_ns)
    first_page_ns: object = None
    last_response_ns: object = None


def _failure(status):
    if status in (401, 403):
        return "denied"
    if status == 429:
        return "rate_limited"
    if status in (400, 404, 405, 406, 415, 422):
        return "invalid"
    return "unavailable"


def collect_list(transport, resource, namespace, page_limit=100, max_pages=20, max_restarts=1,
                 wall_ms=_wall_ms, monotonic=time.monotonic, clock_ns=None):
    """List one resource collection; never raises for a server or transport failure."""
    if resource not in LIST_PATHS:
        raise CollectorError("resource_not_allowed")
    _, api_version, list_kind = LIST_PATHS[resource]
    restarts = 0
    while True:
        result = Collection(resource, "consistent", restarts=restarts)
        token, rv, seen = None, None, set()
        result.first_request_ms, started = wall_ms(), monotonic()
        if clock_ns:
            result.first_request_ns = clock_ns()
        expired = False
        while True:
            if result.pages == max_pages:
                result.outcome = "truncated"
                break
            try:
                status, body = transport.get(build_path(resource, namespace, page_limit, token))
            except CollectorError as exc:
                result.outcome, result.error = ("timeout" if exc.code == "timeout" else "unavailable"), exc.code
                break
            finally:
                result.last_response_ms = wall_ms()
                if clock_ns:
                    result.last_response_ns = clock_ns()
            if clock_ns and result.first_page_ns is None:
                result.first_page_ns = result.last_response_ns
            result.http_status = status
            if status == 410:
                expired = True  # this attempt's token and pages are discarded; nothing from the 410 body is used
                break
            if status != 200:
                result.outcome, result.error = _failure(status), f"http_{status}"
                break
            if len(body) > MAX_PAGE_BYTES:
                result.outcome, result.error = "invalid", "page_too_large"
                break
            try:
                page = canonical.loads(body, canonical.Limits(max_bytes=MAX_PAGE_BYTES))
            except ContractError:
                result.outcome, result.error = "invalid", "body_not_strict_json"
                break
            meta = page.get("metadata") if isinstance(page, dict) else None
            items = page.get("items") if isinstance(page, dict) else None
            if not isinstance(page, dict) or page.get("kind") != list_kind or page.get("apiVersion") != api_version \
                    or not isinstance(meta, dict) or not isinstance(items, list):
                result.outcome, result.error = "invalid", "list_shape_invalid"
                break
            page_rv = meta.get("resourceVersion")
            if not _printable(page_rv, MAX_RV_CHARS):
                result.outcome, result.error = "invalid", "collection_rv_missing"
                break
            if rv is None:
                rv = page_rv
            elif page_rv != rv:  # the collection-level RV changed: not one consistent collection
                result.outcome, result.error = "rv_changed", "collection_rv_changed"
                break
            result.pages += 1
            duplicate = False
            for item in items:
                uid = item.get("metadata", {}).get("uid") if isinstance(item, dict) and isinstance(item.get("metadata"), dict) else None
                if uid is not None and uid in seen:
                    duplicate = True
                seen.add(uid)
                projected = project.project(resource, item, result.counts)  # the raw item is not kept
                if projected is not None:
                    result.items.append(projected)
            if duplicate:
                result.outcome, result.error = "invalid", "item_duplicate"
                break
            remaining = meta.get("remainingItemCount")
            result.remaining_item_count = remaining if type(remaining) is int and remaining > 0 else None
            next_token = meta.get("continue")
            if next_token in (None, ""):
                break
            if not _printable(next_token, MAX_TOKEN_CHARS):
                result.outcome, result.error = "invalid", "continue_token_invalid"
                break
            token = next_token
        result.elapsed_ms = int((monotonic() - started) * 1000)
        if expired:
            if restarts < max_restarts:
                restarts += 1
                continue  # restart from the beginning: no continue parameter, nothing carried over
            result.outcome, result.error = "expired", "list_expired"
        if result.outcome in ("consistent", "truncated"):
            result.collection_resource_version = rv
            if result.outcome == "consistent":
                result.remaining_item_count = None
        else:
            result.items, result.collection_resource_version = [], None
        return result
