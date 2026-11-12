"""Synthetic recorded Kubernetes API responses for CA-P2-004c (all values invented; no real cluster).

Three recordings of the scenario-001 namespace, written by ``tools/export_k8s_recordings.py``:

  rollout-complete   every list answered (HTTP 200): pods, replicasets, deployments, events, configmaps
  degraded           pods truncated (continue token); replicasets 503; events timed out; configmaps 403
  events-only        only events and configmaps were recorded; pods denied; deployments missing

Response bodies are pretty-printed like ``kubectl get -o json``, deliberately not canonical JSON.
The ConfigMap carries synthetic placeholder values, which the adapter must never read or copy.
Nothing here states an outcome.
"""

import hashlib
import json

from ..app import k8s_recording as K

NAMESPACE = "ca-demo"
CLUSTER = "ca-kind-synthetic"
WINDOW = {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T08:30:00Z"}
RECORDINGS = ("rollout-complete", "degraded", "events-only")
# Synthetic placeholder ConfigMap values: a test proves none of them reaches a bundle or a report.
CONFIG_VALUES = {"pool.maxConnections": "4", "db.password": "synthetic-placeholder-not-a-secret-7f3a"}

DEPLOY_UID = "0b8e7c1e-0000-4000-8000-00000000d001"


def _meta(name, uid, version, created, owner=None, annotations=None, labels=None):
    meta = {"name": name, "namespace": NAMESPACE, "uid": uid, "resourceVersion": version, "creationTimestamp": created}
    if owner:
        kind, owner_name, owner_uid = owner
        meta["ownerReferences"] = [{"apiVersion": "apps/v1", "kind": kind, "name": owner_name, "uid": owner_uid,
                                    "controller": True, "blockOwnerDeletion": True}]
    if annotations:
        meta["annotations"] = annotations
    if labels:
        meta["labels"] = labels
    return meta


def _template(image, hash_):
    return {"metadata": {"labels": {"app": "checkout-api", "pod-template-hash": hash_}},
            "spec": {"containers": [{"name": "checkout-api", "image": image,
                                     "env": [{"name": "DB_PASSWORD",
                                              "valueFrom": {"secretKeyRef": {"name": "checkout-db", "key": "password"}}}],
                                     "volumeMounts": [{"name": "pool", "mountPath": "/etc/checkout/pool"}]}],
                     "volumes": [{"name": "pool", "configMap": {"name": "checkout-db-pool"}}]}}


def _replicaset(name, uid, version, created, revision, image, hash_):
    return {"metadata": _meta(name, uid, version, created, ("Deployment", "checkout-api", DEPLOY_UID),
                              {"deployment.kubernetes.io/revision": str(revision)}),
            "spec": {"replicas": 1, "template": _template(image, hash_)},
            "status": {"replicas": 1}}


def _pod(name, uid, version, created, rs, rs_uid, node, restarts):
    template = _template("registry.invalid/ca-demo/checkout-api:1.8.3", rs.rsplit("-", 1)[1])
    return {"metadata": _meta(name, uid, version, created, ("ReplicaSet", rs, rs_uid)),
            "spec": {**template["spec"], "nodeName": node},
            "status": {"phase": "Running", "containerStatuses": [{"name": "checkout-api", "restartCount": restarts}]}}


def _list(api_version, kind, items, cont=None, remaining=None):
    meta = {"resourceVersion": "3000"}
    if cont:
        meta["continue"] = cont
    if remaining:
        meta["remainingItemCount"] = remaining
    return {"apiVersion": api_version, "kind": kind, "metadata": meta, "items": items}


def bodies():
    replicasets = [
        _replicaset("checkout-api-6d4b5", "0b8e7c1e-0000-4000-8000-0000000a0001", "1500", "2026-10-15T07:00:00Z", 1,
                    "registry.invalid/ca-demo/checkout-api:1.8.2", "6d4b5"),
        _replicaset("checkout-api-7c9f8", "0b8e7c1e-0000-4000-8000-0000000a0002", "2002", "2026-10-15T08:11:00Z", 2,
                    "registry.invalid/ca-demo/checkout-api:1.8.3", "7c9f8")]
    deployment = {"metadata": _meta("checkout-api", DEPLOY_UID, "2001", "2026-10-01T09:00:00Z",
                                    annotations={"deployment.kubernetes.io/revision": "2"}),
                  "spec": {"replicas": 2, "template": _template("registry.invalid/ca-demo/checkout-api:1.8.3", "7c9f8")},
                  "status": {"conditions": [
                      {"type": "Available", "status": "True", "reason": "MinimumReplicasAvailable",
                       "lastUpdateTime": "2026-10-15T07:00:30Z"},
                      {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable",
                       "lastUpdateTime": "2026-10-15T08:12:40Z"}]}}
    pods = [_pod("checkout-api-7c9f8-b1", "0b8e7c1e-0000-4000-8000-0000000b0001", "2101", "2026-10-15T08:11:02Z",
                 "checkout-api-7c9f8", "0b8e7c1e-0000-4000-8000-0000000a0002", "node-a", 2),
            _pod("checkout-api-7c9f8-b2", "0b8e7c1e-0000-4000-8000-0000000b0002", "2102", "2026-10-15T08:11:03.250Z",
                 "checkout-api-7c9f8", "0b8e7c1e-0000-4000-8000-0000000a0002", "node-b", 0),
            {"metadata": _meta("debug-shell", "0b8e7c1e-0000-4000-8000-0000000b0009", "2150", "2026-10-15T08:20:00Z"),
             "spec": {"containers": [{"name": "sh", "image": "registry.invalid/tools/sh:1"}], "nodeName": "node-a"},
             "status": {"phase": "Running", "containerStatuses": [{"name": "sh", "restartCount": 0}]}}]
    events = [
        {"metadata": _meta("checkout-api.1", "0b8e7c1e-0000-4000-8000-0000000e0001", "2201", "2026-10-15T08:11:00Z"),
         "involvedObject": {"kind": "Deployment", "name": "checkout-api", "namespace": NAMESPACE},
         "type": "Normal", "reason": "ScalingReplicaSet", "message": "Scaled up replica set checkout-api-7c9f8 to 1",
         "lastTimestamp": "2026-10-15T08:11:00Z", "count": 1},
        {"metadata": _meta("checkout-api-7c9f8-b1.1", "0b8e7c1e-0000-4000-8000-0000000e0002", "2202", "2026-10-15T08:14:00Z"),
         "involvedObject": {"kind": "Pod", "name": "checkout-api-7c9f8-b1", "namespace": NAMESPACE},
         "type": "Warning", "reason": "BackOff",
         "message": "Back-off restarting failed container: pool.maxConnections=4 too low (synthetic)",
         "lastTimestamp": "2026-10-15T08:16:00Z", "count": 3},
        {"metadata": _meta("checkout-db-pool.1", "0b8e7c1e-0000-4000-8000-0000000e0003", "2203", "2026-10-15T08:10:00Z"),
         "involvedObject": {"kind": "ConfigMap", "name": "checkout-db-pool", "namespace": NAMESPACE},
         "type": "Warning", "reason": "ConfigChanged", "message": "configuration changed by ops (synthetic)",
         "lastTimestamp": "2026-10-15T08:10:00Z", "count": 1}]
    configmaps = [{"metadata": _meta("checkout-db-pool", "0b8e7c1e-0000-4000-8000-0000000c0001", "1002",
                                     "2026-10-01T09:00:00Z",
                                     annotations={"kubectl.kubernetes.io/last-applied-configuration":
                                                  json.dumps({"data": CONFIG_VALUES})}),
                   "data": dict(CONFIG_VALUES)}]
    return {
        "pods": _list("v1", "PodList", pods), "replicasets": _list("apps/v1", "ReplicaSetList", replicasets),
        "deployments": _list("apps/v1", "DeploymentList", [deployment]), "events": _list("v1", "EventList", events),
        "configmaps": _list("v1", "ConfigMapList", configmaps),
        "pods-truncated": _list("v1", "PodList", pods[:1], cont="eyJ2IjoibWV0YS5rOHMuaW8vdjEifQ", remaining=2),
    }


def _ok(resource, file):
    return {"resource": resource, "file": f"responses/{file}.json", "http_status": 200, "error": None,
            "coverage": dict(WINDOW)}


def _fail(resource, status, error=None):
    return {"resource": resource, "file": None, "sha256": None, "http_status": status, "error": error, "coverage": None}


def responses(name):
    """(manifest responses without digests, {file: body})."""
    b = bodies()
    if name == "rollout-complete":
        listed = [_ok(r, r) for r in ("pods", "replicasets", "deployments", "events", "configmaps")]
        files = {r: b[r] for r in ("pods", "replicasets", "deployments", "events", "configmaps")}
    elif name == "degraded":
        listed = [_ok("pods", "pods"), _fail("replicasets", 503, "unavailable"), _ok("deployments", "deployments"),
                  _fail("events", 504, "timeout"), _fail("configmaps", 403)]
        files = {"pods": b["pods-truncated"], "deployments": b["deployments"]}
    elif name == "events-only":
        listed = [_fail("pods", 403), _ok("events", "events"), _ok("configmaps", "configmaps")]
        files = {"events": b["events"], "configmaps": b["configmaps"]}
    else:
        raise ValueError("unknown recording")
    return listed, files


def body_bytes(body):
    return (json.dumps(body, indent=2, sort_keys=False) + "\n").encode("utf-8")


def manifest(name, listed, files):
    for entry in listed:
        if entry.get("file"):
            entry["sha256"] = hashlib.sha256(body_bytes(files[entry["file"][len("responses/"):-5]])).hexdigest()
    return {"contract_version": K.RECORDING_VERSION, "recording_id": f"ca-k8s-rec-{name}",
            "data_classification": "synthetic", "source_id": "k8s-api", "cluster_id": CLUSTER, "namespace": NAMESPACE,
            "window": dict(WINDOW),
            "clock": {"clock_domain_id": "k8s-apiserver", "status": "declared", "offset_ms": 0,
                      "offset_uncertainty_ms": 1000, "continuity": "declared_continuous"},
            "responses": sorted(({"sha256": None, **e} for e in listed), key=lambda e: e["resource"])}


# CA-P2-004d: recordings in ca-k8s-recording/0.2-provisional record each list's snapshot instant.
#   snapshot-complete  all five lists at one instant (usable with observation kinds 0.1 or 0.2)
#   snapshot-skewed    deployments and replicasets listed at different instants; events timed out;
#                      configmaps denied
RECORDINGS_V2 = ("snapshot-complete", "snapshot-skewed")
SNAPSHOT_AT = "2026-10-15T08:29:59Z"


def _snap(resource, file, at=SNAPSHOT_AT):
    return {"resource": resource, "file": f"responses/{file}.json", "http_status": 200, "error": None, "snapshot_at": at}


def _snap_fail(resource, status, error=None):
    return {"resource": resource, "file": None, "sha256": None, "http_status": status, "error": error,
            "snapshot_at": None}


def responses_v2(name):
    b = bodies()
    if name == "snapshot-complete":
        listed = [_snap(r, r) for r in ("pods", "replicasets", "deployments", "events", "configmaps")]
        files = {r: b[r] for r in ("pods", "replicasets", "deployments", "events", "configmaps")}
    elif name == "snapshot-skewed":
        listed = [_snap("pods", "pods"), _snap("replicasets", "replicasets"),
                  _snap("deployments", "deployments", "2026-10-15T08:29:58Z"),
                  _snap_fail("events", 504, "timeout"), _snap_fail("configmaps", 403)]
        files = {r: b[r] for r in ("pods", "replicasets", "deployments")}
    else:
        raise ValueError("unknown recording")
    return listed, files


def recording_files(name):
    """{relative path: bytes} for one recording; written by ``k8s_recording.export_example``."""
    if name in RECORDINGS_V2:
        listed, files = responses_v2(name)
        doc = manifest(name, listed, files)
        doc["contract_version"] = K.RECORDING_VERSION_V2
        doc["responses"] = sorted(({"sha256": None, **e} for e in listed), key=lambda e: e["resource"])
        out = {f"responses/{file}.json": body_bytes(body) for file, body in files.items()}
        out[K.MANIFEST] = body_bytes(doc)
        return out
    listed, files = responses(name)
    doc = manifest(name, listed, files)
    out = {f"responses/{file}.json": body_bytes(body) for file, body in files.items()}
    out[K.MANIFEST] = body_bytes(doc)
    return out
