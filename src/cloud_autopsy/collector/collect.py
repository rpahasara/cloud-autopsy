"""Collection run (CA-P2-004e): four list collections -> sanitized recording 0.3 -> bundle -> report.

Written, into a new output directory:
- ``recording/``: ``ca-k8s-recording/0.3-provisional`` holding projected objects only, plus per
  collection its outcome code, opaque collection resourceVersion, page and restart counts and client
  timestamps. No ``snapshot_at`` and no coverage: nothing places a collection at an API-server
  instant. Converting it again reproduces the bundle byte for byte (deterministic replay);
- ``bundle/``: the evidence bundle (observation kinds 0.2), through ``k8s_recording.convert``;
- ``report.json``: codes, counts, opaque RVs and client times only.

Every successful collection becomes a ``partial`` / ``continuity_lost`` batch (``page_limit`` when
truncated): observations kept, no coverage counted, so investigations abstain. Nothing here can
mark an investigation resolved.

CA-P2-004f adds ``run_watch``: one list + watch session (``watch.run_session``) written as a
``ca-k8s-recording/0.4-provisional`` recording (facts only), converted under contract profile 3,
re-checked by replay (``k8s_watch_recording.verify_bundle``) and reported.
"""

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from ..app import k8s_recording as K
from ..app import k8s_watch_recording as W
from ..contracts import canonical
from ..contracts import evidence as ev
from ..contracts.sources import IDENTIFIER, NAMESPACE
from . import client as cl
from . import watch as wt

RESOURCES = ("deployments", "events", "pods", "replicasets")
REPORT_VERSION = "ca-k8s-collection-report/0.1-provisional"
CLOCK_DOMAIN = "k8s-apiserver"
COLLECTOR_CLOCK_DOMAIN_PREFIX = "ca-collector-"   # + the session identity (R1, CA-P2-005b E6)


def new_session_id():
    """A fresh identity for one physical collection session: 64 random bits, never derived from the
    user-supplied recording ID (which need not be unique). Recorded once; replay reads it back."""
    return "cs-" + secrets.token_hex(8)


def collector_clock_domain(session_id):
    return COLLECTOR_CLOCK_DOMAIN_PREFIX + session_id
WATCH_REPORT_VERSION = "ca-k8s-watch-collection-report/0.1-provisional"
MAX_PART_BYTES = 900_000


@dataclass(frozen=True)
class CollectorConfig:
    server: str
    ca_file: Path
    token_file: Path
    namespace: str
    cluster_id: str
    recording_id: str
    source_id: str = "k8s-api"
    window_ms: int = 30 * 60 * 1000
    page_limit: int = 100
    max_pages: int = 20
    max_restarts: int = 1
    timeout_s: float = 10.0

    def check(self):
        cl.check_server(self.server)
        if not NAMESPACE.fullmatch(self.namespace):
            raise cl.CollectorError("namespace_invalid")
        for value in (self.cluster_id, self.recording_id, self.source_id):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or len(value) > 48:
                raise cl.CollectorError("identifier_invalid")
        if not 60_000 <= self.window_ms <= K.LIMITS["max_window_ms"] or not 1 <= self.max_pages <= 100 \
                or not 0 <= self.max_restarts <= 3:
            raise cl.CollectorError("bounds_invalid")


def _bytes(doc):
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _list_body(collection):
    _, api_version, list_kind = cl.LIST_PATHS[collection.resource]
    return {"apiVersion": api_version, "kind": list_kind,
            "metadata": {"resourceVersion": collection.collection_resource_version}, "items": collection.items}


def recording_files(config, collections):
    """{relative path: bytes} of the sanitized 0.3 recording for ``collections``."""
    end = max(c.last_response_ms for c in collections) + 1
    files, responses = {}, []
    for c in collections:
        entry = {"resource": c.resource, "outcome": c.outcome, "http_status": c.http_status, "error": c.error,
                 "file": None, "sha256": None, "collection_resource_version": None, "pages": c.pages,
                 "restarts": c.restarts, "client_first_request_at": K._ms_text(c.first_request_ms),
                 "client_last_response_at": K._ms_text(c.last_response_ms), "client_elapsed_ms": c.elapsed_ms,
                 "remaining_item_count": c.remaining_item_count}
        if c.outcome in ("consistent", "truncated"):
            data = _bytes(_list_body(c))
            path = f"responses/{c.resource}.json"
            files[path] = data
            entry.update(file=path, sha256=hashlib.sha256(data).hexdigest(),
                         collection_resource_version=c.collection_resource_version)
        responses.append(entry)
    manifest = {"contract_version": K.RECORDING_VERSION_V3, "recording_id": config.recording_id,
                "data_classification": "synthetic", "provenance": "collector", "source_id": config.source_id,
                "cluster_id": config.cluster_id, "namespace": config.namespace,
                "window": {"start": K._ms_text(end - config.window_ms), "end": K._ms_text(end)},
                "clock": {"clock_domain_id": CLOCK_DOMAIN, "status": "unknown", "offset_ms": None,
                          "offset_uncertainty_ms": None, "continuity": "unknown"},
                "responses": sorted(responses, key=lambda r: r["resource"])}
    files[K.MANIFEST] = _bytes(manifest)
    return files


def collect(config, transport=None, wall_ms=None, monotonic=None):
    """Run the four collections; returns their ``Collection`` results (projected items only)."""
    config.check()
    transport = transport or cl.HttpsTransport(config.server, config.ca_file, config.token_file, config.timeout_s)
    kwargs = {}
    if wall_ms:
        kwargs["wall_ms"] = wall_ms
    if monotonic:
        kwargs["monotonic"] = monotonic
    return [cl.collect_list(transport, r, config.namespace, config.page_limit, config.max_pages, config.max_restarts,
                            **kwargs) for r in RESOURCES]


def _write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def report(config, collections, conversion):
    rows = [{"resource": c.resource, "outcome": c.outcome, "http_status": c.http_status, "error": c.error,
             "items": len(c.items), "pages": c.pages, "restarts": c.restarts,
             "collection_resource_version": c.collection_resource_version,
             "client_first_request_at": K._ms_text(c.first_request_ms),
             "client_last_response_at": K._ms_text(c.last_response_ms), "client_elapsed_ms": c.elapsed_ms,
             "remaining_item_count": c.remaining_item_count, "withheld_or_dropped": dict(sorted(c.counts.items()))}
            for c in collections]
    return {"contract_version": REPORT_VERSION, "recording_id": config.recording_id, "cluster_id": config.cluster_id,
            "namespace": config.namespace, "source_id": config.source_id,
            "api_server_clock": "unknown", "verified_coverage_ms": 0, "collections": rows,
            "conversion": conversion.report if conversion else None,
            "note": ("A list proves one collection consistent at an opaque resourceVersion, observed between two "
                     "client-clock times. It is not placed at an API-server instant and no coverage is verified: "
                     "every successful collection is partial (continuity_lost); investigations abstain.")}


def run(config, out_dir, transport=None, wall_ms=None, monotonic=None):
    """Collect and write ``recording/``, ``bundle/`` and ``report.json`` into a new ``out_dir``."""
    collections = collect(config, transport, wall_ms, monotonic)
    out = Path(out_dir)
    out.mkdir(parents=False, exist_ok=False)
    recording = out / "recording"
    recording.mkdir()
    for rel, data in sorted(recording_files(config, collections).items()):
        (recording / rel).parent.mkdir(exist_ok=True)
        _write_new(recording / rel, data)
    conversion = K.convert(recording, ev.KIND_REGISTRY_VERSION_V2)
    conversion.write_bundle(out / "bundle")
    doc = report(config, collections, conversion)
    _write_new(out / "report.json", canonical.canonical_bytes(doc))
    return collections, conversion, doc


# ------------------------------------------------------------------------- CA-P2-004f: watch

def watch_recording_files(config, entries, clock, step_threshold_ms=250, session_id=None):
    """{relative path: bytes} of the 0.4 recording: the manifest and canonical stream parts."""
    files, streams = {}, []
    for resource in sorted(entries):
        parts, current, size = [], [], 0
        for entry in entries[resource]:
            n = len(canonical.canonical_bytes(entry)) + 1
            if current and size + n > MAX_PART_BYTES:
                parts.append(current)
                current, size = [], 0
            current.append(entry)
            size += n
        parts.append(current)
        if len(parts) > W.MAX_PARTS:
            raise cl.CollectorError("recording_too_large")
        listed = []
        for number, part in enumerate(parts, 1):
            rel = f"streams/{resource}-{number:04d}.json"
            data = canonical.canonical_bytes({"resource": resource, "part": number, "entries": part})
            if len(data) > K.MAX_RESPONSE_BYTES:
                raise cl.CollectorError("recording_too_large")
            files[rel] = data
            listed.append({"file": rel, "sha256": hashlib.sha256(data).hexdigest()})
        streams.append({"resource": resource, "parts": listed})
    manifest = {"contract_version": K.RECORDING_VERSION_V4, "recording_id": config.recording_id,
                "data_classification": "synthetic", "provenance": "collector", "source_id": config.source_id,
                "cluster_id": config.cluster_id, "namespace": config.namespace, "session_id": session_id,
                "rv_comparison": W.rv.RV_COMPARISON,
                "clocks": {"collector": {"clock_domain_id": collector_clock_domain(session_id),
                                         "anchor_wall": W._ns_text(clock.anchor_wall_ns),
                                         "max_drift_ms": clock.max_drift_ms,
                                         "step_detected": clock.max_drift_ms > step_threshold_ms},
                           "api_server": {"clock_domain_id": CLOCK_DOMAIN}},
                "streams": streams}
    files[K.MANIFEST] = _bytes(manifest)
    return files


def watch_report(config, wconfig, conversion, counts):
    return {"contract_version": WATCH_REPORT_VERSION, "recording_id": config.recording_id,
            "cluster_id": config.cluster_id, "namespace": config.namespace, "source_id": config.source_id,
            "api_server_clock": "unknown", "session_ms": int(wconfig.session_seconds * 1000),
            "bounds": {"max_events": wconfig.max_events, "max_line_bytes": wconfig.max_line_bytes,
                       "max_buffer_bytes": wconfig.max_buffer_bytes, "max_reconnects": wconfig.max_reconnects,
                       "max_relists": wconfig.max_relists, "probe_interval_ms": int(wconfig.probe_interval_s * 1000)},
            "withheld_or_dropped": counts, "verified_coverage_ms": conversion.report["verified_coverage_ms"],
            "conversion": conversion.report,
            "note": ("Coverage is verified only from the receipt of a consistent list to the send time of a "
                     "consistent-read probe that the watch later reached. Bookmarks, events or an open connection "
                     "alone cover nothing; withheld or unconverted changes make a segment partial; every other "
                     "period is a gap. Collector data alone has no symptom source, so investigations abstain.")}


def run_watch(config, wconfig, out_dir, transport=None, clock=None, stop=None, on_signal=None, session_id=None):
    """One list + watch session into a new ``out_dir``: ``recording/``, ``bundle/`` and ``report.json``.

    ``session_id`` is generated here, once per collection (``new_session_id``); tests may pass one."""
    config.check()
    wconfig.check()
    session_id = session_id or new_session_id()
    transport = transport or cl.HttpsTransport(config.server, config.ca_file, config.token_file, config.timeout_s)
    entries, clock, counts = wt.run_session(transport, config.namespace, wconfig, clock=clock, stop=stop,
                                            on_signal=on_signal)
    out = Path(out_dir)
    out.mkdir(parents=False, exist_ok=False)
    recording = out / "recording"
    recording.mkdir()
    if not isinstance(session_id, str) or not W.SESSION_ID.fullmatch(session_id):
        raise cl.CollectorError("session_id_invalid")
    files = watch_recording_files(config, entries, clock, wconfig.step_threshold_ms, session_id)
    for rel, data in sorted(files.items()):
        (recording / rel).parent.mkdir(exist_ok=True)
        _write_new(recording / rel, data)
    conversion = K.convert(recording, ev.KIND_REGISTRY_VERSION_V3)
    conversion.write_bundle(out / "bundle")
    W.verify_bundle(recording, out / "bundle")  # the bundle is exactly the recording's derivation
    doc = watch_report(config, wconfig, conversion, counts)
    _write_new(out / "report.json", canonical.canonical_bytes(doc))
    return entries, conversion, doc
