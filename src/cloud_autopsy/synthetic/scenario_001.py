"""Synthetic scenario 001: checkout-api database-pool exhaustion around a ConfigMap change and a rollout.

Story (all synthetic): at 08:10:00 the ConfigMap ``checkout-db-pool`` lowers
``pool.maxConnections`` from 50 to 4; at 08:11:00 an image-only rollout of ``checkout-api``
starts. Two pods that mount the ConfigMap reload it and later log ``POOL_EXHAUSTED``; an alert
fires. Node clocks carry declared synthetic offsets with bounded uncertainty.

Variants change exactly one aspect of what was delivered:
  config-cause            complete evidence
  configmap-unavailable   the ConfigMap acquisition failed (source unavailable)
  configmap-conflict      two different batches arrived under one ConfigMap batch key
  clock-unknown           node clocks declare unknown continuity
  symptom-before-change   the pods logged the symptom before the ConfigMap changed
  no-symptom              no symptom logs and no alert

Nothing here states an outcome.
"""

import hashlib

from ..contracts import acquisition as acq
from ..contracts import evidence as ev
from ..contracts import plan as pl
from ..contracts import timeinterval as ti
from ..contracts.sources import SOURCE_REGISTRY_VERSION, SourceRegistry
from ..engine import required_rule_versions

VARIANTS = ("config-cause", "configmap-unavailable", "configmap-conflict", "clock-unknown",
            "symptom-before-change", "no-symptom")
NAMESPACE = "ca-demo"
CLUSTER = "ca-kind-synthetic"
WINDOW = ("2026-10-15T08:00:00Z", "2026-10-15T08:30:00Z")

REGISTRY_RECORD = {
    "contract_version": SOURCE_REGISTRY_VERSION,
    "registry_id": "ca-synthetic-scenario-001",
    "sources": [
        {"source_id": "k8s-api", "source_kind": "kubernetes_api", "cluster_id": CLUSTER, "namespace": NAMESPACE,
         "clock_domain_ids": ["k8s-apiserver"], "query_ids": ["k8s.configmaps", "k8s.deployments", "k8s.pods"]},
        {"source_id": "loki", "source_kind": "loki", "cluster_id": CLUSTER, "namespace": NAMESPACE,
         "clock_domain_ids": ["node-a", "node-b"], "query_ids": ["loki.checkout-api"]},
        {"source_id": "prometheus", "source_kind": "prometheus", "cluster_id": CLUSTER, "namespace": NAMESPACE,
         "clock_domain_ids": ["prometheus"], "query_ids": ["prom.alerts"]},
    ],
}
ACQUISITIONS = {  # name -> (source_id, query_id, mandatory)
    "configmaps": ("k8s-api", "k8s.configmaps", True),
    "deployments": ("k8s-api", "k8s.deployments", True),
    "pods": ("k8s-api", "k8s.pods", True),
    "logs": ("loki", "loki.checkout-api", True),
    "alerts": ("prometheus", "prom.alerts", False),
}
LIMITS = {"max_window_ms": 3_600_000, "max_batches_per_acquisition": 10, "max_batch_deliveries": 100,
          "max_observations_per_batch": 100, "max_observations_total": 1_000, "max_batch_bytes": 1_048_576,
          "max_total_bytes": 10_000_000}


def registry():
    return SourceRegistry.from_record(REGISTRY_RECORD)


def plan_record(variant):
    _check(variant)
    reg = registry()
    return {"contract_version": pl.RUN_PLAN_VERSION, "plan_id": f"ca-scenario-001-{variant}",
            "registry_id": reg.registry_id, "registry_digest": reg.digest,
            "window": {"start": WINDOW[0], "end": WINDOW[1]},
            "expected_acquisitions": [{"source_id": s, "query_id": q, "mandatory": m}
                                      for s, q, m in ACQUISITIONS.values()],
            "contract_versions": pl.required_contract_versions(), "rule_versions": required_rule_versions(),
            "synthesis_mode": "disabled", "limits": dict(LIMITS)}


def plan(variant):
    return pl.RunPlan.from_record(plan_record(variant), registry())


def clock_domain_records(variant):
    """Declared synthetic clocks: offset = source clock - reference clock (fixture-declared)."""
    _check(variant)
    node_continuity = ti.UNKNOWN if variant == "clock-unknown" else ti.CONTINUOUS
    declared = [("k8s-apiserver", 0, 0, ti.CONTINUOUS), ("prometheus", 0, 0, ti.CONTINUOUS),
                ("node-a", 1_500, 200, node_continuity), ("node-b", -800, 200, node_continuity)]
    return [ti.clock_domain(d, ti.DECLARED, offset_ms=o, offset_uncertainty_ms=u,
                            offset_provenance=ti.FIXTURE_DECLARED, continuity=c).to_record()
            for d, o, u, c in sorted(declared)]


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _time(raw, domain, kind="event", precision=None):
    return {"timestamp_kind": kind, "raw": raw, "clock_domain_id": domain, "declared_precision_ns": precision}


def _obs(kind, source_ref, uid, version, entity_kind, name, times, attributes):
    return {"contract_version": ev.OBSERVATION_VERSION, "source_ref": source_ref, "observation_kind": kind,
            "source_uid": uid, "source_version": version,
            "entity": {"kind": entity_kind, "namespace": NAMESPACE, "name": name}, "times": times,
            "attributes": attributes}


def _configmap_change(after="4", actor="ops-config-sync"):
    return _obs("configmap_change", "k8s:configmap/ca-demo/checkout-db-pool@1002", "uid-cm-checkout-db-pool",
                "1002", "ConfigMap", "checkout-db-pool", [_time("2026-10-15T08:10:00Z", "k8s-apiserver")],
                {"data_key": "pool.maxConnections", "before_value": "50", "after_value": after,
                 "before_value_sha256": _sha("50"), "after_value_sha256": _sha(after),
                 "previous_resource_version": "1001", "actor": actor})


def _rollout():
    return _obs("deployment_rollout", "k8s:deployment/ca-demo/checkout-api@rev2", "uid-deploy-checkout-api",
                "2001", "Deployment", "checkout-api",
                [_time("2026-10-15T08:11:00Z", "k8s-apiserver"),
                 _time("2026-10-15T08:12:40Z", "k8s-apiserver", "completed", 1_000_000_000)],
                {"revision": "2", "previous_revision": "1",
                 "changed_fields": ["spec.template.spec.containers[checkout-api].image"],
                 "image_before": "registry.invalid/ca-demo/checkout-api:1.8.2",
                 "image_after": "registry.invalid/ca-demo/checkout-api:1.8.3",
                 "config_refs_before": ["checkout-db-pool"], "config_refs_after": ["checkout-db-pool"],
                 "old_replicaset": "checkout-api-6d4b5", "new_replicaset": "checkout-api-7c9f8",
                 "actor": "ci-deployer"})


def _pod(name, node):
    return _obs("pod", f"k8s:pod/ca-demo/{name}", f"uid-pod-{name}", "lifecycle", "Pod", name,
                [_time("2026-10-15T07:00:00Z", "k8s-apiserver")],
                {"owner_replicaset": "checkout-api-6d4b5", "node": node, "restart_count": 0,
                 "configmap_volumes": [{"configmap": "checkout-db-pool", "mount_path": "/etc/checkout/pool",
                                        "sub_path": False}]})


def _log(pod, domain, line, raw, template, fields, message):
    return _obs("log_line", f"loki:{{namespace=ca-demo,pod={pod}}}#{line:04d}", f"uid-pod-{pod}", f"line-{line:04d}",
                "Pod", pod, [_time(raw, domain)],
                {"pod": pod, "template": template, "fields": fields, "message": message})


def _reload(pod, domain, line, raw):
    return _log(pod, domain, line, raw, "CONFIG_RELOADED",
                {"config_key": "pool.maxConnections", "value_sha256": _sha("4")}, "configuration reloaded")


def _exhausted(pod, domain, line, raw):
    return _log(pod, domain, line, raw, "POOL_EXHAUSTED",
                {"pool": "primary", "in_use": "4", "max": "4", "wait_ms": "5000"},
                "connection pool exhausted; waiting for a free connection")


def _alert():
    return _obs("alert_firing", "alert:CheckoutPoolSaturation@2026-10-15T08:11:30Z", "rule:CheckoutPoolSaturation",
                "1:2026-10-15T08:11:30Z", "Service", "checkout-api",
                [_time("2026-10-15T08:12:00Z", "prometheus"),
                 _time("2026-10-15T08:11:30Z", "prometheus", "active_since")],
                {"rule": "CheckoutPoolSaturation", "rule_version": "1",
                 "expr_series": "checkout_api:db_pool_in_use_ratio", "threshold": "0.95", "for": "1m"})


def _batch(plan_, acquisition, observations, *, key=None, outcome=None, reason=None, coverage=WINDOW):
    source_id, query_id, _ = ACQUISITIONS[acquisition]
    outcome = outcome or (acq.COMPLETE if observations else acq.EMPTY)
    return {"contract_version": acq.BATCH_VERSION, "plan_digest": plan_.digest, "source_id": source_id,
            "query_id": query_id, "batch_key": key or f"{acquisition}-1", "sequence": 1, "outcome": outcome,
            "reason": reason,
            "coverage": None if coverage is None else {"start": coverage[0], "end": coverage[1]},
            "cursor": {"before": None, "after": f"{acquisition}-c1"},
            "truncation": {"truncated": False, "reason": None, "omitted_count": None},
            "observations": observations, "delivery": {"attempt": 1}}


def batches(variant):
    """The distinct batch records a collector delivered for ``variant`` (each delivered once)."""
    _check(variant)
    plan_ = plan(variant)
    pods = [_pod("checkout-api-6d4b5-a1", "node-a"), _pod("checkout-api-6d4b5-a2", "node-b")]
    reloads = [_reload("checkout-api-6d4b5-a1", "node-a", 41, "2026-10-15T08:10:21.500Z"),
               _reload("checkout-api-6d4b5-a2", "node-b", 17, "2026-10-15T08:10:23.200Z")]
    if variant == "symptom-before-change":
        symptoms = [_exhausted("checkout-api-6d4b5-a1", "node-a", 12, "2026-10-15T08:05:01.500Z"),
                    _exhausted("checkout-api-6d4b5-a2", "node-b", 9, "2026-10-15T08:04:10.200Z")]
    elif variant == "no-symptom":
        symptoms = []
    else:
        symptoms = [_exhausted("checkout-api-6d4b5-a1", "node-a", 57, "2026-10-15T08:10:51.500Z"),
                    _exhausted("checkout-api-6d4b5-a2", "node-b", 33, "2026-10-15T08:11:05.200Z")]
    alerts = [] if variant == "no-symptom" else [_alert()]

    if variant == "configmap-unavailable":
        configmaps = [_batch(plan_, "configmaps", [], outcome=acq.FAILED, reason="source_unavailable", coverage=None)]
    elif variant == "configmap-conflict":
        configmaps = [_batch(plan_, "configmaps", [_configmap_change()]),
                      _batch(plan_, "configmaps", [_configmap_change(actor="ops-manual-edit")])]
    else:
        configmaps = [_batch(plan_, "configmaps", [_configmap_change()])]
    return configmaps + [_batch(plan_, "deployments", [_rollout()]), _batch(plan_, "pods", pods),
                         _batch(plan_, "logs", reloads + symptoms), _batch(plan_, "alerts", alerts)]


def _check(variant):
    if variant not in VARIANTS:
        raise ValueError("unknown scenario variant")
