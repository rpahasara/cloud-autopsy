"""Collector list + watch recordings, ``ca-k8s-recording/0.4-provisional`` (CA-P2-004f, provisional).

Strictly offline. A 0.4 recording holds **facts only**: what the collector sent and received, on its
own clock. It contains no batch outcome, coverage or coverage basis. This module derives all of
them, and the same derivation is the replay check: converting a recording again gives a
byte-identical bundle, and ``verify_bundle`` refuses any bundle that differs.

Layout::

  recording.json                 the manifest
  streams/<resource>-<nnnn>.json the entries of one resource, in parts of at most 1 MiB

  recording.json = {
    "contract_version": "ca-k8s-recording/0.4-provisional", "recording_id", "data_classification": "synthetic",
    "provenance": "collector", "source_id", "cluster_id", "namespace", "session_id": "cs-<16 hex>",
    "rv_comparison": "k8s-1.37-decimal",
    "clocks": {"collector": {"clock_domain_id": "ca-collector-<session_id>", "anchor_wall", "max_drift_ms",
                             "step_detected"},
               "api_server": {"clock_domain_id"}},
    "streams": [{"resource": "pods" | "replicasets" | "deployments" | "events",
                 "parts": [{"file": "streams/<resource>-<nnnn>.json", "sha256"}, ...]}, ...]}

  a part = {"resource", "part": n, "entries": [entry, ...]}, entries numbered by ``seq`` from 1
  across the parts of one resource. ``anchor_wall`` is the collector's one wall-clock reading (RFC 3339
  UTC, nine fraction digits); every ``*_ns`` time is integer nanoseconds of the collector's monotonic
  clock since that reading (the canonical profile bounds integers, so absolute nanoseconds are never
  written). The converter adds the anchor back.

  {"seq", "segment", "type": "list", "sent_ns", "first_page_ns", "last_page_ns", "outcome",
   "http_status", "error", "collection_resource_version", "pages", "restarts", "items", "withheld"}
  {"seq", "segment", "type": "watch_open", "sent_ns", "from_resource_version", "http_status", "error"}
  {"seq", "segment", "type": "event", "received_ns", "event": "ADDED" | "MODIFIED" | "DELETED",
   "resource_version", "object": <projected object> | null, "withheld": null | "<code>"}
  {"seq", "segment", "type": "bookmark", "received_ns", "resource_version"}
  {"seq", "segment", "type": "probe", "sent_ns", "received_ns", "resource_version" | null, "http_status", "error"}
  {"seq", "segment", "type": "disconnect", "at_ns", "code"}
  {"seq", "segment", "type": "end", "at_ns", "code", "http_status"}

What is derived (per resource, per segment; a segment is one consistent list and the watch that
continues from it, including resumes from the last delivered resourceVersion):
- **Proof.** A probe with resourceVersion ``p`` (a consistent read sent at ``t_p``) is *proven* when
  the same segment delivers an event or bookmark with resourceVersion >= ``p`` (F3 rule). Verified
  coverage is ``[ceil(first list page received), floor(t_p))`` for the latest proven probe, carried
  as a ``watch_continuity`` basis. Bookmarks, events or an open connection alone never cover time.
- **Batches.** The list state: ``partial`` / ``continuity_lost`` (a state, not changes). Changes up to
  the proving resourceVersion: ``complete`` (or ``empty`` when no change at all arrived), unless any
  change was withheld or could not be converted: then ``partial`` / ``changes_withheld``. Later
  changes: ``partial`` / ``continuity_unproven`` (``event_limit``, truncated, when a bound stopped the
  segment). A failed first list: the 004e failed/denied mapping. Nothing else.
- **Observed times.** A change with resourceVersion ``e`` committed after the send time of the
  latest consistent read (list or probe) of its segment with a resourceVersion below ``e``, and
  before its receipt: ``observed`` = ``[that send time, receipt)``, encoded with the unchanged time
  contract (raw = lower bound, declared precision = width).
- **Clock.** The collector domain is declared ``unknown`` (no offset to any clock) with continuity
  ``declared_continuous``, or ``step_declared`` when the collector detected a wall-clock step. The
  API-server domain is ``unknown``.

Refused outright (``RecordingError``): anything but synthetic collector provenance; unknown fields;
stream entries out of order, regressing resourceVersions, invalid resourceVersions, an event object
that disagrees with its entry, an object outside the namespace, a resume from another resourceVersion,
times that contradict causality, unsafe files or digests that do not match.
"""

import hashlib
import os
import re
from pathlib import Path

from ..contracts import acquisition as acq
from ..contracts import canonical
from ..contracts import evidence as ev
from ..contracts import plan as pl
from ..contracts import resourceversion as rv
from ..contracts import timeinterval as ti
from ..contracts.errors import ContractError
from ..contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry
from ..engine import clocks, required_rule_versions
from . import bundle as B
from . import k8s_recording as K

RECORDING_VERSION = K.RECORDING_VERSION_V4
REPORT_VERSION = "ca-k8s-watch-conversion-report/0.1-provisional"
QUERIES = {"k8s.deployments": "deployments", "k8s.events": "events", "k8s.pods": "pods",
           "k8s.replicasets": "replicasets"}
MANDATORY = {"k8s.deployments": True, "k8s.events": False, "k8s.pods": True, "k8s.replicasets": True}
RESOURCE_TYPES = {"pods": "v1/pods", "replicasets": "apps/v1/replicasets", "deployments": "apps/v1/deployments",
                  "events": "v1/events"}
ENTITY = {"pods": "Pod", "replicasets": "ReplicaSet", "deployments": "Deployment", "events": "Event"}
LIMITS = {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 1_000, "max_batch_deliveries": 10_000,
          "max_observations_per_batch": 200, "max_observations_total": 50_000, "max_batch_bytes": 1_048_576,
          "max_total_bytes": 100_000_000}
MAX_PARTS = 48
_MANIFEST_KEYS = {"contract_version", "recording_id", "data_classification", "provenance", "source_id", "cluster_id",
                  "namespace", "session_id", "rv_comparison", "clocks", "streams"}
_ENTRY_KEYS = {
    "list": {"seq", "segment", "type", "sent_ns", "first_page_ns", "last_page_ns", "outcome", "http_status", "error",
             "collection_resource_version", "pages", "restarts", "items", "withheld"},
    "watch_open": {"seq", "segment", "type", "sent_ns", "from_resource_version", "http_status", "error"},
    "event": {"seq", "segment", "type", "received_ns", "event", "resource_version", "object", "withheld"},
    "bookmark": {"seq", "segment", "type", "received_ns", "resource_version"},
    "probe": {"seq", "segment", "type", "sent_ns", "received_ns", "resource_version", "http_status", "error"},
    "disconnect": {"seq", "segment", "type", "at_ns", "code"},
    "end": {"seq", "segment", "type", "at_ns", "code", "http_status"},
}
END_CODES = ("expired", "denied", "unavailable", "timeout", "rate_limited", "invalid_line", "line_too_large",
             "rv_invalid", "rv_regression", "namespace_mismatch", "reconnects_exhausted", "relists_exhausted",
             "event_limit", "buffer_limit", "session_end", "signal", "list_failed", "list_truncated",
             "reader_failed")
_PART = re.compile(r"streams/(pods|replicasets|deployments|events)-[0-9]{4}\.json", re.ASCII)
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
NS_PER_MS = 1_000_000
MAX_NS = 32_503_680_000 * 10 ** 9  # year 3000: a bound, never a meaning
MAX_OFFSET_NS = 2 * 3600 * 10 ** 9  # a recording's times lie within two hours of its anchor
# R1 (CA-P2-005b E6): one physical collection session = one generated identity = one collector clock
# domain. The recording ID is user-supplied and may repeat; the session identity may not be derived
# from it. Replay reads the recorded identity and never generates one.
SESSION_ID = re.compile(r"cs-[0-9a-f]{16}", re.ASCII)
COLLECTOR_DOMAIN_PREFIX = "ca-collector-"


def _bad(detail):
    return K.RecordingError("recording_stream_invalid", detail)


def _ceil_ms(ns):
    return -(-ns // NS_PER_MS)


def _ns_text(epoch_ns):
    """UTC RFC 3339 with nine fraction digits (the observed lower bound, exactly)."""
    seconds, frac = divmod(epoch_ns, 1_000_000_000)
    return K._ms_text(seconds * 1000)[:-5] + f".{frac:09d}Z"


def _int(value, where, low=0, high=MAX_NS):
    if type(value) is not int or not low <= value <= high:
        raise _bad(f"{where} must be an integer in range")
    return value


# ------------------------------------------------------------------------------------- reading

def _manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise K.RecordingError("recording_manifest_invalid", "the manifest must have exactly the documented fields")
    if manifest["data_classification"] != "synthetic":
        raise K.RecordingError("recording_classification_refused", "only synthetic recordings are accepted")
    if manifest["provenance"] != "collector" or manifest["rv_comparison"] != rv.RV_COMPARISON:
        raise K.RecordingError("recording_manifest_invalid", "a 0.4 recording comes from the collector under the F3 rule")
    for field in ("recording_id", "source_id", "cluster_id"):
        if not isinstance(manifest[field], str) or not K._ID.fullmatch(manifest[field]):
            raise K.RecordingError("recording_manifest_invalid", f"{field} must be a lowercase identifier")
    if not isinstance(manifest["session_id"], str) or not SESSION_ID.fullmatch(manifest["session_id"]):
        raise K.RecordingError("recording_manifest_invalid", "session_id must be a generated session identity")
    clocks_ = manifest["clocks"]
    if not isinstance(clocks_, dict) or set(clocks_) != {"collector", "api_server"}:
        raise K.RecordingError("recording_manifest_invalid", "clocks must name the collector and the API server")
    collector, server = clocks_["collector"], clocks_["api_server"]
    if not isinstance(collector, dict) or set(collector) != {"clock_domain_id", "anchor_wall", "max_drift_ms",
                                                              "step_detected"} \
            or not isinstance(server, dict) or set(server) != {"clock_domain_id"}:
        raise K.RecordingError("recording_manifest_invalid", "clock entries must have exactly the documented fields")
    for domain in (collector["clock_domain_id"], server["clock_domain_id"]):
        if not isinstance(domain, str) or not K._ID.fullmatch(domain):
            raise K.RecordingError("recording_manifest_invalid", "clock_domain_id must be an identifier")
    if collector["clock_domain_id"] != COLLECTOR_DOMAIN_PREFIX + manifest["session_id"]:
        raise K.RecordingError("recording_manifest_invalid", "the collector clock domain must be the session's own")
    if collector["clock_domain_id"] == server["clock_domain_id"] or type(collector["step_detected"]) is not bool:
        raise K.RecordingError("recording_manifest_invalid", "the collector and API-server clocks are separate domains")
    anchor = collector["anchor_wall"]
    try:
        parsed = ti.parse_rfc3339(anchor) if isinstance(anchor, str) else None
    except ti.TimeError:
        parsed = None
    if parsed is None or not anchor.endswith("Z") or parsed.text_precision_ns != 1:
        raise K.RecordingError("recording_manifest_invalid", "anchor_wall must be RFC 3339 UTC with nine fraction digits")
    _int(collector["max_drift_ms"], "clocks.collector.max_drift_ms", 0, 10 ** 12)
    streams = manifest["streams"]
    if not isinstance(streams, list) or sorted(s.get("resource") if isinstance(s, dict) else None
                                               for s in streams) != sorted(QUERIES.values()):
        raise K.RecordingError("recording_manifest_invalid", "streams must list each of the four resources once")
    files = []
    for s in streams:
        if set(s) != {"resource", "parts"} or not isinstance(s["parts"], list) or not 1 <= len(s["parts"]) <= MAX_PARTS:
            raise K.RecordingError("recording_manifest_invalid", "a stream lists 1..48 parts")
        for part in s["parts"]:
            if not isinstance(part, dict) or set(part) != {"file", "sha256"} or not isinstance(part["file"], str) \
                    or not _PART.fullmatch(part["file"]) or not part["file"].startswith(f"streams/{s['resource']}-") \
                    or not isinstance(part["sha256"], str) or not K._HEX64.fullmatch(part["sha256"]):
                raise K.RecordingError("recording_path_refused", "a stream part needs streams/<resource>-<nnnn>.json")
            if part["file"] in files:
                raise K.RecordingError("recording_manifest_conflict", "a stream part is listed twice")
            files.append(part["file"])
    return files, parsed.epoch_ns


def _check_layout(root, files):
    """The directory holds exactly the manifest and the listed parts: no links, nothing else."""
    try:
        B._check_node(root, directory=True)
        expected = {K.MANIFEST, "streams"}
        with os.scandir(root) as it:
            for item in it:
                if item.is_symlink() or item.name not in expected:
                    raise K.RecordingError("recording_unexpected_entry", item.name)
        B._check_node(root / "streams", directory=True)
        names = {f.split("/", 1)[1] for f in files}
        with os.scandir(root / "streams") as it:
            for n, item in enumerate(it):
                if n > 4 * MAX_PARTS or item.is_symlink() or item.name not in names:
                    raise K.RecordingError("recording_unexpected_entry", item.name)
        for rel in files:
            if B._check_node(root / rel, directory=False).st_size > K.MAX_RESPONSE_BYTES:
                raise K.RecordingError("recording_file_too_large", Path(rel).name)
    except B.BundleError as exc:
        raise K.RecordingError(exc.code.replace("bundle_", "recording_"), str(exc)) from None


def _entries(root, stream):
    entries = []
    for n, part in enumerate(stream["parts"], 1):
        try:
            data = B._read(root / part["file"], K.MAX_RESPONSE_BYTES, part["sha256"])
            doc = canonical.loads(data, canonical.Limits(max_bytes=K.MAX_RESPONSE_BYTES))
        except B.BundleError as exc:
            raise K.RecordingError(exc.code.replace("bundle_", "recording_"), Path(part["file"]).name) from None
        except ContractError:
            raise K.RecordingError("recording_json_invalid", Path(part["file"]).name) from None
        if not isinstance(doc, dict) or set(doc) != {"resource", "part", "entries"} or doc["resource"] != stream["resource"] \
                or doc["part"] != n or not isinstance(doc["entries"], list):
            raise _bad("a stream part must name its resource and number")
        entries += doc["entries"]
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or entry.get("type") not in _ENTRY_KEYS or set(entry) != _ENTRY_KEYS[entry["type"]]:
            raise _bad("an entry has an unknown type or fields")
        if entry["seq"] != i:
            raise _bad("entries are numbered 1, 2, ... in order")
        _int(entry["segment"], "segment", 1, 10_000)
    return entries


def _absolute(entries, anchor_ns):
    """Entries with every ``*_ns`` offset turned into absolute collector-clock nanoseconds."""
    out = []
    for entry in entries:
        entry = dict(entry)
        for key, value in entry.items():
            if key.endswith("_ns") and value is not None:
                entry[key] = anchor_ns + _int(value, key, 0, MAX_OFFSET_NS)
        out.append(entry)
    return out


# ---------------------------------------------------------------------------------- deriving

class _Segment:
    def __init__(self, number, listing):
        self.number, self.listing = number, listing
        self.delivered = []        # (rv, entry) of events and bookmarks, in delivery order
        self.events = []           # event entries
        self.probes = []           # 200 probes with a resourceVersion
        self.end = None
        self.disconnects = 0
        self.bound = None


def _segments(entries, resource, namespace):
    """Validate the stream's structure and causality; return its segments in order."""
    segments, current, last_delivered, last_receipt = [], None, None, None
    for e in entries:
        kind = e["type"]
        if kind == "list":
            if current is not None and current.end is None:
                raise _bad("a new segment starts only after the previous one ended")
            if e["segment"] != len(segments) + 1:
                raise _bad("segments are numbered 1, 2, ... in order")
            for f in ("sent_ns", "first_page_ns", "last_page_ns"):
                if e[f] is not None:
                    _int(e[f], f)
            if e["outcome"] not in K.V3_OUTCOMES or not isinstance(e["items"], list):
                raise _bad("a list entry has an outcome and items")
            _int(e["pages"], "pages", 0, 100_000)
            _int(e["restarts"], "restarts", 0, 100)
            _int(e["withheld"], "withheld", 0, 10 ** 9)
            collected = e["outcome"] in ("consistent", "truncated")
            if collected:
                if None in (e["sent_ns"], e["first_page_ns"], e["last_page_ns"]) or e["http_status"] != 200 \
                        or not e["sent_ns"] <= e["first_page_ns"] <= e["last_page_ns"]:
                    raise _bad("a collected list has ordered send and receipt times")
                try:
                    rv.check(e["collection_resource_version"])
                except rv.ResourceVersionError as exc:
                    raise _bad(f"list resourceVersion: {exc.code}") from None
                for item in e["items"]:
                    _object(item, resource, namespace)
            elif e["items"] or e["collection_resource_version"] is not None:
                raise _bad("a failed list has no items or resourceVersion")
            current = _Segment(e["segment"], e)
            segments.append(current)
            last_delivered = e["collection_resource_version"] if collected else None
            last_receipt = e["last_page_ns"]
            if not collected:
                current.end = {"code": "list_failed", "at_ns": e["last_page_ns"]}
            continue
        if current is None or e["segment"] != current.number:
            raise _bad("every entry belongs to the current segment")
        if kind == "probe":
            _int(e["sent_ns"], "probe.sent_ns")
            _int(e["received_ns"], "probe.received_ns")
            if e["received_ns"] < e["sent_ns"]:
                raise _bad("a probe is received after it is sent")
            if e["http_status"] == 200 and e["resource_version"] is not None:
                try:
                    rv.check(e["resource_version"])
                except rv.ResourceVersionError as exc:
                    raise _bad(f"probe resourceVersion: {exc.code}") from None
                if current.listing["collection_resource_version"] is not None:
                    current.probes.append(e)
            elif e["resource_version"] is not None:
                raise _bad("a failed probe has no resourceVersion")
            continue
        if current.end is not None:
            raise _bad("nothing but probes follows the end of a segment")
        if kind == "watch_open":
            _int(e["sent_ns"], "watch_open.sent_ns")
            if e["from_resource_version"] != last_delivered:
                raise _bad("a watch starts or resumes exactly from the last delivered resourceVersion")
        elif kind in ("event", "bookmark"):
            received = _int(e["received_ns"], f"{kind}.received_ns")
            if last_receipt is not None and received < last_receipt:
                raise _bad("watch entries are received in order")
            last_receipt = received
            try:
                value = rv.check(e["resource_version"])
            except rv.ResourceVersionError as exc:
                raise _bad(f"{kind} resourceVersion: {exc.code}") from None
            order = rv.compare(value, last_delivered)
            if order < 0 or (order == 0 and kind == "event"):
                raise _bad("watch resourceVersions never go back, and events never repeat one")
            last_delivered = value
            current.delivered.append((value, e))
            if kind == "event":
                if e["event"] not in ("ADDED", "MODIFIED", "DELETED"):
                    raise _bad("an event is ADDED, MODIFIED or DELETED")
                if e["object"] is None:
                    if not isinstance(e["withheld"], str) or not _CODE.fullmatch(e["withheld"]):
                        raise _bad("a withheld event names a code")
                else:
                    if e["withheld"] is not None:
                        raise _bad("a kept event is not withheld")
                    meta = _object(e["object"], resource, namespace)
                    if meta.get("resourceVersion") != value:
                        raise _bad("an event object carries its entry's resourceVersion")
                current.events.append(e)
        elif kind == "disconnect":
            _int(e["at_ns"], "disconnect.at_ns")
            if not isinstance(e["code"], str) or not _CODE.fullmatch(e["code"]):
                raise _bad("a disconnect names a code")
            current.disconnects += 1
        elif kind == "end":
            _int(e["at_ns"], "end.at_ns")
            if e["code"] not in END_CODES:
                raise _bad("an end has a known code")
            current.end = e
    if current is not None and current.end is None:
        raise _bad("the last segment has an end")
    return segments


def _object(item, resource, namespace):
    if not isinstance(item, dict) or not isinstance(item.get("metadata"), dict):
        raise _bad("an object has metadata")
    K._refuse_secrets(item)
    meta = item["metadata"]
    if meta.get("namespace") != namespace:
        raise K.RecordingError("recording_namespace_mismatch", "a recorded object is outside the recording's namespace")
    if item.get("kind", ENTITY[resource]) != ENTITY[resource]:
        raise _bad("an object is of its stream's kind")
    return meta


def _proof(segment):
    """(latest proven probe, proving resourceVersion) of a collected segment, or (None, None)."""
    start_ns = segment.listing["first_page_ns"]
    start_rv = segment.listing["collection_resource_version"]
    best = None
    for probe in segment.probes:
        p = probe["resource_version"]
        if rv.compare(p, start_rv) < 0 or probe["sent_ns"] // NS_PER_MS <= _ceil_ms(start_ns):
            continue
        proving = next((value for value, _ in segment.delivered if rv.at_least(value, p)), None)
        if proving is not None and (best is None or probe["sent_ns"] > best[0]["sent_ns"]):
            best = (probe, proving)
    return best if best else (None, None)


def _lower_bound(segment, event_rv):
    """Send time of the latest consistent read of the segment with a resourceVersion below the event's."""
    lower = segment.listing["sent_ns"]
    for probe in segment.probes:
        if rv.compare(probe["resource_version"], event_rv) < 0 and probe["sent_ns"] > lower:
            lower = probe["sent_ns"]
    return lower


# ------------------------------------------------------------------------------- observations

def _observed(lower_ns, upper_ns, domain):
    width = upper_ns - lower_ns
    if not 1 <= width <= ti.MAX_PRECISION_NS:
        raise _bad("an observed bracket must be 1 ns to one day wide")
    return {"timestamp_kind": ev.OBSERVED_TIME, "raw": _ns_text(lower_ns), "clock_domain_id": domain,
            "declared_precision_ns": width}


class _State:
    """What the whole recording says about ReplicaSets and Deployment revisions (deterministic)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.replicasets = {}      # deployment uid -> {revision: rs}
        self.revisions = {}        # deployment uid -> last known revision
        self.seen = set()          # (uid, resourceVersion) already turned into evidence

    def learn_replicaset(self, item):
        try:
            _, by_deployment, _ = K._replicasets([item], self.ctx)
        except (K._ItemInvalid, K.RecordingError):
            return
        for uid, sets in by_deployment.items():
            for rs in sets:
                self.replicasets.setdefault(uid, {})[rs["revision"]] = rs


def _revision(item):
    meta = item.get("metadata") or {}
    value = (meta.get("annotations") or {}).get(K.REVISION_ANNOTATION)
    return int(value) if isinstance(value, str) and K._DIGITS.fullmatch(value) else None


def _convert_object(resource, item, state, change=True):
    """Observations of one object; raises K._ItemInvalid when it cannot.

    A Deployment *change* is a rollout only when its revision rises above the last known one; other
    Deployment changes (status or spec updates) are not converted and are counted. In a list state
    (``change=False``) a Deployment yields its rollout as in CA-P2-004e, unless that revision was
    already known (a relist), which is counted ``already_observed``."""
    ctx = state.ctx
    if resource == "pods":
        observations, out_of_scope = K._pods([item], ctx)
        if out_of_scope:
            raise K._ItemInvalid("out_of_scope")
        return observations
    if resource == "replicasets":
        observations, _, out_of_scope = K._replicasets([item], ctx)
        if out_of_scope:
            raise K._ItemInvalid("out_of_scope")
        return observations
    if resource == "events":
        return K._event_observations([item], ctx)
    uid = (item.get("metadata") or {}).get("uid")
    revision = _revision(item)
    previous = state.revisions.get(uid)
    if revision is None:
        raise K._ItemInvalid("revision_missing")
    state.revisions[uid] = max(revision, previous or 0)
    if previous is not None and revision <= previous:
        raise K._ItemInvalid("no_new_revision" if change else "already_observed")
    sets = [rs for _, rs in sorted(state.replicasets.get(uid, {}).items())]
    observations, notes = K._deployments([item], {uid: sets}, ctx)
    if not observations:
        raise K._ItemInvalid("no_previous_revision" if notes.get("no_previous_revision") else "rollout_unknown")
    return observations


def _change_observations(resource, event, observed, state):
    """(observations, None) or ([], reason) for one watch event entry."""
    if event["object"] is None:
        return [], event["withheld"]
    item = event["object"]
    meta = item["metadata"]
    key = (meta.get("uid"), event["resource_version"])
    if key in state.seen:
        return [], None  # already evidence (a relist met a version the watch delivered)
    if event["event"] == "DELETED":
        name, uid = meta.get("name"), meta.get("uid")
        if not isinstance(name, str) or not isinstance(uid, str):
            return [], "deleted_object_invalid"
        state.seen.add(key)
        return [K._observation("k8s_object_deleted", f"k8s:deleted/{state.ctx['namespace']}/{ENTITY[resource].lower()}/"
                               f"{name}@{event['resource_version']}", uid, event["resource_version"], ENTITY[resource],
                               state.ctx["namespace"], name, [{**observed, "timestamp_kind": "event"}, observed],
                               {"object_kind": ENTITY[resource]})], None
    if resource == "replicasets":
        state.learn_replicaset(item)
    try:
        observations = _convert_object(resource, item, state)
    except K._ItemInvalid as exc:
        return [], exc.code
    for observation in observations:
        observation["times"].append(observed)
    state.seen.add(key)
    return observations, None


# ------------------------------------------------------------------------------------- convert

def convert(root, manifest, manifest_sha):
    files, anchor_ns = _manifest(manifest)
    _check_layout(root, files)
    collector, server = manifest["clocks"]["collector"], manifest["clocks"]["api_server"]
    domain, server_domain = collector["clock_domain_id"], server["clock_domain_id"]
    ctx = {"namespace": manifest["namespace"], "source_id": manifest["source_id"], "clock": server_domain,
           "rv_pattern": re.compile(r"[1-9][0-9]{0,127}", re.ASCII)}
    if not isinstance(ctx["namespace"], str):
        raise K.RecordingError("recording_manifest_invalid", "namespace must be a string")
    streams = {s["resource"]: _segments(_absolute(_entries(root, s), anchor_ns), s["resource"], ctx["namespace"])
               for s in manifest["streams"]}

    times = [t for segs in streams.values() for s in segs for t in
             [s.listing["sent_ns"], s.listing["last_page_ns"], s.end.get("at_ns")]
             + [e["received_ns"] for e in s.events] + [p["received_ns"] for p in s.probes] if t is not None]
    if not times:
        raise K.RecordingError("recording_manifest_invalid", "a recording has at least one timed entry")
    window = (min(times) // NS_PER_MS, _ceil_ms(max(times)) + 1)
    if window[1] - window[0] > LIMITS["max_window_ms"]:
        raise K.RecordingError("recording_manifest_invalid", "a recording spans at most one hour")

    recording_id = manifest["recording_id"]
    try:
        clock_records = [
            ti.clock_domain(domain, ti.UNKNOWN, continuity=ti.STEP_DECLARED if collector["step_detected"]
                            else ti.CONTINUOUS).to_record(),
            ti.clock_domain(server_domain, ti.UNKNOWN).to_record()]
        registry_record = {"contract_version": SOURCE_REGISTRY_VERSION, "registry_id": f"{recording_id}-sources",
                           "sources": [{"source_id": ctx["source_id"], "source_kind": "kubernetes_api",
                                        "cluster_id": manifest["cluster_id"], "namespace": ctx["namespace"],
                                        "clock_domain_ids": sorted([domain, server_domain]),
                                        "query_ids": sorted(QUERIES)}]}
        registry = SourceRegistry.from_record(registry_record)
        clocks.declare(registry, clock_records)
    except (ContractError, clocks.ClockDeclarationError) as exc:
        raise K.RecordingError("recording_manifest_invalid", getattr(exc, "code", "clock_invalid")) from None
    plan_record = {"contract_version": pl.RUN_PLAN_VERSION, "plan_id": recording_id, "registry_id": registry.registry_id,
                   "registry_digest": registry.digest,
                   "window": {"start": K._ms_text(window[0]), "end": K._ms_text(window[1])},
                   "expected_acquisitions": [{"source_id": ctx["source_id"], "query_id": q, "mandatory": MANDATORY[q]}
                                             for q in sorted(QUERIES)],
                   "contract_versions": pl.required_contract_versions(ev.KIND_REGISTRY_VERSION_V3),
                   "rule_versions": required_rule_versions(), "synthesis_mode": "disabled", "limits": dict(LIMITS)}
    try:
        plan = pl.RunPlan.from_record(plan_record, registry)
    except ContractError as exc:
        raise K.RecordingError("recording_manifest_invalid", exc.code) from None

    state = _State(ctx)
    for segment in streams["replicasets"]:  # rollouts need ReplicaSet templates, which never change
        for item in segment.listing["items"]:
            state.learn_replicaset(item)
        for event in segment.events:
            if event["object"] is not None and event["event"] != "DELETED":
                state.learn_replicaset(event["object"])

    acquisitions, batches = [], []
    for query in sorted(QUERIES):
        resource = QUERIES[query]
        entry, records = _acquisition(plan, ctx, domain, manifest["session_id"], query, resource,
                                      streams[resource], state)
        for record in records:
            observations = record["observations"]
            for observation in observations:  # the evidence contract, before anything is written
                ev.observe(observation, source_id=ctx["source_id"], registry=registry,
                           delivery={"query_id": query, "batch_id": "check", "attempt": 1},
                           kind_registry_version=ev.KIND_REGISTRY_VERSION_V3)
        acquisitions.append(entry)
        batches += records
    for record in batches:
        try:
            acq.decode_batch(record, plan, registry)
        except ContractError as exc:
            raise K.RecordingError("recording_conversion_invalid", exc.code) from None
    verified = sum(a["verified_coverage_ms"] for a in acquisitions)
    report = {"contract_version": REPORT_VERSION, "recording_id": recording_id, "recording_sha256": manifest_sha,
              "recording_version": RECORDING_VERSION, "kind_registry_version": ev.KIND_REGISTRY_VERSION_V3,
              "bundle_id": recording_id, "source_id": ctx["source_id"], "cluster_id": manifest["cluster_id"],
              "namespace": ctx["namespace"], "plan_digest": plan.digest, "session_id": manifest["session_id"],
              "collector_clock": {"clock_domain_id": domain, "step_detected": collector["step_detected"],
                                  "max_drift_ms": collector["max_drift_ms"]},
              "api_server_clock": "unknown", "rv_comparison": rv.RV_COMPARISON, "verified_coverage_ms": verified,
              "acquisitions": acquisitions,
              "note": ("Coverage is verified only between the receipt of a consistent list and the send time of a "
                       "consistent-read probe that the watch later reached; bookmarks, events or an open connection "
                       "alone cover nothing. Withheld or unconverted changes make a segment partial "
                       "(changes_withheld). Every other period is a gap.")}
    canonical.canonical_bytes(report)
    return K.Conversion(recording_id, registry_record, plan_record, tuple(clock_records), tuple(batches), report)


def _acquisition(plan, ctx, domain, session_id, query, resource, segments, state):
    stem = query.replace("k8s.", "")
    entry = {"query_id": query, "resource": resource, "segments": [], "verified_coverage_ms": 0,
             "observations": 0, "withheld": {}, "unconverted": {}, "outcomes": []}
    plans = []   # (outcome, reason, coverage_ms, observations, basis, cursor_after, truncated)
    first = segments[0] if segments else None
    if first is None or first.listing["outcome"] not in ("consistent", "truncated"):
        code = first.listing["outcome"] if first else "invalid"
        outcome, reason = K._V3_FAILURES.get(code, (acq.FAILED, "source_unavailable"))
        records = _records(plan, ctx, query, stem, [(outcome, reason, None, [], None, None, False)])
        entry["outcomes"] = [outcome]
        entry["segments"].append({"segment": 1, "list": code, "proven": False})
        return entry, records

    for segment in segments:
        listing = segment.listing
        info = {"segment": segment.number, "list": listing["outcome"], "reconnects": segment.disconnects,
                "end": segment.end["code"], "proven": False, "probes": len(segment.probes)}
        entry["segments"].append(info)
        if listing["outcome"] not in ("consistent", "truncated"):
            continue  # a failed relist: the rest of the window is a gap
        start_rv = listing["collection_resource_version"]
        # The list state: a state at an unplaced moment, never coverage of changes.
        baseline, withheld = [], listing["withheld"]
        for item in listing["items"]:
            meta = item["metadata"]
            key = (meta.get("uid"), meta.get("resourceVersion"))
            if key in state.seen:
                continue
            try:
                baseline += _convert_object(resource, item, state, change=False)
                state.seen.add(key)
            except K._ItemInvalid as exc:
                entry["unconverted"][exc.code] = entry["unconverted"].get(exc.code, 0) + 1
        if withheld:
            entry["withheld"]["list"] = entry["withheld"].get("list", 0) + withheld
        plans.append((acq.PARTIAL, "page_limit" if listing["outcome"] == "truncated" else "continuity_lost",
                      (listing["sent_ns"] // NS_PER_MS, _ceil_ms(listing["first_page_ns"]) + 1), baseline, None,
                      None, listing["outcome"] == "truncated"))
        if listing["outcome"] == "truncated":
            continue  # an incomplete starting state cannot anchor continuity

        probe, proving = _proof(segment)
        proven, tail, missing = [], [], 0
        for event in segment.events:
            lower = _lower_bound(segment, event["resource_version"])
            observed = _observed(lower, event["received_ns"], domain)
            observations, reason = _change_observations(resource, event, observed, state)
            in_proof = proving is not None and rv.compare(event["resource_version"], proving) <= 0
            if reason:
                bucket = entry["withheld"] if event["object"] is None else entry["unconverted"]
                bucket[reason] = bucket.get(reason, 0) + 1
                if in_proof:
                    missing += 1
            (proven if in_proof else tail).extend(observations)
        last_ns = max([segment.end["at_ns"]] + [e["received_ns"] for e in segment.events])
        if probe is not None:
            start_ms, end_ms = _ceil_ms(listing["first_page_ns"]), probe["sent_ns"] // NS_PER_MS
            coverage = (start_ms, end_ms)
            if missing:
                plans.append((acq.PARTIAL, "changes_withheld", coverage, proven, None, None, False))
            else:
                basis = {"kind": acq.WATCH_CONTINUITY, "resource_type": RESOURCE_TYPES[resource],
                         "session_id": session_id, "clock_domain_id": domain, "rv_comparison": rv.RV_COMPARISON,
                         "start_anchor": {"kind": "list_first_page_received", "at": K._ms_text(start_ms),
                                          "resource_version": start_rv},
                         "end_anchor": {"kind": "probe_sent", "at": K._ms_text(end_ms),
                                        "resource_version": probe["resource_version"],
                                        "proven_by_resource_version": proving}}
                plans.append((acq.COMPLETE, None, coverage, proven, basis, f"rv:{proving}", False))
                info["proven"] = True
                entry["verified_coverage_ms"] += end_ms - start_ms
            tail_start = end_ms
        else:
            tail_start = _ceil_ms(listing["first_page_ns"])
        limited = segment.end["code"] in ("event_limit", "buffer_limit")
        if tail or limited or probe is None:
            reason = "event_limit" if limited else "continuity_unproven"
            tail_end = max(_ceil_ms(last_ns) + 1, tail_start + 1)
            plans.append((acq.PARTIAL, reason, (tail_start, tail_end), tail, None, None, limited))
    records = _records(plan, ctx, query, stem, plans)
    entry["outcomes"] = sorted({r["outcome"] for r in records})
    entry["observations"] = sum(len(r["observations"]) for r in records)
    return entry, records


def _records(plan, ctx, query, stem, plans):
    per_batch = LIMITS["max_observations_per_batch"]
    records, before, n = [], None, 0
    for outcome, reason, coverage_ms, observations, basis, after, truncated in plans:
        observations = K._sort(observations)
        chunks = [observations[i:i + per_batch] for i in range(0, len(observations), per_batch)] or [[]]
        for chunk in chunks:
            n += 1
            chunk_outcome = outcome
            if outcome in (acq.COMPLETE, acq.EMPTY):
                chunk_outcome = acq.COMPLETE if chunk else acq.EMPTY
            coverage = None
            if coverage_ms is not None:
                lo = max(coverage_ms[0], plan.window_start_ms)
                hi = min(max(coverage_ms[1], lo + 1), plan.window_end_ms)
                coverage = {"start": K._ms_text(lo), "end": K._ms_text(hi)}
            cursor_after = after or f"{stem}-{n}"
            records.append({
                "contract_version": acq.BATCH_VERSION_V2, "plan_digest": plan.digest, "source_id": ctx["source_id"],
                "query_id": query, "batch_key": f"{stem}-{n}", "sequence": n, "outcome": chunk_outcome,
                "reason": reason, "coverage": coverage, "cursor": {"before": before, "after": cursor_after},
                "truncation": {"truncated": bool(truncated), "reason": "event_limit" if truncated and reason == "event_limit"
                               else ("page_limit" if truncated else None), "omitted_count": None},
                "observations": chunk, "coverage_basis": basis if chunk_outcome in (acq.COMPLETE, acq.EMPTY) else None,
                "delivery": {"attempt": 1}})
            before = cursor_after
    return records


def verify_bundle(recording_dir, bundle_dir):
    """Replay check: re-derive the bundle from the recording and require byte-identical files."""
    conversion = K.convert(recording_dir, ev.KIND_REGISTRY_VERSION_V3)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ca-replay-") as tmp:
        fresh = Path(tmp) / "bundle"
        conversion.write_bundle(fresh)
        expected = {p.relative_to(fresh).as_posix(): p.read_bytes() for p in sorted(fresh.rglob("*")) if p.is_file()}
    given_root = Path(bundle_dir)
    given = {p.relative_to(given_root).as_posix(): p.read_bytes() for p in sorted(given_root.rglob("*")) if p.is_file()}
    if given != expected:
        raise K.RecordingError("replay_mismatch", "the bundle is not the recording's derivation")
    return conversion


def recording_digest(files):
    """SHA-256 over a recording's {relative path: bytes}, for reports."""
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode() + b"\0" + hashlib.sha256(files[rel]).digest())
    return h.hexdigest()
