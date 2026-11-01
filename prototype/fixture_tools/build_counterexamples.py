"""Authoring tool: writes the two PR #13 counterexample fixtures (developer-authored, synthetic).

    python -I prototype/fixture_tools/build_counterexamples.py

Outputs are the reviewed, digest-pinned artifacts; this script only documents how they were made.
It writes fixtures only, never ground truth. Re-running must reproduce identical bytes.
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "ca-demo"
POOL_PATH = "/etc/checkout/pool"


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def t(type_, raw, domain):
    return {"type": type_, "raw": raw, "clock_domain": domain}


def declared(precision, unc):
    return {"status": "declared", "offset_ms": 0, "offset_uncertainty_ms": unc, "precision_ms": precision,
            "provenance": "fixture-declared"}


def pod(name, uid, rs, node, start, end=None):
    times = [t("event", start, "k8s-apiserver")] + ([t("terminated", end, "k8s-apiserver")] if end else [])
    return {"source_ref": f"k8s:pod/{NS}/{name}", "observation_kind": "pod", "source_uid": uid,
            "source_version": "lifecycle", "entity": {"kind": "Pod", "namespace": NS, "name": name},
            "times": times,
            "attributes": {"owner_replicaset": rs, "node": node, "restart_count": 0,
                           "configmap_volumes": [{"configmap": "checkout-db-pool", "mount_path": POOL_PATH,
                                                  "sub_path": False}]}}


def replicaset(name, version, revision, image, created):
    return {"source_ref": f"k8s:replicaset/{NS}/{name}", "observation_kind": "replicaset",
            "source_uid": f"uid-rs-{name}", "source_version": version,
            "entity": {"kind": "ReplicaSet", "namespace": NS, "name": name}, "times": [t("event", created, "k8s-apiserver")],
            "attributes": {"owner_deployment": "checkout-api", "revision": revision, "image": image}}


def log(p, seq, ts, template, fields, message):
    name, uid, node = p
    return {"source_ref": f"loki:{{namespace={NS},pod={name}}}#{seq:04d}", "observation_kind": "log_line",
            "source_uid": uid, "source_version": f"line-{seq:04d}",
            "entity": {"kind": "Pod", "namespace": NS, "name": name}, "times": [t("event", ts, node)],
            "attributes": {"pod": name, "template": template, "fields": fields, "message": message}}


def cfg(p, seq, ts, template, key, value, source):
    verb = "reloaded" if template == "CONFIG_RELOADED" else "loaded"
    return log(p, seq, ts, template, {"config_key": key, "value": value, "value_sha256": sha(value),
                                      "config_source": source, "config_path": f"{POOL_PATH}/{key}"},
               f"config {verb} key={key} value={value} source={source}")


def exhausted(p, seq, ts):
    return log(p, seq, ts, "POOL_EXHAUSTED", {"pool": "checkout-db", "in_use": "4", "max": "4", "wait_ms": "5000"},
               "db pool exhausted in_use=4 max=4 waited=5000ms")


def sample(series, labels, ts, value):
    return {"source_ref": f"prom:{series}{{{labels}}}@{ts}", "observation_kind": "metric_sample",
            "source_uid": f"series:{series}{{{labels}}}", "source_version": ts,
            "entity": {"kind": "Service", "namespace": NS, "name": "checkout-api"}, "times": [t("event", ts, "prometheus")],
            "attributes": {"series": series, "labels": labels, "value": value}}


def cm_change(version, prev, ts, key, before, after):
    return {"source_ref": f"k8s:configmap/{NS}/checkout-db-pool@{version}", "observation_kind": "configmap_change",
            "source_uid": "uid-cm-checkout-db-pool", "source_version": version,
            "entity": {"kind": "ConfigMap", "namespace": NS, "name": "checkout-db-pool"},
            "times": [t("event", ts, "k8s-apiserver")],
            "attributes": {"data_key": key, "before_value": before, "after_value": after,
                           "before_value_sha256": sha(before), "after_value_sha256": sha(after),
                           "previous_resource_version": prev, "actor": "ops-config-sync"}}


def rollout(version, start, done, field_changes, changed_fields):
    return {"source_ref": f"k8s:deployment/{NS}/checkout-api@rev2", "observation_kind": "deployment_rollout",
            "source_uid": "uid-deploy-checkout-api", "source_version": version,
            "entity": {"kind": "Deployment", "namespace": NS, "name": "checkout-api"},
            "times": [t("event", start, "k8s-apiserver"), t("completed", done, "k8s-apiserver")],
            "attributes": {"revision": "2", "previous_revision": "1", "changed_fields": changed_fields,
                           "field_changes": field_changes,
                           "image_before": "registry.invalid/ca-demo/checkout-api:1.8.2",
                           "image_after": "registry.invalid/ca-demo/checkout-api:1.8.3",
                           "config_refs_before": ["checkout-db-pool"], "config_refs_after": ["checkout-db-pool"],
                           "old_replicaset": "checkout-api-6d4b5", "new_replicaset": "checkout-api-7c9f8",
                           "actor": "ci-deployer"}}


def acq(query, source, window, observations):
    return {"query_id": query, "source_id": source, "window": window, "status": "complete",
            "observations": observations}


def plan(window):
    base = json.loads((ROOT / "fixtures" / "ca-scenario-001" / "source-plan.json").read_bytes())
    base["incident_window"] = window
    return base


def document(fixture_id, window, groups):
    domains = {"k8s-apiserver": declared(1000, 0), "node-a": declared(1, 250), "node-b": declared(1, 250),
               "prometheus": declared(1, 0)}
    queries = [("k8s.configmap-checkpoints", "k8s-api"), ("k8s.deployments", "k8s-api"),
               ("k8s.replicasets", "k8s-api"), ("k8s.pods", "k8s-api"), ("loki.checkout-api", "loki"),
               ("prom.checkout-api", "prometheus"), ("prom.alerts", "prometheus")]
    return {"fixture_id": fixture_id, "fixture_version": "0.1.0-spike", "schema_version": "ca-fixture/0.1",
            "clock_domains": domains,
            "acquisitions": [acq(q, s, window, groups.get(q, [])) for q, s in queries]}


IMG_OLD = "registry.invalid/ca-demo/checkout-api:1.8.2"
IMG_NEW = "registry.invalid/ca-demo/checkout-api:1.8.3"
ENV_FIELD = "spec.template.spec.containers[checkout-api].env[DB_POOL_MAX]"
IMAGE_FIELD = "spec.template.spec.containers[checkout-api].image"


def deploy_cause():
    """Rollout sets DB_POOL_MAX=4 on new pods; an unrelated ConfigMap log.level change is closest to onset."""
    d = "2026-10-20T"
    w = {"start": d + "08:50:00Z", "end": d + "09:10:00Z"}
    a1 = ("checkout-api-6d4b5-a1", "uid-pod-6d4b5-a1", "node-a")
    a2 = ("checkout-api-6d4b5-a2", "uid-pod-6d4b5-a2", "node-b")
    b1 = ("checkout-api-7c9f8-b1", "uid-pod-7c9f8-b1", "node-a")
    b2 = ("checkout-api-7c9f8-b2", "uid-pod-7c9f8-b2", "node-b")
    field_changes = [{"field": ENV_FIELD, "config_key": "pool.maxConnections", "before_value": "50",
                      "after_value": "4", "before_value_sha256": sha("50"), "after_value_sha256": sha("4")}]
    error = [("08:59:45Z", "0.002"), ("09:00:15Z", "0.003"), ("09:00:45Z", "0.041"), ("09:01:15Z", "0.048"),
             ("09:01:45Z", "0.212"), ("09:02:15Z", "0.236"), ("09:02:45Z", "0.231")]
    groups = {
        "k8s.configmap-checkpoints": [cm_change("1003", "1002", d + "09:01:15Z", "log.level", "debug", "info")],
        "k8s.deployments": [rollout("2001", d + "09:00:00Z", d + "09:01:50Z", field_changes, [IMAGE_FIELD, ENV_FIELD])],
        "k8s.replicasets": [replicaset("checkout-api-6d4b5", "1501", "1", IMG_OLD, "2026-10-19T15:00:00Z"),
                            replicaset("checkout-api-7c9f8", "2002", "2", IMG_NEW, d + "09:00:00Z")],
        "k8s.pods": [pod(a1[0], a1[1], "checkout-api-6d4b5", "node-a", d + "07:00:00Z", d + "09:01:00Z"),
                     pod(a2[0], a2[1], "checkout-api-6d4b5", "node-b", d + "07:00:00Z", d + "09:01:50Z"),
                     pod(b1[0], b1[1], "checkout-api-7c9f8", "node-a", d + "09:00:05Z"),
                     pod(b2[0], b2[1], "checkout-api-7c9f8", "node-b", d + "09:01:02Z")],
        "loki.checkout-api": [
            cfg(a1, 1, d + "07:00:03.100Z", "CONFIG_LOADED", "pool.maxConnections", "50", "configmap"),
            cfg(a2, 1, d + "07:00:03.400Z", "CONFIG_LOADED", "pool.maxConnections", "50", "configmap"),
            cfg(b1, 1, d + "09:00:07.200Z", "CONFIG_LOADED", "pool.maxConnections", "4", "env"),
            exhausted(b1, 2, d + "09:00:40.300Z"),
            cfg(b2, 1, d + "09:01:04.500Z", "CONFIG_LOADED", "pool.maxConnections", "4", "env"),
            cfg(a2, 2, d + "09:01:38.900Z", "CONFIG_RELOADED", "log.level", "info", "configmap"),
            exhausted(b2, 2, d + "09:01:30.700Z"),
            exhausted(b1, 3, d + "09:01:52.000Z"),
        ],
        "prom.checkout-api": [sample("checkout_api:error_ratio", f"namespace={NS}", d + ts, v) for ts, v in error],
        "prom.alerts": [{"source_ref": "alert:CheckoutHighErrorRate@2026-10-20T09:01:45Z",
                         "observation_kind": "alert_firing", "source_uid": "rule:CheckoutHighErrorRate",
                         "source_version": "3:" + d + "09:01:45Z",
                         "entity": {"kind": "Service", "namespace": NS, "name": "checkout-api"},
                         "times": [t("event", d + "09:03:45Z", "prometheus"),
                                   t("active_since", d + "09:01:45Z", "prometheus")],
                         "attributes": {"rule": "CheckoutHighErrorRate", "rule_version": "3",
                                        "expr_series": "checkout_api:error_ratio", "threshold": "0.05",
                                        "for": "2m"}}],
    }
    return document("cx-deploy-cause", w, groups), plan(w)


def benign():
    """Image-only rollout and a pool increase 50->60 that is consumed; no symptom, no alert."""
    d = "2026-10-22T"
    w = {"start": d + "09:55:00Z", "end": d + "10:15:00Z"}
    a1 = ("checkout-api-6d4b5-a1", "uid-pod-6d4b5-a1", "node-a")
    b1 = ("checkout-api-7c9f8-b1", "uid-pod-7c9f8-b1", "node-a")
    b2 = ("checkout-api-7c9f8-b2", "uid-pod-7c9f8-b2", "node-b")
    error = [("09:59:45Z", "0.002"), ("10:01:45Z", "0.003"), ("10:03:45Z", "0.002"), ("10:05:45Z", "0.002"),
             ("10:07:45Z", "0.003")]
    groups = {
        "k8s.configmap-checkpoints": [cm_change("1004", "1003", d + "10:05:00Z", "pool.maxConnections", "50", "60")],
        "k8s.deployments": [rollout("2001", d + "10:00:00Z", d + "10:01:40Z", [], [IMAGE_FIELD])],
        "k8s.replicasets": [replicaset("checkout-api-6d4b5", "1501", "1", IMG_OLD, "2026-10-21T15:00:00Z"),
                            replicaset("checkout-api-7c9f8", "2002", "2", IMG_NEW, d + "10:00:00Z")],
        "k8s.pods": [pod(a1[0], a1[1], "checkout-api-6d4b5", "node-a", d + "07:00:00Z", d + "10:01:40Z"),
                     pod(b1[0], b1[1], "checkout-api-7c9f8", "node-a", d + "10:00:05Z"),
                     pod(b2[0], b2[1], "checkout-api-7c9f8", "node-b", d + "10:01:00Z")],
        "loki.checkout-api": [
            cfg(a1, 1, d + "07:00:03.100Z", "CONFIG_LOADED", "pool.maxConnections", "50", "configmap"),
            cfg(b1, 1, d + "10:00:07.000Z", "CONFIG_LOADED", "pool.maxConnections", "50", "configmap"),
            cfg(b2, 1, d + "10:01:03.000Z", "CONFIG_LOADED", "pool.maxConnections", "50", "configmap"),
            cfg(b1, 2, d + "10:05:41.000Z", "CONFIG_RELOADED", "pool.maxConnections", "60", "configmap"),
            cfg(b2, 2, d + "10:05:49.000Z", "CONFIG_RELOADED", "pool.maxConnections", "60", "configmap"),
        ],
        "prom.checkout-api": [sample("checkout_api:error_ratio", f"namespace={NS}", d + ts, v) for ts, v in error],
        "prom.alerts": [],
    }
    return document("cx-benign", w, groups), plan(w)


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def main():
    for build in (deploy_cause, benign):
        observations, source_plan = build()
        out = ROOT / "fixtures" / observations["fixture_id"]
        write(out / "observations.json", observations)
        write(out / "source-plan.json", source_plan)
        write(out / "variants" / "A.json",
              {"variant": "A", "description": "Single variant", "synthesis": {"mode": "disabled"}, "ops": []})
        files = sorted(p for p in out.rglob("*.json") if p.name != "fixture-manifest.json")
        write(out / "fixture-manifest.json", {
            "fixture_id": observations["fixture_id"], "fixture_version": "0.1.0-spike", "digest_algorithm": "sha256",
            "files": {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
