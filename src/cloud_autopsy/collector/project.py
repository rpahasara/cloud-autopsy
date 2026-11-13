"""Sanitizing projection (CA-P2-004e): every collected object is reduced, in memory, to an allowlist.

Only the fields below are copied, after type checks and length bounds; nothing else of a response
is kept. The projected objects keep the Kubernetes shape the recorded-response adapter reads, so
the same converters serve recordings and collections.

Never copied: annotations (except ``deployment.kubernetes.io/revision``), labels, env and envFrom
values, Secret references and Secret volumes (counted only), commands, args, status and Event
messages and notes, managedFields, ``last-applied-configuration``. An Event whose involved object
is a Secret is withheld entirely and counted (D6).
"""

from ..contracts.evidence import _UNSAFE_TEXT
from . import limits as LIM

MAX_TEXT = 1024
REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
_CONTROL = _UNSAFE_TEXT  # the evidence contract's control/separator/bidi pattern


def _text(value, max_len=MAX_TEXT):
    """A bounded, printable string, or None (the adapter then reports the item as invalid)."""
    if isinstance(value, str) and 0 < len(value) <= max_len and not _CONTROL.search(value):
        return value
    return None


def _int(value):
    return value if type(value) is int else None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _put(target, key, value):
    if value is not None:
        target[key] = value


def _metadata(item, revision=False):
    meta = _dict(item.get("metadata"))
    out = {}
    for key in ("name", "namespace", "uid", "resourceVersion", "creationTimestamp"):
        _put(out, key, _text(meta.get(key), 253))
    owners = []
    for ref in _list(meta.get("ownerReferences")):
        ref = _dict(ref)
        if ref.get("controller") is True:
            owner = {"controller": True}
            for key in ("kind", "name", "uid"):
                _put(owner, key, _text(ref.get(key), 253))
            owners.append(owner)
    if owners:
        out["ownerReferences"] = owners
    if revision:
        value = _text(_dict(meta.get("annotations")).get(REVISION_ANNOTATION), 20)
        if value is not None:
            out["annotations"] = {REVISION_ANNOTATION: value}
    return out


def _configmap_volumes(spec, counts):
    volumes = []
    for volume in _list(spec.get("volumes")):
        volume = _dict(volume)
        if "secret" in volume or "projected" in volume:
            counts["secret_or_projected_volumes"] = counts.get("secret_or_projected_volumes", 0) + 1
        cm = _dict(volume.get("configMap"))
        name, ref = _text(volume.get("name"), 253), _text(cm.get("name"), 253)
        if name and ref:
            volumes.append({"name": name, "configMap": {"name": ref}})
    return volumes


def _count_secret_refs(container, counts):
    for env in _list(container.get("env")):
        if "secretKeyRef" in _dict(_dict(env).get("valueFrom")):
            counts["secret_env_refs"] = counts.get("secret_env_refs", 0) + 1
    for source in _list(container.get("envFrom")):
        if "secretRef" in _dict(source):
            counts["secret_env_refs"] = counts.get("secret_env_refs", 0) + 1


def pod(item, counts):
    spec, status = _dict(item.get("spec")), _dict(item.get("status"))
    volumes = _configmap_volumes(spec, counts)
    names = {v["name"] for v in volumes}
    containers = []
    for container in _list(spec.get("containers")):
        container = _dict(container)
        _count_secret_refs(container, counts)
        mounts = []
        for mount in _list(container.get("volumeMounts")):
            mount = _dict(mount)
            if mount.get("name") in names:
                out = {"name": mount["name"], "subPath": bool(mount.get("subPath"))}
                _put(out, "mountPath", _text(mount.get("mountPath")))
                mounts.append(out)
        entry = {"volumeMounts": mounts}
        _put(entry, "name", _text(container.get("name"), 63))
        containers.append(entry)
    out_spec = {"containers": containers, "volumes": volumes}
    _put(out_spec, "nodeName", _text(spec.get("nodeName"), 253))
    statuses = []
    for s in _list(status.get("containerStatuses")):
        entry = {}
        _put(entry, "restartCount", _int(_dict(s).get("restartCount")))
        statuses.append(entry)
    out_status = {"containerStatuses": statuses} if "containerStatuses" in status else {}
    return {"metadata": _metadata(item), "spec": out_spec, "status": out_status}


def _template(template, counts, limits=()):
    spec = _dict(_dict(template).get("spec"))
    containers = []
    for container in _list(spec.get("containers")):
        container = _dict(container)
        _count_secret_refs(container, counts)
        entry = {}
        _put(entry, "name", _text(container.get("name"), 63))
        _put(entry, "image", _text(container.get("image"), 512))
        env_from = [{"configMapRef": {"name": _text(_dict(s.get("configMapRef")).get("name"), 253)}}
                    for s in map(_dict, _list(container.get("envFrom")))
                    if _text(_dict(s.get("configMapRef")).get("name"), 253)]
        env = [{"valueFrom": {"configMapKeyRef": {"name": _text(_dict(_dict(e.get("valueFrom")).get("configMapKeyRef")).get("name"), 253)}}}
               for e in map(_dict, _list(container.get("env")))
               if _text(_dict(_dict(e.get("valueFrom")).get("configMapKeyRef")).get("name"), 253)]
        if env_from:
            entry["envFrom"] = env_from
        # CA-P2-004g: only declared numeric limits, as literal integers (collector/limits.py).
        env = env + LIM.project_env(container, entry.get("name"), limits, counts)
        if env:
            entry["env"] = env
        containers.append(entry)
    return {"spec": {"containers": containers, "volumes": _configmap_volumes(spec, counts)}}


def replicaset(item, counts, limits=()):
    spec = _dict(item.get("spec"))
    return {"metadata": _metadata(item, revision=True),
            "spec": {"template": _template(spec.get("template"), counts, limits)}}


def deployment(item, counts):
    conditions = []
    for condition in _list(_dict(item.get("status")).get("conditions")):
        condition = _dict(condition)
        if condition.get("type") == "Progressing":
            out = {"type": "Progressing"}
            _put(out, "reason", _text(condition.get("reason"), 128))
            _put(out, "lastUpdateTime", _text(condition.get("lastUpdateTime"), 64))
            conditions.append(out)
    return {"metadata": _metadata(item, revision=True), "status": {"conditions": conditions}}


def event(item, counts):
    """An Event without its message or note; None (withheld, counted) when it concerns a Secret."""
    involved = _dict(item.get("involvedObject") or item.get("regarding"))
    if involved.get("kind") == "Secret":
        counts["secret_events_withheld"] = counts.get("secret_events_withheld", 0) + 1
        return None
    out = {"metadata": _metadata(item), "involvedObject": {}}
    for key in ("kind", "name", "namespace"):
        _put(out["involvedObject"], key, _text(involved.get(key), 253))
    _put(out, "type", _text(item.get("type"), 16))
    _put(out, "reason", _text(item.get("reason"), 128))
    series = _dict(item.get("series"))
    count = _int(item.get("count")) or _int(item.get("deprecatedCount")) or _int(series.get("count"))
    _put(out, "count", count)
    _put(out, "lastTimestamp", _text(item.get("lastTimestamp") or item.get("eventTime") or series.get("lastObservedTime"), 64))
    _put(out, "firstTimestamp", _text(item.get("firstTimestamp") or item.get("deprecatedFirstTimestamp"), 64))
    component = _text(_dict(item.get("source")).get("component"), 128) or _text(item.get("reportingComponent"), 128) \
        or _text(item.get("reportingController"), 128)
    if component:
        out["source"] = {"component": component}
    return out


PROJECTORS = {"pods": pod, "replicasets": replicaset, "deployments": deployment, "events": event}


def project(resource, item, counts, limits=()):
    """The allowlisted projection of one item (or None when withheld). Counts go to the report.
    ``limits``: validated declared numeric limits (CA-P2-004g); only ReplicaSet templates use them."""
    item = item if isinstance(item, dict) else {}
    if resource == "replicasets":
        return replicaset(item, counts, limits)
    return PROJECTORS[resource](item, counts)
