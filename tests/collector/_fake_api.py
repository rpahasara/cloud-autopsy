"""A scriptable fake Kubernetes API (test-only): synthetic lists with planted sensitive values and
injectable faults, served in-process (``FakeApi.get``) or over loopback TLS (``TlsServer``).

Planted values must never appear in anything the collector writes, raises or logs.
"""

import base64
import copy
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.synthetic import k8s_recordings as R  # noqa: E402

NAMESPACE = "ca-demo"
PLANTED = ("PLANTED-ENV-VALUE-7c1", "PLANTED-ANNOTATION-91d", "PLANTED-EVENT-MESSAGE-3fa", "planted-secret-name-0b2",
           "PLANTED-STATUS-MESSAGE-5e8", "PLANTED-CONFIG-VALUE-c44", "PLANTED-COMMAND-a90", "STOLEN-TOKEN-AFTER-410")
PATHS = {"/api/v1/namespaces/ca-demo/pods": ("pods", "v1", "PodList"),
         "/apis/apps/v1/namespaces/ca-demo/deployments": ("deployments", "apps/v1", "DeploymentList"),
         "/apis/apps/v1/namespaces/ca-demo/replicasets": ("replicasets", "apps/v1", "ReplicaSetList"),
         "/api/v1/namespaces/ca-demo/events": ("events", "v1", "EventList")}


def planted_items():
    """The scenario objects of the synthetic recordings, with sensitive fields planted everywhere."""
    bodies = R.bodies()
    items = {r: copy.deepcopy(bodies[r]["items"]) for r in ("pods", "replicasets", "deployments", "events")}
    for resource in ("pods", "replicasets", "deployments"):
        for item in items[resource]:
            item["metadata"].setdefault("annotations", {})["kubectl.kubernetes.io/last-applied-configuration"] = \
                json.dumps({"env": "PLANTED-ANNOTATION-91d", "data": "PLANTED-CONFIG-VALUE-c44"})
            item["metadata"]["managedFields"] = [{"manager": "kubectl", "fieldsV1": {"f:PLANTED-ANNOTATION-91d": {}}}]
            spec = item["spec"]["template"]["spec"] if "template" in item.get("spec", {}) else item["spec"]
            for c in spec.get("containers", []):
                c.setdefault("env", []).append({"name": "API_KEY", "value": "PLANTED-ENV-VALUE-7c1"})
                c["command"] = ["/bin/app", "--password=PLANTED-COMMAND-a90"]
                c.setdefault("envFrom", []).append({"secretRef": {"name": "planted-secret-name-0b2"}})
            spec.setdefault("volumes", []).append({"name": "creds", "secret": {"secretName": "planted-secret-name-0b2"}})
    for event in items["events"]:
        event["message"] = "PLANTED-EVENT-MESSAGE-3fa"
        event["note"] = "PLANTED-EVENT-MESSAGE-3fa"
    items["events"].append({"metadata": {"name": "planted-secret-name-0b2.1", "namespace": NAMESPACE,
                                         "uid": "0b8e7c1e-0000-4000-8000-0000000e0099", "resourceVersion": "2299",
                                         "creationTimestamp": "2026-10-15T08:12:00Z"},
                            "involvedObject": {"kind": "Secret", "name": "planted-secret-name-0b2", "namespace": NAMESPACE},
                            "type": "Warning", "reason": "FailedMount", "message": "PLANTED-EVENT-MESSAGE-3fa",
                            "lastTimestamp": "2026-10-15T08:12:00Z", "count": 1})
    return items


class FakeApi:
    """Lists served in pages of ``limit``. Faults (per resource) are a dict of:
      status: int                 answer every request with this status (body: a Status with a planted message)
      rv_change_on_page: n        page n reports a different collection resourceVersion
      gone_on_page: n             page n answers 410 (with a planted token); ``gone_times`` limits how often
      item_rv_drift: True         item resourceVersions differ from the collection RV (must not matter)
      raw: bytes                  answer with these bytes
      duplicate: True             repeat the first item on the last page
    """

    def __init__(self, items=None, faults=None, collection_rvs=None):
        self.items = items if items is not None else planted_items()
        self.faults = faults or {}
        self.rvs = collection_rvs or {"pods": "3101", "deployments": "3102", "replicasets": "3103", "events": "3104"}
        self.requests = []           # (path without query, query dict) as received
        self.issued = {}             # token -> (resource, attempt, next offset)
        self.attempts = {r: 0 for r in self.rvs}
        self.gone = {r: 0 for r in self.rvs}
        self.lock = threading.Lock()

    def _token(self, resource, attempt, offset):
        raw = f"{resource}|{attempt}|{offset}|+/=&%? :".encode()
        token = base64.b64encode(raw).decode() + "+/=&%? :" + str(len(self.issued))
        self.issued[token] = (resource, attempt, offset)
        return token

    def _status_body(self, code):
        return json.dumps({"kind": "Status", "apiVersion": "v1", "status": "Failure", "code": code,
                           "message": "PLANTED-STATUS-MESSAGE-5e8 PLANTED-ENV-VALUE-7c1", "reason": "Forbidden"}).encode()

    def get(self, path):
        with self.lock:
            return self._get(path)

    def _get(self, path):
        parts = urlsplit(path)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.requests.append((parts.path, query, path))
        if parts.path not in PATHS:
            return 404, self._status_body(404)
        resource, api_version, kind = PATHS[parts.path]
        fault = self.faults.get(resource, {})
        if "status" in fault:
            return fault["status"], self._status_body(fault["status"])
        if "raw" in fault:
            return 200, fault["raw"]
        limit = int(query.get("limit", "500"))
        token = query.get("continue")
        if token is None:
            self.attempts[resource] += 1
            offset, attempt = 0, self.attempts[resource]
        else:
            if token not in self.issued:
                raise AssertionError("the collector sent a token this server never issued")
            t_resource, attempt, offset = self.issued[token]
            if t_resource != resource or attempt != self.attempts[resource]:
                raise AssertionError("the collector reused a token outside its attempt")
        page_no = offset // limit + 1
        if fault.get("gone_on_page") == page_no and self.gone[resource] < fault.get("gone_times", 99):
            self.gone[resource] += 1
            body = json.loads(self._status_body(410))
            body["metadata"] = {"continue": "STOLEN-TOKEN-AFTER-410"}
            return 410, json.dumps(body).encode()
        items = copy.deepcopy(self.items[resource])
        chunk = items[offset:offset + limit]
        if fault.get("item_rv_drift"):
            for n, item in enumerate(chunk):
                item["metadata"]["resourceVersion"] = str(9000 + offset + n)
        rv = self.rvs[resource] + ("-changed" if fault.get("rv_change_on_page") == page_no else "")
        meta = {"resourceVersion": rv}
        if offset + limit < len(items):
            meta["continue"] = self._token(resource, attempt, offset + limit)
            meta["remainingItemCount"] = len(items) - offset - limit
        elif fault.get("duplicate") and chunk:
            chunk.append(copy.deepcopy(items[0]))
        return 200, json.dumps({"apiVersion": api_version, "kind": kind, "metadata": meta, "items": chunk}).encode()


class Clock:
    """A deterministic client clock (wall ms, monotonic s) for replay tests."""

    def __init__(self, start_ms=1_792_051_200_000):  # 2026-10-15T08:00:00Z
        self.now = start_ms

    def wall_ms(self):
        self.now += 7
        return self.now

    def monotonic(self):
        return self.now / 1000


def openssl():
    return shutil.which("openssl")


def make_cert(directory, cn="127.0.0.1"):
    """A throwaway self-signed certificate for 127.0.0.1/localhost, generated at test time (never committed)."""
    directory = Path(directory)
    key, cert = directory / "key.pem", directory / "cert.pem"
    subprocess.run([openssl(), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
                    "-days", "1", "-subj", f"/CN={cn}", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost"],
                   check=True, capture_output=True, timeout=120)
    return cert, key


class TlsServer:
    """``FakeApi`` behind a real loopback HTTPS server. ``redirect=True`` answers every request with 302."""

    def __init__(self, api, cert, key, redirect=False):
        fake = api

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if redirect:
                    fake.requests.append((self.path, {}, self.path))
                    self.send_response(302)
                    self.send_header("Location", "https://example.invalid/steal")
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != "Bearer synthetic-test-token-0000000000000000000000":
                    status, body = 401, fake._status_body(401)
                else:
                    status, body = fake.get(self.path)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # no request logging
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def write_token(directory):
    path = Path(directory) / "token"
    path.write_text("synthetic-test-token-0000000000000000000000", encoding="ascii")
    os.chmod(path, 0o600)
    return path


def scan(paths_or_bytes):
    """Planted values found in files (recursively) or byte strings."""
    found = set()
    for item in paths_or_bytes:
        if isinstance(item, (bytes, str)) and not isinstance(item, Path):
            data = item.encode() if isinstance(item, str) else item
            found |= {p for p in PLANTED if p.encode() in data}
            continue
        root = Path(item)
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for f in files:
            data = f.read_bytes()
            found |= {p for p in PLANTED if p.encode() in data}
    return found


def tempdir(test, prefix="ca-collector-test-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    test.addCleanup(shutil.rmtree, d, True)
    return d
