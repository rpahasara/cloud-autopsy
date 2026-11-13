"""A scriptable fake Kubernetes API with watch (test-only, CA-P2-004f).

One global revision counter, as etcd has. Objects come from ``_fake_api.planted_items()`` (sensitive
values planted everywhere). ``mutate``/``rollout``/``delete`` append to a history that watches replay
in order; bookmarks report the current revision on a cadence. Probes (``?limit=1``) return the current
revision and a planted continue token that must never be kept.

Served in-process (``get``/``open_stream``, the transport interface the collector uses) or over
loopback TLS (``WatchTlsServer``).

Faults, per resource (``faults[resource]``):
  deny_watch            every watch request answers 403
  deny_watch_after      watch requests after this many succeed answer 403 (a revoked binding)
  gone_on_resume        a resume (a watch not from the list's resourceVersion) answers 410
  error_410_after: n    after n events the stream sends an ERROR (410) with a planted message
  eof_after: n          after n lines the stream ends (once)
  eof_every: n          every watch ends cleanly after n lines (a short server timeoutSeconds)
  garbage_after: n      after n lines the stream sends a line that is not JSON
  oversize_after: n     after n lines the stream sends a line larger than any bound
  regress_after: n      after n lines the stream sends an event with an older resourceVersion
  foreign_after: n      after n lines the stream sends an object from another namespace
  no_bookmarks          no bookmarks at all
  list_status: code     every list request answers ``code``
  probe_status: code    every probe answers ``code``
"""

import copy
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

import _fake_api as F

from cloud_autopsy.collector import client as cl

START_RV = 5000
KINDS = {"pods": ("v1", "PodList", "Pod"), "deployments": ("apps/v1", "DeploymentList", "Deployment"),
         "replicasets": ("apps/v1", "ReplicaSetList", "ReplicaSet"), "events": ("v1", "EventList", "Event")}
PLANTED_TOKEN = "STOLEN-TOKEN-AFTER-410"


class FakeCluster:
    def __init__(self, faults=None, bookmark_interval=0.05):
        self.cond = threading.Condition()
        self.rev = START_RV
        self.objects = {r: {} for r in KINDS}
        for resource, items in F.planted_items().items():
            for item in items:
                self.rev += 1
                item["metadata"]["resourceVersion"] = str(self.rev)
                self.objects[resource][item["metadata"]["uid"]] = item
        self.history = []          # (rev, resource, type, object)
        self.faults = faults or {}
        self.bookmark_interval = bookmark_interval
        self.watch_opens = {r: 0 for r in KINDS}
        self.requests = []

    # ----------------------------------------------------------------------- mutations
    def _record(self, resource, kind, obj):
        with self.cond:
            self.rev += 1
            obj = copy.deepcopy(obj)
            obj["metadata"]["resourceVersion"] = str(self.rev)
            if kind == "DELETED":
                self.objects[resource].pop(obj["metadata"]["uid"], None)
            else:
                self.objects[resource][obj["metadata"]["uid"]] = obj
            self.history.append((self.rev, resource, kind, obj))
            self.cond.notify_all()
            return self.rev

    def touch(self, resource, n=0):
        """MODIFIED: a status-like change of the n-th object."""
        uid = sorted(self.objects[resource])[n % len(self.objects[resource])]
        obj = copy.deepcopy(self.objects[resource][uid])
        if resource == "pods":
            for s in obj.get("status", {}).get("containerStatuses", []):
                s["restartCount"] = s.get("restartCount", 0) + 1
        elif resource == "events":
            obj["count"] = obj.get("count", 1) + 1
        return self._record(resource, "MODIFIED", obj)

    def add_event(self, name, reason="BackOff", involved="Pod", involved_name="checkout-api-6d4b5-a1"):
        obj = {"metadata": {"name": name, "namespace": F.NAMESPACE, "uid": f"uid-{name}",
                            "creationTimestamp": "2026-11-12T10:00:00Z"},
               "involvedObject": {"kind": involved, "name": involved_name, "namespace": F.NAMESPACE},
               "type": "Warning", "reason": reason, "message": "PLANTED-EVENT-MESSAGE-3fa",
               "lastTimestamp": "2026-11-12T10:00:00Z", "count": 1}
        return self._record("events", "ADDED", obj)

    def delete(self, resource, n=0):
        uid = sorted(self.objects[resource])[n % len(self.objects[resource])]
        return self._record(resource, "DELETED", self.objects[resource][uid])

    # ------------------------------------------------------------------------- reads
    def get(self, path):
        parts = urlsplit(path)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.requests.append(path)
        if parts.path not in F.PATHS:
            return 404, b"{}"
        resource = F.PATHS[parts.path][0]
        fault = self.faults.get(resource, {})
        probe = query.get("limit") == "1"
        status = fault.get("probe_status" if probe else "list_status")
        if status:
            return status, json.dumps({"kind": "Status", "code": status,
                                       "message": "PLANTED-STATUS-MESSAGE-5e8"}).encode()
        api_version, list_kind, _ = KINDS[resource]
        with self.cond:
            items = [copy.deepcopy(o) for _, o in sorted(self.objects[resource].items())]
            meta = {"resourceVersion": str(self.rev)}
        if probe:
            meta["continue"] = PLANTED_TOKEN
            meta["remainingItemCount"] = max(1, len(items) - 1)
            items = items[:1]
        return 200, json.dumps({"apiVersion": api_version, "kind": list_kind, "metadata": meta,
                                "items": items}).encode()

    def open_stream(self, path, idle_timeout):
        parts = urlsplit(path)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.requests.append(path)
        resource = F.PATHS[parts.path][0]
        fault = self.faults.get(resource, {})
        assert query.get("watch") == "1" and query.get("allowWatchBookmarks") == "true", "only allowlisted watches"
        from_rv = int(query["resourceVersion"])
        self.watch_opens[resource] += 1
        if fault.get("deny_watch") or (fault.get("deny_watch_after") is not None
                                       and self.watch_opens[resource] > fault["deny_watch_after"]):
            return 403, None
        if fault.get("gone_on_resume") and self.watch_opens[resource] > 1:
            fault.pop("gone_on_resume")
            return 410, None
        return 200, FakeStream(self, resource, from_rv, idle_timeout, fault)


class FakeStream:
    def __init__(self, cluster, resource, from_rv, idle_timeout, fault):
        self.cluster, self.resource, self.position = cluster, resource, from_rv
        self.idle_timeout, self.fault = idle_timeout, fault
        self.sent = 0
        self.closed = False
        self.last_bookmark = time.monotonic()

    def _line(self, doc):
        self.sent += 1
        return (json.dumps(doc) + "\n").encode()

    def _injected(self, limit):
        f, n = self.fault, self.sent
        if f.get("eof_after") is not None and n >= f["eof_after"]:
            f.pop("eof_after")
            return b""
        if f.get("crash_after") is not None and n >= f["crash_after"]:
            raise AttributeError("'NoneType' object has no attribute 'close'")  # as http.client did on kind
        if f.get("eof_every") and n >= f["eof_every"]:
            return b""  # the server ends every watch after this many lines (like timeoutSeconds)
        if f.get("garbage_after") is not None and n >= f["garbage_after"]:
            return self._line_raw(b"this is not json PLANTED-STATUS-MESSAGE-5e8\n")
        if f.get("oversize_after") is not None and n >= f["oversize_after"]:
            return b"{" + b" " * (limit + 10)  # longer than the bound; readline(limit) cuts it
        if f.get("error_410_after") is not None and n >= f["error_410_after"]:
            f.pop("error_410_after")
            return self._line({"type": "ERROR", "object": {"kind": "Status", "code": 410, "reason": "Expired",
                                                           "message": "PLANTED-STATUS-MESSAGE-5e8"}})
        if f.get("regress_after") is not None and n >= f["regress_after"]:
            obj = copy.deepcopy(next(iter(self.cluster.objects[self.resource].values())))
            obj["metadata"]["resourceVersion"] = "1"
            return self._line({"type": "MODIFIED", "object": obj})
        if f.get("foreign_after") is not None and n >= f["foreign_after"]:
            obj = copy.deepcopy(next(iter(self.cluster.objects[self.resource].values())))
            obj["metadata"]["namespace"] = "ca-other"
            obj["metadata"]["resourceVersion"] = str(self.cluster.rev + 100)
            return self._line({"type": "MODIFIED", "object": obj})
        return None

    def _line_raw(self, data):
        self.sent += 1
        return data

    def readline(self, limit):
        deadline = time.monotonic() + self.idle_timeout
        with self.cluster.cond:
            while True:
                if self.closed:
                    raise cl.CollectorError("unavailable")
                injected = self._injected(limit)
                if injected is not None:
                    return injected[:limit]
                for rev, resource, kind, obj in self.cluster.history:
                    if resource == self.resource and rev > self.position:
                        self.position = rev
                        return self._line({"type": kind, "object": obj})[:limit]
                now = time.monotonic()
                if not self.fault.get("no_bookmarks") and now - self.last_bookmark >= self.cluster.bookmark_interval:
                    self.last_bookmark = now
                    if self.cluster.rev >= self.position:
                        self.position = self.cluster.rev
                        _, _, kind = KINDS[self.resource]
                        return self._line({"type": "BOOKMARK", "object": {
                            "kind": kind, "metadata": {"resourceVersion": str(self.cluster.rev),
                                                       "annotations": {"k8s.io/initial-events-end": "true"}}}})[:limit]
                if now >= deadline:
                    raise cl.CollectorError("timeout")
                self.cluster.cond.wait(min(0.02, deadline - now))

    def close(self):
        with self.cluster.cond:
            self.closed = True
            self.cluster.cond.notify_all()


class Mutator:
    """Applies ``steps`` (callables) every ``interval`` seconds on a thread, then stops."""

    def __init__(self, steps, interval=0.15, delay=0.3):
        self.steps, self.interval, self.delay = list(steps), interval, delay
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        time.sleep(self.delay)
        for step in self.steps:
            step()
            time.sleep(self.interval)

    def start(self):
        self.thread.start()
        return self


class WatchTlsServer:
    """``FakeCluster`` behind a real loopback HTTPS server, with streaming watch responses."""

    def __init__(self, cluster, cert, key):
        fake = cluster

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):  # noqa: N802
                if self.headers.get("Authorization") != "Bearer synthetic-test-token-0000000000000000000000":
                    self.send_response(401)
                    self.end_headers()
                    return
                if "watch=1" not in self.path:
                    status, body = fake.get(self.path)
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                status, stream = fake.open_stream(self.path, 0.5)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if stream is None:
                    return
                try:
                    while True:
                        try:
                            line = stream.readline(2_000_000)
                        except cl.CollectorError:
                            return
                        if not line:
                            return
                        self.wfile.write(line)
                        self.wfile.flush()
                except OSError:
                    return
                finally:
                    stream.close()

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
