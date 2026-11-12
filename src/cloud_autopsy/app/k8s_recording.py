"""Recorded Kubernetes evidence adapter, ``ca-k8s-recording/0.1-provisional`` (CA-P2-004c, provisional).

Strictly offline. It reads a directory of **recorded** Kubernetes API list responses (synthetic
only in this slice) and converts them into the existing contracts: a source registry, a run plan,
a clock declaration and acquisition batches, written as an evidence bundle
(``ca-investigation-bundle/0.1-provisional``) that the existing bundle loader and creation path
accept. It opens no network connection and has no Kubernetes client.

Layout::

  recording.json               the manifest (below)
  responses/<name>.json        one recorded list response per resource, exactly as listed

  recording.json = {
    "contract_version": "ca-k8s-recording/0.1-provisional",
    "recording_id": "<identifier>", "data_classification": "synthetic",
    "source_id": "<identifier>", "cluster_id": "<identifier>", "namespace": "<namespace>",
    "window": {"start": "<RFC 3339 Z>", "end": "<RFC 3339 Z>"},
    "clock": {"clock_domain_id": "<identifier>", "status": "declared" | "unknown",
              "offset_ms": int | null, "offset_uncertainty_ms": int | null,
              "continuity": "declared_continuous" | "step_declared" | "unknown"},
    "responses": [{"resource": "pods" | "replicasets" | "deployments" | "events" | "configmaps",
                   "file": "responses/<name>.json" | null, "sha256": "<64 hex>" | null,
                   "http_status": int, "error": null | "timeout" | "rate_limited" | "unavailable",
                   "coverage": {"start": ..., "end": ...} | null}, ...]}

What is converted (observation kinds 0.1, unchanged):

  k8s.pods          pods          -> ``pod``
  k8s.deployments   deployments   -> ``deployment_rollout`` (from a Deployment and its two newest
                    + replicasets    ReplicaSet revisions) and ``replicaset``

What is **not** converted: ``events`` and ``configmaps`` are parsed and validated, then classified
``unsupported_conversion`` in the conversion report with their counts. Observation kinds 0.1 has no
Kubernetes Event kind, and its only ConfigMap kind needs configuration values, which are never read.
No acquisition is planned for them, so no coverage is claimed for them and nothing from them can
be cited as evidence.

Honesty rules:
- A converted acquisition is ``complete`` / ``empty`` only for an HTTP 200 response with a declared
  coverage and no continuation token. A continuation token makes it ``partial`` (``page_limit``,
  truncated). 401/403 is ``denied``; 429 ``rate_limited``; a timeout ``timeout``; any other
  failure, or a resource that was not recorded at all, ``source_unavailable``; a body that is not a
  valid list of the expected kind, or any item that cannot be converted, ``invalid_response``.
  Failed and denied acquisitions carry no coverage and no observations.
- Timestamps are kept as raw text with their declared precision (seconds unless the text has a
  fraction); nothing is reordered or inferred. The clock is what the recording declares.
- Items whose controller owner is outside the query's scope (a Pod not owned by a ReplicaSet, a
  ReplicaSet not owned by a Deployment) are counted ``out_of_scope`` in the report, never dropped
  silently.

Refused outright (``RecordingError``, nothing written): anything but synthetic classification;
unknown or duplicate manifest fields or resources; any Secret resource or object; an object in
another namespace; unsafe paths, links or unlisted files; digests that do not match; oversize files.
Messages and the report carry codes and counts, never recorded values.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..contracts import acquisition as acq
from ..contracts import canonical
from ..contracts import evidence as ev
from ..contracts import plan as pl
from ..contracts import timeinterval as ti
from ..contracts.errors import ContractError
from ..contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry
from ..engine import clocks, required_rule_versions
from . import bundle as B

RECORDING_VERSION = "ca-k8s-recording/0.1-provisional"
REPORT_VERSION = "ca-k8s-conversion-report/0.1-provisional"
MANIFEST = "recording.json"
MAX_MANIFEST_BYTES = 65_536
MAX_RESPONSE_BYTES = canonical.CEILING_BYTES
UNSUPPORTED_CONVERSION = "unsupported_conversion"
# Converted query -> recorded resources it needs (all of them, for a complete acquisition).
QUERIES = {"k8s.deployments": ("deployments", "replicasets"), "k8s.pods": ("pods",)}
UNSUPPORTED = ("configmaps", "events")
RESOURCES = {  # resource -> (accepted apiVersions, list kind, item kind)
    "pods": (("v1",), "PodList", "Pod"),
    "replicasets": (("apps/v1",), "ReplicaSetList", "ReplicaSet"),
    "deployments": (("apps/v1",), "DeploymentList", "Deployment"),
    "events": (("v1", "events.k8s.io/v1"), "EventList", "Event"),
    "configmaps": (("v1",), "ConfigMapList", "ConfigMap"),
}
LIMITS = {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 10, "max_batch_deliveries": 100,
          "max_observations_per_batch": 100, "max_observations_total": 1_000, "max_batch_bytes": 1_048_576,
          "max_total_bytes": 10_000_000}
REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
_MANIFEST_KEYS = {"contract_version", "recording_id", "data_classification", "source_id", "cluster_id",
                  "namespace", "window", "clock", "responses"}
_RESPONSE_KEYS = {"resource", "file", "sha256", "http_status", "error", "coverage"}
_CLOCK_KEYS = {"clock_domain_id", "status", "offset_ms", "offset_uncertainty_ms", "continuity"}
_ERRORS = ("timeout", "rate_limited", "unavailable")
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,47}", re.ASCII)  # leaves room for derived identifiers
_PATH = re.compile(r"responses/[a-z0-9][a-z0-9_-]{0,63}\.json", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_DIGITS = re.compile(r"[0-9]{1,20}", re.ASCII)
_EVENT_REASON = re.compile(r"[A-Za-z][A-Za-z0-9]{0,127}", re.ASCII)
_FRACTION = re.compile(r"\.([0-9]{1,9})")


class RecordingError(ValueError):
    """The whole recording was refused. ``code`` is stable; messages never echo recorded values."""

    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class _ItemInvalid(ValueError):
    """One recorded object could not be converted; its response becomes ``invalid_response``."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _OutOfScope(Exception):
    pass


@dataclass(frozen=True)
class Conversion:
    bundle_id: str
    registry_record: dict
    plan_record: dict
    clock_records: tuple
    batch_records: tuple
    report: dict

    def report_bytes(self):
        return canonical.canonical_bytes(self.report)

    def write_bundle(self, directory):
        return B.write(directory, self.bundle_id, self.registry_record, self.plan_record, list(self.clock_records),
                       list(self.batch_records))


def export_example(directory, name):
    """Write one synthetic example recording into ``directory``, which must not exist."""
    from ..synthetic import k8s_recordings
    root = Path(directory)
    root.mkdir(parents=False, exist_ok=False)
    for rel, data in sorted(k8s_recordings.recording_files(name).items()):
        (root / rel).parent.mkdir(exist_ok=True)
        B._create(root / rel, data)
    return root


# ------------------------------------------------------------------------------------ reading

def _read_manifest(root):
    try:
        data = B._read(root / MANIFEST, MAX_MANIFEST_BYTES)
    except B.BundleError as exc:
        raise RecordingError(exc.code.replace("bundle_", "recording_"), MANIFEST) from None
    try:
        manifest = canonical.loads(data, canonical.Limits(max_bytes=MAX_MANIFEST_BYTES))
    except ContractError as exc:
        raise RecordingError("recording_json_invalid", f"{MANIFEST}: {exc.code}") from None
    return manifest, hashlib.sha256(data).hexdigest()


def _check_layout(root, files):
    """The directory holds exactly the manifest and the listed response files: no links, nothing else."""
    try:
        B._check_node(root, directory=True)
        expected = {MANIFEST} | set(files)
        dirs = {"responses"} if files else set()
        for directory in [""] + sorted(dirs):
            here = root / directory if directory else root
            B._check_node(here, directory=True)
            with os.scandir(here) as it:
                for n, item in enumerate(it):
                    if n > 64:
                        raise RecordingError("recording_too_many_entries")
                    rel = f"{directory}/{item.name}" if directory else item.name
                    if item.is_symlink():
                        raise RecordingError("recording_link_refused", item.name)
                    if rel in dirs and not directory:
                        continue
                    if rel not in expected:
                        raise RecordingError("recording_unexpected_entry", item.name)
        for rel in files:
            info = B._check_node(root / rel, directory=False)
            if info.st_size > MAX_RESPONSE_BYTES:
                raise RecordingError("recording_file_too_large", Path(rel).name)
    except B.BundleError as exc:
        raise RecordingError(exc.code.replace("bundle_", "recording_"), str(exc)) from None


def _window(value, field):
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise RecordingError("recording_manifest_invalid", f"{field} must have exactly start and end")
    try:
        start, end = pl.exact_ms(value["start"], f"{field}.start"), pl.exact_ms(value["end"], f"{field}.end")
    except ContractError:
        raise RecordingError("recording_manifest_invalid", f"{field} must be RFC 3339 UTC timestamps") from None
    if start >= end:
        raise RecordingError("recording_manifest_invalid", f"{field} must be a non-empty interval")
    return start, end


def _validate_manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise RecordingError("recording_manifest_invalid", "the manifest must have exactly the documented fields")
    if manifest["contract_version"] != RECORDING_VERSION:
        raise RecordingError("recording_version_unsupported")
    if manifest["data_classification"] != "synthetic":
        raise RecordingError("recording_classification_refused", "only synthetic recordings are accepted")
    for field in ("recording_id", "source_id", "cluster_id"):
        if not isinstance(manifest[field], str) or not _ID.fullmatch(manifest[field]):
            raise RecordingError("recording_manifest_invalid", f"{field} must be a lowercase identifier")
    window = _window(manifest["window"], "window")
    clock = manifest["clock"]
    if not isinstance(clock, dict) or set(clock) != _CLOCK_KEYS:
        raise RecordingError("recording_manifest_invalid", "clock must have exactly the documented fields")
    responses = manifest["responses"]
    if not isinstance(responses, list) or not 1 <= len(responses) <= len(RESOURCES) + 4:
        raise RecordingError("recording_manifest_invalid", "responses must be a short list")
    seen, files = {}, []
    for i, r in enumerate(responses):
        if not isinstance(r, dict) or set(r) != _RESPONSE_KEYS:
            raise RecordingError("recording_manifest_invalid", f"responses[{i}] must have exactly the documented fields")
        resource = r["resource"]
        if resource == "secrets" or (isinstance(resource, str) and "secret" in resource.lower()):
            raise RecordingError("recording_sensitive_refused", "Secret resources are never accepted")
        if resource not in RESOURCES:
            raise RecordingError("recording_resource_refused", f"responses[{i}].resource is not supported")
        if resource in seen:
            raise RecordingError("recording_manifest_conflict", f"responses[{i}] repeats a resource")
        status, error, path, digest = r["http_status"], r["error"], r["file"], r["sha256"]
        if type(status) is not int or not 100 <= status <= 599:
            raise RecordingError("recording_manifest_invalid", f"responses[{i}].http_status must be an HTTP status")
        if error is not None and error not in _ERRORS:
            raise RecordingError("recording_manifest_invalid", f"responses[{i}].error is not a supported value")
        if status == 200 and error is None:
            if not isinstance(path, str) or not _PATH.fullmatch(path) or not isinstance(digest, str) \
                    or not _HEX64.fullmatch(digest):
                raise RecordingError("recording_path_refused", f"responses[{i}] needs a responses/<name>.json file and sha256")
            if path in files:
                raise RecordingError("recording_manifest_conflict", f"responses[{i}] repeats a file")
            coverage = _window(r["coverage"], f"responses[{i}].coverage")
            if not window[0] <= coverage[0] < coverage[1] <= window[1]:
                raise RecordingError("recording_manifest_invalid", f"responses[{i}].coverage must lie inside the window")
            files.append(path)
        elif (path, digest, r["coverage"]) != (None, None, None):
            raise RecordingError("recording_manifest_invalid", f"responses[{i}]: a failed response has no file or coverage")
        seen[resource] = r
    return seen, files


# --------------------------------------------------------------------------- object checks

def _obj(value, code):
    if not isinstance(value, dict):
        raise _ItemInvalid(code)
    return value


def _text(value, code, pattern=None, max_len=253):
    if not isinstance(value, str) or not 1 <= len(value) <= max_len or (pattern and not pattern.fullmatch(value)):
        raise _ItemInvalid(code)
    return value


def _refuse_secrets(value, depth=0):
    """No Secret object may appear anywhere in a recorded response."""
    if depth > 64:
        raise _ItemInvalid("item_too_deep")
    if isinstance(value, dict):
        if value.get("kind") in ("Secret", "SecretList"):
            raise RecordingError("recording_sensitive_refused", "a Secret object appears in a recorded response")
        for key, item in value.items():
            if key in ("data", "binaryData", "stringData"):  # configuration values are never inspected
                continue
            _refuse_secrets(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _refuse_secrets(item, depth + 1)


def _metadata(item, namespace):
    meta = _obj(item.get("metadata"), "metadata_missing")
    if meta.get("namespace") != namespace:
        # Namespace isolation: a recording binds exactly one namespace.
        raise RecordingError("recording_namespace_mismatch", "a recorded object is outside the recording's namespace")
    return {"name": _text(meta.get("name"), "name_invalid", re.compile(r"[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?")),
            "uid": _text(meta.get("uid"), "uid_invalid", re.compile(r"[A-Za-z0-9-]{1,128}")),
            "resource_version": _text(meta.get("resourceVersion"), "resource_version_invalid", _DIGITS),
            "created": _text(meta.get("creationTimestamp"), "timestamp_invalid", max_len=64),
            "owners": meta.get("ownerReferences") or [], "annotations": meta.get("annotations") or {}}


def _controller(meta, kind):
    owners = [o for o in meta["owners"] if isinstance(o, dict) and o.get("controller") is True]
    if len(owners) > 1:
        raise _ItemInvalid("owner_ambiguous")
    if not owners or owners[0].get("kind") != kind:
        raise _OutOfScope()
    return (_text(owners[0].get("name"), "owner_invalid"), _text(owners[0].get("uid"), "owner_invalid", max_len=128))


def _time(raw, clock_domain, kind="event"):
    match = _FRACTION.search(raw)
    precision = 10 ** (9 - len(match.group(1))) if match else ti.NS_PER_S
    return {"timestamp_kind": kind, "raw": raw, "clock_domain_id": clock_domain, "declared_precision_ns": precision}


def _observation(kind, source_ref, uid, version, entity_kind, namespace, name, times, attributes):
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": source_ref, "observation_kind": kind,
            "source_uid": uid, "source_version": version,
            "entity": {"kind": entity_kind, "namespace": namespace, "name": name}, "times": times,
            "attributes": attributes}


def _single_container(template):
    spec = _obj(_obj(template, "template_invalid").get("spec"), "template_invalid")
    containers = spec.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise _ItemInvalid("not_single_container")
    container = _obj(containers[0], "template_invalid")
    return spec, container, _text(container.get("image"), "image_invalid", max_len=512)


def _config_refs(spec):
    """ConfigMap names a pod spec references (volumes, envFrom, env valueFrom); never their values."""
    refs = set()
    for volume in spec.get("volumes") or []:
        if isinstance(volume, dict) and isinstance(volume.get("configMap"), dict):
            refs.add(_text(volume["configMap"].get("name"), "configmap_ref_invalid"))
    for container in spec.get("containers") or []:
        for source in (container.get("envFrom") or []) if isinstance(container, dict) else []:
            if isinstance(source, dict) and isinstance(source.get("configMapRef"), dict):
                refs.add(_text(source["configMapRef"].get("name"), "configmap_ref_invalid"))
        for env in (container.get("env") or []) if isinstance(container, dict) else []:
            ref = env.get("valueFrom", {}).get("configMapKeyRef") if isinstance(env, dict) and isinstance(env.get("valueFrom"), dict) else None
            if isinstance(ref, dict):
                refs.add(_text(ref.get("name"), "configmap_ref_invalid"))
    return sorted(refs)


# ----------------------------------------------------------------------------- converters

def _pods(items, ctx):
    observations, out_of_scope = [], 0
    for item in items:
        meta = _metadata(item, ctx["namespace"])
        try:
            owner, _ = _controller(meta, "ReplicaSet")
        except _OutOfScope:
            out_of_scope += 1
            continue
        spec, status = _obj(item.get("spec"), "spec_missing"), _obj(item.get("status"), "status_missing")
        node = _text(spec.get("nodeName"), "node_missing")
        statuses = status.get("containerStatuses")
        if not isinstance(statuses, list) or not statuses:
            raise _ItemInvalid("container_statuses_missing")
        restarts = 0
        for s in statuses:
            count = _obj(s, "container_status_invalid").get("restartCount")
            if type(count) is not int or count < 0:
                raise _ItemInvalid("restart_count_invalid")
            restarts += count
        volumes = {}
        for volume in spec.get("volumes") or []:
            if isinstance(volume, dict) and isinstance(volume.get("configMap"), dict):
                volumes[_text(volume.get("name"), "volume_invalid")] = _text(volume["configMap"].get("name"), "configmap_ref_invalid")
        mounts = set()
        for container in spec.get("containers") or []:
            for mount in _obj(container, "container_invalid").get("volumeMounts") or []:
                mount = _obj(mount, "mount_invalid")
                if mount.get("name") in volumes:
                    mounts.add((volumes[mount["name"]], _text(mount.get("mountPath"), "mount_invalid", max_len=1024),
                                bool(mount.get("subPath"))))
        name = meta["name"]
        observations.append(_observation(
            "pod", f"k8s:pod/{ctx['namespace']}/{name}@{meta['resource_version']}", meta["uid"], meta["resource_version"],
            "Pod", ctx["namespace"], name, [_time(meta["created"], ctx["clock"])],
            {"owner_replicaset": owner, "node": node, "restart_count": restarts,
             "configmap_volumes": [{"configmap": c, "mount_path": p, "sub_path": s} for c, p, s in sorted(mounts)]}))
    return observations, out_of_scope


def _replicasets(items, ctx):
    """ReplicaSets owned by a Deployment: (observations, {deployment uid: [(revision, rs)]}, out_of_scope)."""
    observations, by_deployment, out_of_scope = [], {}, 0
    for item in items:
        meta = _metadata(item, ctx["namespace"])
        try:
            owner, owner_uid = _controller(meta, "Deployment")
        except _OutOfScope:
            out_of_scope += 1
            continue
        revision = _text(_obj(meta["annotations"], "annotations_invalid").get(REVISION_ANNOTATION), "revision_missing", _DIGITS)
        spec = _obj(item.get("spec"), "spec_missing")
        pod_spec, _, image = _single_container(spec.get("template"))
        rs = {"name": meta["name"], "revision": int(revision), "image": image, "created": meta["created"],
              "config_refs": _config_refs(pod_spec), "template": spec.get("template")}
        by_deployment.setdefault(owner_uid, []).append(rs)
        observations.append(_observation(
            "replicaset", f"k8s:replicaset/{ctx['namespace']}/{meta['name']}@{meta['resource_version']}", meta["uid"],
            meta["resource_version"], "ReplicaSet", ctx["namespace"], meta["name"], [_time(meta["created"], ctx["clock"])],
            {"owner_deployment": owner, "revision": revision, "image": image}))
    return observations, by_deployment, out_of_scope


def _changed_fields(old, new):
    """Changed pod-template paths between two ReplicaSet templates (only these, never values)."""
    _, old_c, _ = _single_container(old["template"])
    _, new_c, _ = _single_container(new["template"])
    fields = set()
    if old["image"] != new["image"]:
        fields.add(f"spec.template.spec.containers[{_text(new_c.get('name'), 'container_name_invalid', max_len=63)}].image")
    if old["config_refs"] != new["config_refs"]:
        fields.add("spec.template.spec.configmap_refs")

    def rest(template):  # the template without images and the controller-added pod-template-hash label
        t = canonical.loads(canonical.canonical_bytes(template))
        for c in t.get("spec", {}).get("containers", []):
            c.pop("image", None)
        t.get("metadata", {}).get("labels", {}).pop("pod-template-hash", None)
        return canonical.canonical_bytes(t)

    if rest(old["template"]) != rest(new["template"]) and "spec.template.spec.configmap_refs" not in fields:
        fields.add("spec.template")
    return sorted(fields)


def _deployments(items, replicasets, ctx):
    observations, notes = [], {"no_previous_revision": 0}
    for item in items:
        meta = _metadata(item, ctx["namespace"])
        revision = int(_text(_obj(meta["annotations"], "annotations_invalid").get(REVISION_ANNOTATION),
                             "revision_missing", _DIGITS))
        owned = sorted(replicasets.get(meta["uid"], []), key=lambda r: r["revision"])
        if len({r["revision"] for r in owned}) != len(owned):
            raise _ItemInvalid("replicaset_revision_duplicate")
        new = [r for r in owned if r["revision"] == revision]
        if not new:
            raise _ItemInvalid("rollout_replicaset_missing")
        older = [r for r in owned if r["revision"] < revision]
        if not older:
            notes["no_previous_revision"] += 1  # no rollout to describe; the ReplicaSet is still evidence
            continue
        new, old = new[0], older[-1]
        times = [_time(new["created"], ctx["clock"])]
        for condition in _obj(item.get("status") or {}, "status_invalid").get("conditions") or []:
            if isinstance(condition, dict) and condition.get("type") == "Progressing" \
                    and condition.get("reason") == "NewReplicaSetAvailable" and isinstance(condition.get("lastUpdateTime"), str):
                times.append(_time(condition["lastUpdateTime"], ctx["clock"], "completed"))
        name = meta["name"]
        observations.append(_observation(
            "deployment_rollout", f"k8s:deployment/{ctx['namespace']}/{name}@rev{revision}", meta["uid"],
            meta["resource_version"], "Deployment", ctx["namespace"], name, times,
            {"revision": str(revision), "previous_revision": str(old["revision"]),
             "changed_fields": _changed_fields(old, new), "image_before": old["image"], "image_after": new["image"],
             "config_refs_before": old["config_refs"], "config_refs_after": new["config_refs"],
             "old_replicaset": old["name"], "new_replicaset": new["name"]}))
    return observations, notes


def _events(items, ctx):
    """Validated, counted, never converted: {"<involved kind>/<type>": count}."""
    counts = {}
    for item in items:
        _metadata(item, ctx["namespace"])
        involved = _obj(item.get("involvedObject") or item.get("regarding"), "involved_object_missing")
        if involved.get("namespace") not in (None, ctx["namespace"]):
            raise RecordingError("recording_namespace_mismatch", "an event concerns another namespace")
        kind = _text(involved.get("kind"), "involved_kind_invalid", re.compile(r"[A-Z][A-Za-z]{0,62}"))
        event_type = item.get("type")
        if event_type not in ("Normal", "Warning"):
            raise _ItemInvalid("event_type_invalid")
        _text(item.get("reason"), "event_reason_invalid", _EVENT_REASON)
        counts[f"{kind}/{event_type}"] = counts.get(f"{kind}/{event_type}", 0) + 1
    return {k: counts[k] for k in sorted(counts)}


def _configmaps(items, ctx):
    """Metadata only, never converted: the number of ConfigMaps and of data keys. Values are not read."""
    keys = 0
    for item in items:
        _metadata(item, ctx["namespace"])
        for field in ("data", "binaryData"):
            data = item.get(field)
            if data is None:
                continue
            if not isinstance(data, dict):
                raise _ItemInvalid("configmap_data_invalid")
            keys += len(data)  # key names are counted; values are neither inspected nor copied
    return {"configmaps": len(items), "data_keys": keys, "values_excluded": True}


# ------------------------------------------------------------------------------- responses

def _load_response(root, response, resource):
    """(items, continue_token, remaining) for an HTTP 200 response, or raise _ItemInvalid (invalid body)."""
    try:
        data = B._read(root / response["file"], MAX_RESPONSE_BYTES, response["sha256"])
    except B.BundleError as exc:
        raise RecordingError(exc.code.replace("bundle_", "recording_"), Path(response["file"]).name) from None
    try:
        body = canonical.loads(data, canonical.Limits(max_bytes=MAX_RESPONSE_BYTES))
    except ContractError:
        raise _ItemInvalid("body_not_strict_json") from None
    _refuse_secrets(body)
    api_versions, list_kind, item_kind = RESOURCES[resource]
    if not isinstance(body, dict) or body.get("kind") != list_kind or body.get("apiVersion") not in api_versions:
        raise _ItemInvalid("list_kind_mismatch")
    items, meta = body.get("items"), body.get("metadata") or {}
    if not isinstance(items, list) or not isinstance(meta, dict):
        raise _ItemInvalid("list_shape_invalid")
    uids = set()
    for item in items:
        if not isinstance(item, dict) or item.get("kind", item_kind) != item_kind:
            raise _ItemInvalid("item_kind_mismatch")
        uid = (item.get("metadata") or {}).get("uid") if isinstance(item.get("metadata"), dict) else None
        if uid in uids:
            raise _ItemInvalid("item_duplicate")
        uids.add(uid)
    token = meta.get("continue")
    remaining = meta.get("remainingItemCount")
    return items, (token if isinstance(token, str) and token else None), \
        (remaining if type(remaining) is int and remaining > 0 else None)


def _status(response):
    """The failure of a non-200 response: (outcome, reason)."""
    if response is None:
        return acq.FAILED, "source_unavailable", "not_recorded"
    code, error = response["http_status"], response["error"]
    if code in (401, 403):
        return acq.DENIED, "authorization_denied", f"http_{code}"
    if code == 429 or error == "rate_limited":
        return acq.FAILED, "rate_limited", f"http_{code}"
    if code == 504 or error == "timeout":
        return acq.FAILED, "timeout", f"http_{code}"
    return acq.FAILED, "source_unavailable", f"http_{code}"


def _batches(plan_digest, ctx, query, outcome, reason, coverage, observations, truncated, omitted):
    stem = query.replace("k8s.", "")
    chunks = [observations[i:i + LIMITS["max_observations_per_batch"]]
              for i in range(0, len(observations), LIMITS["max_observations_per_batch"])] or [[]]
    records, before = [], None
    for n, chunk in enumerate(chunks, 1):
        last = n == len(chunks)
        record_outcome = outcome
        if outcome in (acq.COMPLETE, acq.EMPTY):
            record_outcome = acq.COMPLETE if chunk else acq.EMPTY
        after = f"{stem}-c{n}"
        records.append({
            "contract_version": acq.BATCH_VERSION, "plan_digest": plan_digest, "source_id": ctx["source_id"],
            "query_id": query, "batch_key": f"{stem}-{n}", "sequence": n, "outcome": record_outcome,
            "reason": reason, "coverage": coverage, "cursor": {"before": before, "after": after},
            "truncation": {"truncated": bool(truncated and last), "reason": "page_limit" if truncated and last else None,
                           "omitted_count": omitted if truncated and last else None},
            "observations": chunk, "delivery": {"attempt": 1}})
        before = after
    return records


def _sort(observations):
    return sorted(observations, key=lambda o: (o["observation_kind"], o["source_uid"], o["source_version"]))


# ---------------------------------------------------------------------------------- convert

def convert(directory):
    """Convert one recording directory. Raises ``RecordingError`` when the recording is refused."""
    root = Path(os.path.abspath(directory))
    manifest, manifest_sha = _read_manifest(root)
    responses, files = _validate_manifest(manifest)
    _check_layout(root, files)
    ctx = {"namespace": manifest["namespace"], "source_id": manifest["source_id"],
           "clock": manifest["clock"]["clock_domain_id"]}
    recording_id = manifest["recording_id"]
    clock = manifest["clock"]
    try:
        clock_record = ti.clock_domain(clock["clock_domain_id"], clock["status"], clock["offset_ms"],
                                       clock["offset_uncertainty_ms"],
                                       ti.FIXTURE_DECLARED if clock["status"] == ti.DECLARED else None,
                                       clock["continuity"]).to_record()
        registry_record = {"contract_version": SOURCE_REGISTRY_VERSION, "registry_id": f"{recording_id}-sources",
                           "sources": [{"source_id": ctx["source_id"], "source_kind": "kubernetes_api",
                                        "cluster_id": manifest["cluster_id"], "namespace": ctx["namespace"],
                                        "clock_domain_ids": [ctx["clock"]], "query_ids": sorted(QUERIES)}]}
        registry = SourceRegistry.from_record(registry_record)  # also validates the namespace and cluster binding
        clocks.declare(registry, [clock_record])
    except (ContractError, clocks.ClockDeclarationError) as exc:
        raise RecordingError("recording_manifest_invalid", getattr(exc, "code", "clock_invalid")) from None
    plan_record = {"contract_version": pl.RUN_PLAN_VERSION, "plan_id": recording_id, "registry_id": registry.registry_id,
                   "registry_digest": registry.digest,
                   "window": {"start": manifest["window"]["start"], "end": manifest["window"]["end"]},
                   "expected_acquisitions": [{"source_id": ctx["source_id"], "query_id": q, "mandatory": True}
                                             for q in sorted(QUERIES)],
                   "contract_versions": pl.required_contract_versions(), "rule_versions": required_rule_versions(),
                   "synthesis_mode": "disabled", "limits": dict(LIMITS)}
    try:
        plan = pl.RunPlan.from_record(plan_record, registry)
    except ContractError as exc:
        raise RecordingError("recording_manifest_invalid", exc.code) from None

    # Read every recorded 200 response once: (items, token, remaining) or an invalid-body code.
    loaded = {}
    for resource, response in sorted(responses.items()):
        if response["http_status"] == 200 and response["error"] is None:
            try:
                loaded[resource] = _load_response(root, response, resource)
            except _ItemInvalid as exc:
                loaded[resource] = exc

    acquisitions, batches = [], []
    for query in sorted(QUERIES):
        needed = QUERIES[query]
        entry = {"query_id": query, "resources": list(needed), "observations": 0, "out_of_scope": {},
                 "item_errors": {}, "notes": {}}
        failure = None
        for resource in needed:  # the first failed resource decides a failed acquisition
            if resource not in loaded:
                outcome, reason, detail = _status(responses.get(resource))
                failure = failure or (outcome, reason)
                entry.setdefault("response", {})[resource] = detail
            elif isinstance(loaded[resource], _ItemInvalid):
                failure = failure or (acq.FAILED, "invalid_response")
                entry["item_errors"][loaded[resource].code] = 1
                entry.setdefault("response", {})[resource] = "invalid_response"
            else:
                entry.setdefault("response", {})[resource] = "http_200"
        observations = []
        if failure is None:
            try:
                if query == "k8s.pods":
                    observations, entry["out_of_scope"]["pods"] = _pods(loaded["pods"][0], ctx)
                else:
                    rs_obs, by_deployment, entry["out_of_scope"]["replicasets"] = _replicasets(loaded["replicasets"][0], ctx)
                    rollouts, entry["notes"] = _deployments(loaded["deployments"][0], by_deployment, ctx)
                    observations = rs_obs + rollouts
                for observation in observations:  # the evidence contract, before anything is written
                    ev.observe(observation, source_id=ctx["source_id"], registry=registry,
                               delivery={"query_id": query, "batch_id": "check", "attempt": 1})
            except _ItemInvalid as exc:
                failure, observations = (acq.FAILED, "invalid_response"), []
                entry["item_errors"][exc.code] = entry["item_errors"].get(exc.code, 0) + 1
            except ContractError as exc:
                failure, observations = (acq.FAILED, "invalid_response"), []
                entry["item_errors"][exc.code] = entry["item_errors"].get(exc.code, 0) + 1
        if failure:
            outcome, reason = failure
            coverage, truncated, omitted, observations = None, False, None, []
        else:
            truncated = any(loaded[r][1] for r in needed)
            omitted_counts = [loaded[r][2] for r in needed if loaded[r][1]]
            omitted = sum(omitted_counts) if omitted_counts and None not in omitted_counts else None
            starts = [pl.exact_ms(responses[r]["coverage"]["start"], "s") for r in needed]
            ends = [pl.exact_ms(responses[r]["coverage"]["end"], "e") for r in needed]
            if max(starts) >= min(ends):  # the resources' coverages do not overlap: nothing is verified
                outcome, reason, coverage, observations, truncated, omitted = acq.FAILED, "invalid_response", None, [], False, None
                entry["item_errors"]["coverage_disjoint"] = 1
            else:
                bound = max(needed, key=lambda r: pl.exact_ms(responses[r]["coverage"]["start"], "s"))
                tight = min(needed, key=lambda r: pl.exact_ms(responses[r]["coverage"]["end"], "e"))
                coverage = {"start": responses[bound]["coverage"]["start"], "end": responses[tight]["coverage"]["end"]}
                outcome = acq.PARTIAL if truncated else (acq.COMPLETE if observations else acq.EMPTY)
                reason = "page_limit" if truncated else None
        observations = _sort(observations)
        entry.update(outcome=outcome, reason=reason, observations=len(observations),
                     coverage_claimed=outcome in (acq.COMPLETE, acq.EMPTY))
        acquisitions.append(entry)
        batches += _batches(plan.digest, ctx, query, outcome, reason, coverage, observations, truncated, omitted)

    unsupported = []
    for resource in UNSUPPORTED:
        entry = {"resource": resource, "classification": UNSUPPORTED_CONVERSION, "coverage_claimed": False,
                 "used_as_evidence": False}
        if resource not in responses:
            entry["response"] = "not_recorded"
        elif resource not in loaded:
            entry["response"] = _status(responses[resource])[2]
        elif isinstance(loaded[resource], _ItemInvalid):
            entry.update(response="invalid_response", item_errors={loaded[resource].code: 1})
        else:
            items, token, _ = loaded[resource]
            try:
                entry["counts"] = _events(items, ctx) if resource == "events" else _configmaps(items, ctx)
                entry.update(response="http_200", items=len(items), truncated=bool(token))
            except _ItemInvalid as exc:
                entry.update(response="invalid_response", item_errors={exc.code: 1})
        unsupported.append(entry)

    for record in batches:  # every batch must decode under the plan before anything is written
        try:
            acq.decode_batch(record, plan, registry)
        except ContractError as exc:
            raise RecordingError("recording_conversion_invalid", exc.code) from None
    report = {"contract_version": REPORT_VERSION, "recording_id": recording_id, "recording_sha256": manifest_sha,
              "bundle_id": recording_id, "source_id": ctx["source_id"], "cluster_id": manifest["cluster_id"],
              "namespace": ctx["namespace"], "plan_digest": plan.digest, "acquisitions": acquisitions,
              "unsupported": unsupported,
              "note": ("events and configmaps are validated and counted only (unsupported_conversion): observation "
                       "kinds 0.1 has no kind for them. No acquisition is planned for them, no coverage is claimed "
                       "and nothing from them is evidence. ConfigMap values are never read.")}
    canonical.canonical_bytes(report)  # the report itself is canonical JSON
    return Conversion(recording_id, registry_record, plan_record, (clock_record,), tuple(batches), report)
