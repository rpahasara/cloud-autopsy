"""List + watch collection session (CA-P2-004f): facts only, recorded for ``k8s_watch_recording``.

For each of the four resources, one reader thread lists and watches, and one prober thread sends
consistent-read probes. Every entry is stamped with the session clock: one wall-clock reading at the
start (the anchor) plus the monotonic clock. Nothing here decides coverage or outcomes; the recording
adapter derives them from these facts.

Reader, per resource:
1. A paginated consistent list (the 004e safeguards). A failed list ends the resource: the rest of
   the window is a gap.
2. A watch from the list's collection resourceVersion with bookmarks requested. Each line is read
   under ``max_line_bytes``, parsed strictly and projected immediately (the raw line is dropped).
   resourceVersions must be valid (F3) and must not regress; objects must be in the namespace.
3. End of stream, an idle timeout, 429 or 5xx: resume from the last delivered resourceVersion, at
   most ``max_reconnects`` times. 410 (an ERROR event or a refused resume): end the segment and
   relist, at most ``max_relists`` times. 401/403: end. Anything invalid: end.
4. Bounds (events per resource, the projected buffer of the session) end the resource.

Prober, per resource: every ``probe_interval_s``, ``GET <list path>?limit=1`` (a consistent read),
recording its send and receipt times and the returned collection resourceVersion. The returned item
and any continue token are discarded unread. A probe whose segment changed while it was in flight is
dropped, so a recorded probe always belongs to its segment.

Shutdown (end of session, a signal or ``stop()``): each prober sends a final probe; readers keep
reading until the watch delivers that resourceVersion or ``final_wait_s`` passes, then end with
``session_end`` or ``signal``. Every connection is closed. Nothing raw is kept.
"""

import threading
import time
from dataclasses import dataclass

from ..contracts import canonical
from ..contracts import resourceversion as rv
from ..contracts.errors import ContractError
from . import client as cl
from . import project

RESOURCES = ("deployments", "events", "pods", "replicasets")
EVENT_TYPES = ("ADDED", "MODIFIED", "DELETED", "BOOKMARK", "ERROR")
MAX_CLEAN_RESUMES = 200   # server-closed watches (timeoutSeconds) resumed per segment


@dataclass(frozen=True)
class WatchConfig:
    session_seconds: float = 300.0
    probe_interval_s: float = 15.0
    idle_timeout_s: float = 90.0
    watch_timeout_s: int = 600            # upper bound on each watch request's timeoutSeconds
    final_wait_s: float = 90.0
    max_events: int = 10_000
    max_line_bytes: int = 1_048_576
    max_buffer_bytes: int = 32 * 1_048_576
    max_reconnects: int = 3
    max_relists: int = 2
    step_threshold_ms: int = 250
    page_limit: int = 100
    max_pages: int = 20
    max_restarts: int = 1

    def check(self):
        if not 1 <= self.session_seconds <= 600 or not 0.01 <= self.probe_interval_s <= 60 \
                or not 0.05 <= self.idle_timeout_s <= 300 or not 0 <= self.final_wait_s <= 300 \
                or not 1 <= self.max_events <= 100_000 or not 1024 <= self.max_line_bytes <= 1_048_576 \
                or not 1 <= self.max_buffer_bytes <= 256 * 1_048_576 or not 0 <= self.max_reconnects <= 10 \
                or not 0 <= self.max_relists <= 5 or not 1 <= self.max_pages <= 100                 or type(self.watch_timeout_s) is not int or not 1 <= self.watch_timeout_s <= 600:
            raise cl.CollectorError("bounds_invalid")


class SessionClock:
    """One wall-clock reading (the anchor) plus the monotonic clock; step detection by drift."""

    def __init__(self, wall_ns=time.time_ns, monotonic_ns=time.monotonic_ns):
        self._wall, self._mono = wall_ns, monotonic_ns
        self.anchor_wall_ns = wall_ns()
        self._anchor_mono = monotonic_ns()
        self.max_drift_ms = 0

    def offset_ns(self):
        """Nanoseconds since the anchor (what the recording stores)."""
        return self._mono() - self._anchor_mono

    def check_drift(self):
        drift = abs(self._wall() - (self.anchor_wall_ns + self.offset_ns())) // 1_000_000
        self.max_drift_ms = max(self.max_drift_ms, drift)
        return drift


class _Shared:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.finishing = threading.Event()
        self.reason = "session_end"
        self.buffer_bytes = 0


class _Resource:
    def __init__(self, name, shared, transport, namespace, clock):
        self.name, self.shared, self.transport, self.namespace, self.clock = name, shared, transport, namespace, clock
        self.entries = []
        self.segment = 0
        self.segment_open = False
        self.last_rv = None
        self.final_rv = None
        self.final_sent = threading.Event()
        self.done = threading.Event()
        self.stream = None
        self.events = 0
        self.counts = {}
        self.on_object = None   # CA-P2-004g: the pod-log manager hears listed and watched Pods
        self.limits = ()        # CA-P2-004g: declared numeric limits (ReplicaSet projection only)

    # -------------------------------------------------------------------------- entries
    def _append(self, entry):
        with self.shared.lock:
            entry["seq"] = len(self.entries) + 1
            self.entries.append(entry)

    def _end(self, code, status=None):
        self.segment_open = False
        self._append({"segment": self.segment, "type": "end", "at_ns": self.clock.offset_ns(), "code": code,
                      "http_status": status})

    # --------------------------------------------------------------------------- reader
    def run_reader(self):
        try:
            self._read()
        except Exception:  # noqa: BLE001 -- never a silent thread death: the segment ends as a gap
            with self.shared.lock:
                ended = not self.entries or self.entries[-1]["type"] == "end" or (
                    self.entries[-1]["type"] == "list" and not self.segment_open)
            if self.segment and not ended:
                self._end("reader_failed")
        finally:
            self.segment_open = False
            self.done.set()

    def _list(self):
        cfg = self.shared.config
        result = cl.collect_list(self.transport, self.name, self.namespace, cfg.page_limit, cfg.max_pages,
                                 cfg.max_restarts, clock_ns=self.clock.offset_ns)
        if result.outcome in ("consistent", "truncated") and not rv.is_valid(result.collection_resource_version):
            # Not comparable under the F3 rule: recorded as an invalid list (no items, no resourceVersion).
            result.outcome, result.error, result.items, result.collection_resource_version = (
                "invalid", "rv_invalid", [], None)
        with self.shared.lock:
            self.segment += 1
            self.segment_open = result.outcome in ("consistent", "truncated")
            entry = {"segment": self.segment, "type": "list", "sent_ns": result.first_request_ns,
                     "first_page_ns": result.first_page_ns if result.outcome in ("consistent", "truncated") else None,
                     "last_page_ns": result.last_response_ns, "outcome": result.outcome,
                     "http_status": result.http_status, "error": result.error,
                     "collection_resource_version": result.collection_resource_version, "pages": result.pages,
                     "restarts": result.restarts, "items": result.items,
                     "withheld": result.counts.get("secret_events_withheld", 0)}
            entry["seq"] = len(self.entries) + 1
            self.entries.append(entry)
            for key, value in result.counts.items():
                self.counts[key] = self.counts.get(key, 0) + value
        if self.on_object is not None and result.outcome in ("consistent", "truncated"):
            for item in result.items:
                self.on_object("LISTED", item)
        return result

    def _read(self):
        cfg = self.shared.config
        relists = 0
        while True:
            listing = self._list()
            if listing.outcome == "truncated":
                self._end("list_truncated")  # an incomplete starting state cannot anchor a watch
                return
            if listing.outcome != "consistent":
                return  # a failed list: the rest of the window is a gap
            self.last_rv = listing.collection_resource_version
            reconnects = 0
            outcome = self._watch_segment(reconnects)
            if outcome == "relist" and relists < cfg.max_relists and not self.shared.finishing.is_set():
                relists += 1
                continue
            if outcome == "relist":
                self._end("relists_exhausted" if relists >= cfg.max_relists else self.shared.reason)
            return

    def _remaining_s(self, deadline):
        return max(1, min(self.shared.config.watch_timeout_s, int(deadline - time.monotonic())))

    def _watch_segment(self, reconnects):
        """Watch until the segment ends. Returns 'relist' after a 410, otherwise 'done'."""
        cfg = self.shared.config
        clean_resumes = 0
        while True:
            if self._finished():
                self._end(self.shared.reason)
                return "done"
            # While finishing, size timeoutSeconds to the final deadline, not the passed session deadline.
            deadline = self.shared.final_deadline if self.shared.finishing.is_set() and self.shared.final_deadline                 else self.shared.deadline
            path = cl.build_watch_path(self.name, self.namespace, self.last_rv, self._remaining_s(deadline))
            sent = self.clock.offset_ns()
            try:
                status, stream = self.transport.open_stream(path, cfg.idle_timeout_s)
                error = None
            except cl.CollectorError as exc:
                status, stream, error = None, None, exc.code
            self._append({"segment": self.segment, "type": "watch_open", "sent_ns": sent,
                          "from_resource_version": self.last_rv, "http_status": status, "error": error})
            if status == 200:
                result = self._consume(stream)
                if result in ("relist", "done"):
                    if result == "relist":
                        self._end("expired", 410)
                    return result
                code = result  # a disconnect: resume
            elif status == 410:
                self._end("expired", 410)
                return "relist"
            elif status in (401, 403):
                self._end("denied", status)
                return "done"
            else:
                code = error or ("rate_limited" if status == 429 else f"http_{status}")
            if self._finished():
                self._end(self.shared.reason)
                return "done"
            self._append({"segment": self.segment, "type": "disconnect", "at_ns": self.clock.offset_ns(),
                          "code": code[:64]})
            if code == "end_of_stream":
                # The server ended the watch cleanly (its timeoutSeconds): an expected resume, not a fault.
                # Bounded separately so a server that closes at once cannot spin the reader.
                clean_resumes += 1
                if clean_resumes > MAX_CLEAN_RESUMES:
                    self._end("reconnects_exhausted")
                    return "done"
                continue
            reconnects += 1
            if reconnects > cfg.max_reconnects:
                self._end("reconnects_exhausted")
                return "done"
            time.sleep(min(2.0, 0.2 * reconnects))

    def _finished(self):
        if not self.shared.finishing.is_set():
            return False
        if self.final_sent.is_set() and self.final_rv is not None and self.last_rv is not None \
                and rv.at_least(self.last_rv, self.final_rv):
            return True  # the final probe is proven
        return self.shared.final_deadline is not None and time.monotonic() >= self.shared.final_deadline

    def _consume(self, stream):
        """Read one open watch. Returns 'relist', 'done', or a disconnect code."""
        cfg = self.shared.config
        self.stream = stream
        try:
            while True:
                if self._finished():
                    self._end(self.shared.reason)
                    return "done"
                try:
                    line = stream.readline(cfg.max_line_bytes + 1)
                except cl.CollectorError as exc:
                    if self.shared.finishing.is_set():
                        self._end(self.shared.reason)
                        return "done"
                    return "idle_timeout" if exc.code == "timeout" else "stream_closed"
                if not line:
                    return "end_of_stream"
                if len(line) > cfg.max_line_bytes:
                    self._end("line_too_large")
                    return "done"
                received = self.clock.offset_ns()
                outcome = self._line(line, received)
                if outcome:
                    return outcome
        finally:
            self.stream = None
            stream.close()

    def _line(self, line, received):
        """Handle one watch line; returns None to continue, or 'relist' / 'done'."""
        cfg = self.shared.config
        try:
            doc = canonical.loads(line.strip(), canonical.Limits(max_bytes=cfg.max_line_bytes))
        except ContractError:
            self._end("invalid_line")
            return "done"
        kind = doc.get("type") if isinstance(doc, dict) else None
        obj = doc.get("object") if isinstance(doc, dict) else None
        if kind not in EVENT_TYPES or not isinstance(obj, dict):
            self._end("invalid_line")
            return "done"
        if kind == "ERROR":
            code = obj.get("code")
            if code == 410:
                return "relist"
            self._end("denied" if code in (401, 403) else "unavailable", code if type(code) is int else None)
            return "done"
        meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        value = meta.get("resourceVersion")
        if not rv.is_valid(value):
            self._end("rv_invalid")
            return "done"
        order = rv.compare(value, self.last_rv)
        if order < 0 or (order == 0 and kind != "BOOKMARK"):
            self._end("rv_regression")
            return "done"
        if kind == "BOOKMARK":
            self.last_rv = value
            self._append({"segment": self.segment, "type": "bookmark", "received_ns": received,
                          "resource_version": value})
            return None
        if meta.get("namespace") != self.namespace:
            self._end("namespace_mismatch")
            return "done"
        projected = project.project(self.name, obj, self.counts, self.limits)
        size = len(canonical.canonical_bytes(projected)) if projected is not None else 0
        with self.shared.lock:
            self.shared.buffer_bytes += size
            over_buffer = self.shared.buffer_bytes > cfg.max_buffer_bytes
        if over_buffer:
            self._end("buffer_limit")
            return "done"
        self.last_rv = value
        self.events += 1
        self._append({"segment": self.segment, "type": "event", "received_ns": received, "event": kind,
                      "resource_version": value, "object": projected,
                      "withheld": None if projected is not None else "secret_event"})
        if self.on_object is not None and projected is not None:
            self.on_object(kind, projected)
        if self.events >= cfg.max_events:
            self._end("event_limit")
            return "done"
        return None

    # --------------------------------------------------------------------------- prober
    def probe(self):
        with self.shared.lock:
            segment, open_ = self.segment, self.segment_open
        if not open_:
            return None
        sent = self.clock.offset_ns()
        self.clock.check_drift()
        try:
            status, body = self.transport.get(cl.build_path(self.name, self.namespace, 1))
            error = None
        except cl.CollectorError as exc:
            status, body, error = None, b"", exc.code
        received = self.clock.offset_ns()
        value = None
        if status == 200:
            try:
                page = canonical.loads(body, canonical.Limits(max_bytes=cl.MAX_PAGE_BYTES))
                meta = page.get("metadata") if isinstance(page, dict) else None
                candidate = meta.get("resourceVersion") if isinstance(meta, dict) else None
                value = candidate if rv.is_valid(candidate) else None
            except ContractError:
                value, error = None, "body_not_strict_json"
        with self.shared.lock:
            if self.segment != segment:
                return None  # the segment changed in flight: the probe is dropped
            entry = {"segment": segment, "type": "probe", "sent_ns": sent, "received_ns": received,
                     "resource_version": value, "http_status": status, "error": error}
            entry["seq"] = len(self.entries) + 1
            self.entries.append(entry)
        return value

    def run_prober(self):
        interval = self.shared.config.probe_interval_s
        while not self.shared.finishing.wait(interval):
            if self.done.is_set():
                return
            self.probe()
        if not self.done.is_set():
            self.final_rv = self.probe()
        self.final_sent.set()


def run_session(transport, namespace, config, clock=None, stop=None, on_signal=None, pod_logs=None, limits=(),
                resources=RESOURCES):
    """Run one session. Returns (entries by resource, clock, counts). ``stop`` is an Event that ends
    the session early (``on_signal()`` True marks the end as a signal).

    CA-P2-004g: ``pod_logs`` (a ``podlogs.LogConfig``) also records the pods' logs; the entries are
    returned under ``"pod_logs"``. ``limits``: validated declared numeric limits (``limits.py``)."""
    config.check()
    clock = clock or SessionClock()
    shared = _Shared(config)
    shared.deadline = time.monotonic() + config.session_seconds
    shared.final_deadline = None
    if not set(resources) <= set(RESOURCES) or not {"deployments", "pods", "replicasets"} <= set(resources):
        raise cl.CollectorError("resources_invalid")   # only Events may be left out (recording 0.7)
    resources = {name: _Resource(name, shared, transport, namespace, clock) for name in sorted(resources)}
    resources["replicasets"].limits = tuple(limits)
    logs = None
    if pod_logs is not None:
        from . import podlogs
        logs = podlogs.PodLogManager(transport, namespace, clock, pod_logs)
        resources["pods"].on_object = logs.on_pod
    threads = []
    for res in resources.values():
        threads.append(threading.Thread(target=res.run_reader, name=f"ca-watch-{res.name}", daemon=True))
        threads.append(threading.Thread(target=res.run_prober, name=f"ca-probe-{res.name}", daemon=True))
    for t in threads:
        t.start()
    if logs is not None:
        log_thread = threading.Thread(target=logs.run, name="ca-logs", daemon=True)
        log_thread.start()
    stop = stop or threading.Event()
    end = time.monotonic() + config.session_seconds
    while time.monotonic() < end and not stop.is_set() and not all(r.done.is_set() for r in resources.values()):
        stop.wait(min(0.2, max(0.0, end - time.monotonic())))
    if stop.is_set() and on_signal and on_signal():
        shared.reason = "signal"
    shared.final_deadline = time.monotonic() + config.final_wait_s
    shared.finishing.set()
    give_up = shared.final_deadline + 5
    while time.monotonic() < give_up and not all(r.done.is_set() for r in resources.values()):
        if time.monotonic() >= shared.final_deadline:
            for res in resources.values():
                stream = res.stream
                if stream is not None:
                    stream.close()  # unblocks a reader waiting on a silent watch
        time.sleep(0.05)
    for res in resources.values():
        stream = res.stream
        if stream is not None:
            stream.close()
    log_entries = None
    if logs is not None:
        # The final Pod probe was sent before the readers finished: drain after it (plan 4.4 step 3).
        resources["pods"].final_sent.wait(5)
        log_entries = logs.finish()
        log_thread.join(timeout=5)
    join_deadline = time.monotonic() + 10  # one bound for all threads, not ten seconds each
    for t in threads:
        t.join(timeout=max(0.0, join_deadline - time.monotonic()))
    snapshot = {}
    for name, res in resources.items():
        with shared.lock:
            entries = list(res.entries)
        # A reader still blocked (for example on a watch request a stalled API server never answers)
        # must not leave its stream without an end: that resource ends ``reader_stalled`` (a gap) in
        # the snapshot written now; whatever the stalled thread does later is never recorded.
        last = next((e for e in reversed(entries) if e["type"] != "probe"), None)  # probes may follow an end
        open_segment = last is not None and last["type"] != "end" and not (
            last["type"] == "list" and last["outcome"] not in ("consistent", "truncated"))
        if not res.done.is_set() and open_segment:
            entries.append({"seq": len(entries) + 1, "segment": last["segment"], "type": "end",
                            "at_ns": clock.offset_ns(), "code": "reader_stalled", "http_status": None})
        snapshot[name] = entries
    counts = {name: dict(sorted(r.counts.items())) for name, r in resources.items()}
    if logs is not None:
        snapshot["pod_logs"] = log_entries
        counts["pod_logs"] = dict(sorted(logs.counts.items()))
    return snapshot, clock, counts
