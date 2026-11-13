"""Pod-log streams inside a watch session (CA-P2-004g): facts only, for ``app.pod_logs`` to judge.

Runs beside the list + watch readers of ``watch.run_session``. For every container of every pod the Pod
watch reports in the namespace (at most ``max_pods``), it records:

- **history** stream: ``pods/<name>/log?follow=true`` without ``tailLines`` -- the instance's log from the
  start (retried each rotation period until it opens, and again after a restart);
- **rotation** streams: every ``rotation_s`` a new ``tailLines=0`` stream; the older stream is closed only
  once the newer one has delivered a line and the older has delivered every line before it (overlap);
- **drain** stream: after the final Pod probe, one more ``tailLines=0`` stream per live instance, kept until
  it delivered two lines or ``drain_wait_s`` passed;
- a **recheck** after every stream closes: ``GET pods/<name>`` and the returned UID (nothing else kept).

Each line is sanitized in memory (``logline.sanitize``) on the reading thread; only the result is
recorded. A trailing line without a newline is recorded as ``log_partial`` (no content). Nothing here
decides coverage, identity or time order: ``app.pod_logs.derive`` does, from these entries.

Entries (all times are session-clock offsets)::

  {"seq", "type": "log_open", "stream", "pod", "uid", "container", "mode", "sent_ns", "http_status", "error"}
  {"seq", "type": "log_line", "stream", "received_ns", "line": <sanitized>}
  {"seq", "type": "log_partial", "stream", "at_ns"}
  {"seq", "type": "log_close", "stream", "at_ns", "code"}
  {"seq", "type": "log_recheck", "stream", "sent_ns", "received_ns", "http_status", "uid"}
"""

import threading
import time
from dataclasses import dataclass

from ..contracts import canonical
from ..contracts.errors import ContractError
from . import client as cl
from . import logline

CLOSE_CODES = ("eof", "rotated", "session_end", "byte_limit", "line_limit", "idle_timeout", "unavailable",
               "drained", "pod_gone", "open_failed")


@dataclass(frozen=True)
class LogConfig:
    rotation_s: float = 5.0
    drain_wait_s: float = 10.0
    idle_timeout_s: float = 10.0
    max_pods: int = 16
    max_bytes_per_instance: int = 65_536
    max_lines_per_instance: int = 2_000
    max_streams_open: int = 3            # per instance

    def check(self):
        if not 0.05 <= self.rotation_s <= 60 or not 0 <= self.drain_wait_s <= 60 \
                or not 0.05 <= self.idle_timeout_s <= 120 or not 1 <= self.max_pods <= 64 \
                or not 1024 <= self.max_bytes_per_instance <= 1_048_576 \
                or not 1 <= self.max_lines_per_instance <= 100_000 or not 2 <= self.max_streams_open <= 4:
            raise cl.CollectorError("bounds_invalid")


class _Stream:
    def __init__(self, manager, number, instance, mode):
        self.manager, self.number, self.instance, self.mode = manager, number, instance, mode
        self.handle = None
        self.closing_code = None
        self.opened = threading.Event()
        self.finished = threading.Event()
        self.status = None
        self.first = None     # (boot, seq) of the first line delivered
        self.last = None      # (boot, seq) of the last line delivered
        self.lines = 0

    def close(self, code):
        if self.closing_code is None:
            self.closing_code = code
        handle = self.handle
        if handle is not None:
            handle.close()

    def run(self):
        m, inst = self.manager, self.instance
        try:
            budget = inst.bytes_left()
            path = cl.build_pod_log_path(m.namespace, inst.pod, inst.container, tail_zero=self.mode != "history",
                                         limit_bytes=max(1, budget))
            sent = m.clock.offset_ns()
            try:
                status, handle = m.transport.open_stream(path, m.config.idle_timeout_s)
                error = None
            except cl.CollectorError as exc:
                status, handle, error = None, None, exc.code
            self.status = status
            m.append({"type": "log_open", "stream": self.number, "pod": inst.pod, "uid": inst.uid,
                      "container": inst.container, "mode": self.mode, "sent_ns": sent, "http_status": status,
                      "error": error})
            if status != 200 or handle is None:
                m.append({"type": "log_close", "stream": self.number, "at_ns": m.clock.offset_ns(),
                          "code": "open_failed"})
                return
            self.handle = handle
            self.opened.set()
            if self.closing_code is not None:
                handle.close()
            code = self._read(handle)
            m.append({"type": "log_close", "stream": self.number, "at_ns": m.clock.offset_ns(),
                      "code": self.closing_code or code})
            handle.close()
            self._recheck()
        except Exception:  # noqa: BLE001 -- never a silent thread death: the stream ends and is not coverage
            m.append({"type": "log_close", "stream": self.number, "at_ns": m.clock.offset_ns(),
                      "code": "unavailable"})
        finally:
            self.opened.set()
            self.finished.set()

    def _read(self, handle):
        m, inst = self.manager, self.instance
        limit = logline.MAX_LINE_BYTES + 64
        while True:
            try:
                raw = handle.readline(limit + 1)
            except cl.CollectorError as exc:
                return "idle_timeout" if exc.code == "timeout" else "unavailable"
            received = m.clock.offset_ns()
            if not raw:
                return "eof"
            if not raw.endswith(b"\n"):
                if len(raw) > limit:   # an over-long line: recorded as invalid, the rest is skipped by the bound
                    m.append({"type": "log_line", "stream": self.number, "received_ns": received,
                              "line": {"invalid": "too_long"}})
                    return "unavailable"
                m.append({"type": "log_partial", "stream": self.number, "at_ns": received})
                continue
            if not inst.spend(len(raw)):
                return "byte_limit" if inst.bytes_left() <= 0 else "line_limit"
            line = logline.sanitize(raw[:-1])       # the raw bytes are dropped here
            del raw
            m.append({"type": "log_line", "stream": self.number, "received_ns": received, "line": line})
            if "invalid" not in line:
                key = (line["boot"], line["seq"])
                with m.lock:
                    self.first = self.first or key
                    self.last = key
                    self.lines += 1
                    if line["template"] == "STOPPED":
                        inst.stopped = True

    def _recheck(self):
        m, inst = self.manager, self.instance
        sent = m.clock.offset_ns()
        uid = None
        try:
            status, body = m.transport.get(cl.build_pod_path(m.namespace, inst.pod))
        except cl.CollectorError:
            status, body = None, b""
        received = m.clock.offset_ns()
        if status == 200:
            try:
                doc = canonical.loads(body, canonical.Limits(max_bytes=cl.MAX_PAGE_BYTES))
                meta = doc.get("metadata") if isinstance(doc, dict) else None
                value = meta.get("uid") if isinstance(meta, dict) else None
                uid = value if isinstance(value, str) and 0 < len(value) <= 128 and value.isprintable() else None
            except ContractError:
                status = None
        m.append({"type": "log_recheck", "stream": self.number, "sent_ns": sent, "received_ns": received,
                  "http_status": status, "uid": uid})


class _Instance:
    def __init__(self, manager, uid, pod, container):
        self.manager, self.uid, self.pod, self.container = manager, uid, pod, container
        self.streams = []
        self.history_ok = False      # some history stream ever opened
        self.epoch = None            # the pod's restart count the current history belongs to
        self.epoch_ok = False
        self.next_attempt = 0.0
        self.stopped = False
        self.bytes, self.lines = 0, 0

    def bytes_left(self):
        return self.manager.config.max_bytes_per_instance - self.bytes

    def spend(self, n):
        cfg = self.manager.config
        with self.manager.lock:
            if self.bytes + n > cfg.max_bytes_per_instance or self.lines + 1 > cfg.max_lines_per_instance:
                return False
            self.bytes += n
            self.lines += 1
            return True

    def live(self):
        return [s for s in self.streams if not s.finished.is_set()]


class PodLogManager:
    def __init__(self, transport, namespace, clock, config):
        config.check()
        self.transport, self.namespace, self.clock, self.config = transport, namespace, clock, config
        self.lock = threading.Lock()
        self.entries = []
        self.pods = {}           # uid -> {"name", "containers", "restarts", "deleted"}
        self.instances = {}      # (uid, container) -> _Instance
        self.threads = []
        self.stop = threading.Event()
        self.counts = {}
        self._number = 0

    # ----------------------------------------------------------------------------- entries
    def append(self, entry):
        with self.lock:
            entry["seq"] = len(self.entries) + 1
            self.entries.append(entry)

    # ----------------------------------------------------------- facts from the Pod watch
    def on_pod(self, kind, obj):
        """Called by the Pod reader for listed items and watch events (projected objects)."""
        if not isinstance(obj, dict):
            return
        meta = obj.get("metadata") or {}
        uid, name = meta.get("uid"), meta.get("name")
        if not isinstance(uid, str) or not isinstance(name, str):
            return
        containers = [c.get("name") for c in (obj.get("spec") or {}).get("containers") or []
                      if isinstance(c, dict) and isinstance(c.get("name"), str)]
        restarts = sum(s.get("restartCount", 0) for s in (obj.get("status") or {}).get("containerStatuses") or []
                       if isinstance(s, dict) and type(s.get("restartCount")) is int)
        with self.lock:
            pod = self.pods.get(uid)
            if pod is None:
                if len(self.pods) >= self.config.max_pods:
                    self.counts["pods_over_limit"] = self.counts.get("pods_over_limit", 0) + 1
                    return
                pod = self.pods[uid] = {"name": name, "containers": sorted(set(containers)), "restarts": restarts,
                                        "deleted": False}
            pod["restarts"] = max(pod["restarts"], restarts)
            if kind == "DELETED":
                pod["deleted"] = True

    # ------------------------------------------------------------------------- streams
    def _start(self, inst, mode):
        with self.lock:
            self._number += 1
            stream = _Stream(self, self._number, inst, mode)
            stream.epoch = inst.epoch
            inst.streams.append(stream)
        thread = threading.Thread(target=stream.run, name=f"ca-log-{stream.number}", daemon=True)
        self.threads.append(thread)
        thread.start()
        return stream

    def _tick(self, now):
        with self.lock:
            pods = {uid: dict(p) for uid, p in self.pods.items()}
        for uid, pod in sorted(pods.items()):
            for container in pod["containers"]:
                inst = self.instances.get((uid, container))
                if inst is None:
                    inst = self.instances[(uid, container)] = _Instance(self, uid, pod["name"], container)
                if pod["deleted"] and inst.stopped:
                    continue
                if inst.epoch != pod["restarts"]:      # first sight, or a restart: a new history is needed
                    inst.epoch, inst.epoch_ok, inst.stopped = pod["restarts"], False, False
                if any(s.mode == "history" and s.epoch == inst.epoch and s.status == 200 for s in inst.streams):
                    inst.epoch_ok = inst.history_ok = True
                if not inst.epoch_ok:
                    history_live = any(s.mode == "history" and not s.finished.is_set() for s in inst.streams)
                    if not history_live and now >= inst.next_attempt and not pod["deleted"]:
                        self._start(inst, "history")
                        inst.next_attempt = now + self.config.rotation_s
                    continue
                if inst.stopped or pod["deleted"]:
                    continue
                if now >= inst.next_attempt and len(inst.live()) < self.config.max_streams_open:
                    self._start(inst, "rotation")
                    inst.next_attempt = now + self.config.rotation_s
                self._retire(inst)

    def _retire(self, inst):
        """Close an older stream once a newer one overlaps it (the newer delivered line s, the older s-1)."""
        live = inst.live()
        for older, newer in zip(live, live[1:]):
            with self.lock:
                first, last = newer.first, older.last
            if first is None or last is None or first[0] != last[0]:
                continue
            if last[1] >= first[1] - 1:
                older.close("rotated")

    def run(self):
        while not self.stop.wait(0.05):
            self._tick(time.monotonic())

    # ---------------------------------------------------------------------------- finish
    def finish(self):
        """Called after the final Pod probe was sent: drain each live instance, close everything."""
        self.stop.set()
        drains = []
        for inst in self.instances.values():
            with self.lock:
                deleted = self.pods.get(inst.uid, {}).get("deleted", False)
            if inst.history_ok and not inst.stopped and not deleted:
                drains.append(self._start(inst, "drain"))
        deadline = time.monotonic() + self.config.drain_wait_s
        while drains and time.monotonic() < deadline:
            if all(s.finished.is_set() or s.lines >= 2 for s in drains):
                break
            time.sleep(0.02)
        for inst in self.instances.values():
            for stream in inst.streams:
                stream.close("drained" if stream.mode == "drain" else "session_end")
        join_deadline = time.monotonic() + 10
        for thread in self.threads:
            thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
        with self.lock:
            entries = list(self.entries)
        # A stream thread still blocked has no close in the recording: give it one now, as the
        # watch readers' reader_stalled does. Its lines after this point are never recorded.
        closed = {e["stream"] for e in entries if e["type"] == "log_close"}
        opened = [e["stream"] for e in entries if e["type"] == "log_open"]
        for number in opened:
            if number not in closed:
                entries.append({"seq": len(entries) + 1, "type": "log_close", "stream": number,
                                "at_ns": self.clock.offset_ns(), "code": "unavailable"})
        return entries
