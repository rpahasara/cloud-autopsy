"""A fake Kubernetes API with pod logs (test-only, CA-P2-004g), on top of ``_fake_watch.FakeCluster``.

The planted Pods are replaced by incident pods that run a simulated workload: it writes enveloped lines
(``CA1 boot=... seq=...``) with the write-after-append handshake (in the fake an append is immediate),
a HEARTBEAT every ``interval``, POOL_EXHAUSTED once ``symptom`` is set, STOPPED on stop. Planted
sensitive lines are mixed in when ``planted=True``.

Served paths, besides list/watch: ``GET pods/<name>`` and ``GET pods/<name>/log?...&follow=true`` (a
stream; ``tailLines=0`` starts at the end; ``limitBytes`` caps it; EOF after the container stopped).

Faults (``log_faults``): ``deny`` (403 on every log request), ``eof_after`` (a stream ends after n lines,
once), ``drop_seq`` (the server silently skips that line in every stream), ``swap_on_reuse`` (a stream
follows the *name*: after a delete + recreate it serves the new pod's lines), ``garbage_after`` (a line
without an envelope), ``partial_at_end`` (a trailing line without newline before EOF).
"""

import copy
import random
import threading
import time
from urllib.parse import parse_qsl, urlsplit

import _fake_api as F
import _fake_watch as FW

from cloud_autopsy.collector import client as cl

PLANTED_LINES = ("password=PLANTED-LOG-PASSWORD-1d2", "Authorization: Bearer PLANTED-LOG-TOKEN-8e1",
                 "user PLANTED-LOG-EMAIL@example.com failed", "eyJhbGciOiJIUzI1NiJ9.PLANTED-LOG-JWT.sig")
LOG_NEEDLES = ("PLANTED-LOG-PASSWORD-1d2", "PLANTED-LOG-TOKEN-8e1", "PLANTED-LOG-EMAIL", "PLANTED-LOG-JWT")
RS_NEW, RS_OLD = "checkout-api-7c9f8", "checkout-api-6d4b5"


def _ts():
    ns = time.time_ns()
    s, frac = divmod(ns, 10 ** 9)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(s)) + f".{frac:09d}Z"


class Workload:
    def __init__(self, cluster, uid, container="checkout-api", interval=0.05, planted=False, handshake=True):
        self.cluster, self.uid, self.container = cluster, uid, container
        self.interval, self.planted, self.handshake = interval, planted, handshake
        self.boot = "%08x" % random.Random(uid).getrandbits(32)
        self.lines = []          # bytes, appended (instantly) to the "node file"
        self.seq = 0
        self.symptom = False
        self.stopped = False
        self.stop_requested = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def write(self, body):
        with self.cluster.cond:
            self.seq += 1
            hs = f" synced={self.seq - 1} lag_ms=0" if self.handshake and self.seq > 1 else ""
            self.lines.append(f"{_ts()} CA1 boot={self.boot} seq={self.seq}{hs} {body}\n".encode())
            self.cluster.cond.notify_all()

    def raw(self, text):
        with self.cluster.cond:
            self.lines.append(f"{_ts()} {text}\n".encode())
            self.cluster.cond.notify_all()

    def _run(self):
        self.write(f"STARTED pod_uid={self.uid} container={self.container}")
        n = 0
        while not self.stop_requested.wait(self.interval):
            n += 1
            if self.planted and n % 3 == 0:
                self.write("DEBUG_DUMP " + PLANTED_LINES[n % len(PLANTED_LINES)].replace(" ", "_"))
            if self.symptom:
                self.write("POOL_EXHAUSTED pool=checkout-db in_use=8 max=4")
            else:
                self.write("HEARTBEAT")
        self.write("STOPPED")
        with self.cluster.cond:
            self.stopped = True
            self.cluster.cond.notify_all()

    def start(self):
        self.thread.start()
        return self


class LogCluster(FW.FakeCluster):
    def __init__(self, log_faults=None, interval=0.05, planted=False, **kw):
        super().__init__(**kw)
        self.objects["pods"] = {}
        self.workloads = {}      # uid -> Workload
        self.log_faults = log_faults or {}
        self.interval, self.planted = interval, planted
        self.log_requests = []

    def pod_object(self, name, uid, rs=RS_NEW):
        return {"apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": name, "namespace": F.NAMESPACE, "uid": uid,
                             "creationTimestamp": "2026-11-13T10:00:00Z",
                             "ownerReferences": [{"apiVersion": "apps/v1", "kind": "ReplicaSet", "name": rs,
                                                  "uid": "0b8e7c1e-0000-4000-8000-0000000a0002", "controller": True}]},
                "spec": {"nodeName": "node-1", "containers": [{"name": "checkout-api", "image": "busybox",
                                                               "env": [{"name": "API_KEY", "value": "PLANTED-ENV-VALUE-7c1"}]}]},
                "status": {"containerStatuses": [{"name": "checkout-api", "restartCount": 0}]}}

    def spawn(self, name, uid, rs=RS_NEW, start=True):
        workload = Workload(self, uid, interval=self.interval, planted=self.planted)
        self.workloads[uid] = workload
        self._record("pods", "ADDED", self.pod_object(name, uid, rs))
        if start:
            workload.start()
        return workload

    def stop(self, uid, delete=True):
        workload = self.workloads[uid]
        workload.stop_requested.set()
        workload.thread.join(2)
        if delete:
            self._record("pods", "DELETED", self.objects["pods"][uid])

    def stop_all(self):
        for workload in self.workloads.values():
            workload.stop_requested.set()

    def _uid_for(self, name):
        with self.cond:
            for uid, obj in self.objects["pods"].items():
                if obj["metadata"]["name"] == name:
                    return uid
        return None

    def get(self, path):
        parts = urlsplit(path)
        prefix = f"/api/v1/namespaces/{F.NAMESPACE}/pods/"
        if parts.path.startswith(prefix) and "/" not in parts.path[len(prefix):]:
            self.requests.append(path)
            uid = self._uid_for(parts.path[len(prefix):])
            if uid is None:
                return 404, b'{"kind":"Status","code":404,"message":"PLANTED-STATUS-MESSAGE-5e8"}'
            import json
            return 200, json.dumps(self.objects["pods"][uid]).encode()
        return super().get(path)

    def open_stream(self, path, idle_timeout):
        parts = urlsplit(path)
        if not parts.path.endswith("/log"):
            return super().open_stream(path, idle_timeout)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.log_requests.append(path)
        assert query.get("follow") == "true" and query.get("timestamps") == "true" and "previous" not in query
        assert set(query) <= {"container", "follow", "timestamps", "limitBytes", "tailLines"}, query
        if self.log_faults.get("deny"):
            return 403, None
        name = parts.path.split("/")[-2]
        uid = self._uid_for(name)
        if uid is None or uid not in self.workloads:
            return 404, None
        workload = self.workloads[uid]
        tail = query.get("tailLines") == "0"
        with self.cond:
            start = len(workload.lines) if tail else 0
        return 200, FakeLogStream(self, name, workload, start, int(query["limitBytes"]), idle_timeout)


class FakeLogStream:
    def __init__(self, cluster, name, workload, position, limit_bytes, idle_timeout):
        self.cluster, self.name, self.workload, self.position = cluster, name, workload, position
        self.limit_bytes, self.idle_timeout = limit_bytes, idle_timeout
        self.sent_bytes, self.sent_lines = 0, 0
        self.closed = False
        self.pending_partial = False

    def readline(self, limit):
        faults = self.cluster.log_faults
        deadline = time.monotonic() + self.idle_timeout
        with self.cluster.cond:
            while True:
                if self.closed:
                    raise cl.CollectorError("unavailable")
                if faults.get("swap_on_reuse"):
                    uid = self.cluster._uid_for(self.name)
                    if uid is not None and self.cluster.workloads.get(uid) is not self.workload:
                        self.workload, self.position = self.cluster.workloads[uid], 0
                if faults.get("eof_after") is not None and self.sent_lines >= faults["eof_after"]:
                    faults.pop("eof_after")
                    return b""
                if faults.get("garbage_after") is not None and self.sent_lines >= faults["garbage_after"]:
                    faults.pop("garbage_after")
                    self.sent_lines += 1
                    return f"{_ts()} plain text PLANTED-LOG-PASSWORD-1d2\n".encode()
                if self.position < len(self.workload.lines):
                    line = self.workload.lines[self.position]
                    self.position += 1
                    drop = faults.get("drop_seq")
                    if drop is not None and f" seq={drop} ".encode() in line:
                        continue
                    if self.sent_bytes + len(line) > self.limit_bytes:
                        return b""
                    self.sent_bytes += len(line)
                    self.sent_lines += 1
                    return line[:limit]
                if self.workload.stopped:
                    if faults.get("partial_at_end") and not self.pending_partial:
                        self.pending_partial = True
                        return f"{_ts()} CA1 boot={self.workload.boot} seq=999".encode()
                    return b""
                now = time.monotonic()
                if now >= deadline:
                    raise cl.CollectorError("timeout")
                self.cluster.cond.wait(min(0.02, deadline - now))

    def close(self):
        with self.cluster.cond:
            self.closed = True
            self.cluster.cond.notify_all()
