"""Synthetic multi-scope fixtures for the cross-scope correlation regressions (test-only).

Builds on scenario 001's home scope (cluster ``ca-kind-synthetic``, namespace ``ca-demo``) and
adds sources bound to a second namespace and to a second cluster. Observations there reuse the
home scope's Pod, ConfigMap and ReplicaSet names on purpose: identical names in different
scopes are different objects, and the engine must never join them.
"""

import copy
import hashlib

import _support  # noqa: F401  (sets up the src path first)
from cloud_autopsy.contracts import acquisition as acq
from cloud_autopsy.contracts import frozen_input as fi
from cloud_autopsy.contracts import plan as pl
from cloud_autopsy.contracts.sources import SourceRegistry
from cloud_autopsy.engine import inputs
from cloud_autopsy.synthetic import scenario_001 as scenario

HOME = (scenario.CLUSTER, scenario.NAMESPACE)
OTHER_NAMESPACE = (scenario.CLUSTER, "ca-other")
OTHER_CLUSTER = ("ca-kind-synthetic-2", scenario.NAMESPACE)
SCOPES = {"other-ns": OTHER_NAMESPACE, "other-cluster": OTHER_CLUSTER}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sources():
    out = copy.deepcopy(scenario.REGISTRY_RECORD["sources"])
    for tag, (cluster, namespace) in SCOPES.items():
        out.append({"source_id": f"k8s-api-{tag}", "source_kind": "kubernetes_api", "cluster_id": cluster,
                    "namespace": namespace, "clock_domain_ids": ["k8s-apiserver"], "query_ids": ["k8s.pods"]})
        out.append({"source_id": f"loki-{tag}", "source_kind": "loki", "cluster_id": cluster,
                    "namespace": namespace, "clock_domain_ids": ["node-a", "node-b"],
                    "query_ids": ["loki.checkout-api"]})
    return sorted(out, key=lambda s: s["source_id"])


def registry():
    return SourceRegistry.from_record({**scenario.REGISTRY_RECORD, "registry_id": "ca-synthetic-cross-scope",
                                       "sources": _sources()})


def plan():
    reg = registry()
    record = scenario.plan_record("config-cause")
    acquisitions = list(record["expected_acquisitions"])
    for tag in SCOPES:
        acquisitions += [{"source_id": f"k8s-api-{tag}", "query_id": "k8s.pods", "mandatory": True},
                         {"source_id": f"loki-{tag}", "query_id": "loki.checkout-api", "mandatory": True}]
    record.update(plan_id="ca-scenario-001-cross-scope", registry_id=reg.registry_id, registry_digest=reg.digest,
                  expected_acquisitions=acquisitions)
    return pl.RunPlan.from_record(record, reg)


def in_namespace(observation, namespace):
    out = copy.deepcopy(observation)
    out["entity"]["namespace"] = namespace
    return out


def pod(name, node, *, uid=None, owner="checkout-api-6d4b5", configmaps=("checkout-db-pool",), namespace=None):
    out = scenario._pod(name, node)
    out["source_uid"] = uid or out["source_uid"]
    out["attributes"]["owner_replicaset"] = owner
    out["attributes"]["configmap_volumes"] = [{"configmap": c, "mount_path": "/etc/checkout/pool",
                                               "sub_path": False} for c in configmaps]
    return out if namespace is None else in_namespace(out, namespace)


def reload(pod_name, domain, line, raw, namespace=None):
    out = scenario._reload(pod_name, domain, line, raw)
    return out if namespace is None else in_namespace(out, namespace)


def exhausted(pod_name, domain, line, raw, namespace=None):
    out = scenario._exhausted(pod_name, domain, line, raw)
    return out if namespace is None else in_namespace(out, namespace)


def lowering_rollout():
    """A rollout whose typed field change lowers the mapped limit (env-var style)."""
    out = scenario._rollout()
    field = "spec.template.spec.containers[checkout-api].env[POOL_MAX_CONNECTIONS]"
    out["attributes"]["changed_fields"] = sorted(out["attributes"]["changed_fields"] + [field])
    out["attributes"]["field_changes"] = [{"field": field, "config_key": "pool.maxConnections",
                                           "before_value": "50", "after_value": "4",
                                           "before_value_sha256": _sha("50"), "after_value_sha256": _sha("4")}]
    return out


def batch(plan_, source_id, query_id, observations, key):
    return {"contract_version": acq.BATCH_VERSION, "plan_digest": plan_.digest, "source_id": source_id,
            "query_id": query_id, "batch_key": key, "sequence": 1,
            "outcome": acq.COMPLETE if observations else acq.EMPTY, "reason": None,
            "coverage": {"start": scenario.WINDOW[0], "end": scenario.WINDOW[1]},
            "cursor": {"before": None, "after": f"{key}-c1"},
            "truncation": {"truncated": False, "reason": None, "omitted_count": None},
            "observations": observations, "delivery": {"attempt": 1}}


def records(*, configmaps, deployments, pods, logs, foreign=None, alerts=None):
    """Batches for the home scope plus ``foreign`` = {tag: (pods, logs)} for the other scopes."""
    plan_ = plan()
    foreign = foreign or {}
    out = [batch(plan_, "k8s-api", "k8s.configmaps", configmaps, "configmaps-1"),
           batch(plan_, "k8s-api", "k8s.deployments", deployments, "deployments-1"),
           batch(plan_, "k8s-api", "k8s.pods", pods, "pods-1"),
           batch(plan_, "loki", "loki.checkout-api", logs, "logs-1"),
           batch(plan_, "prometheus", "prom.alerts", [scenario._alert()] if alerts is None else alerts, "alerts-1")]
    for tag in SCOPES:
        f_pods, f_logs = foreign.get(tag, ([], []))
        out.append(batch(plan_, f"k8s-api-{tag}", "k8s.pods", f_pods, f"pods-{tag}-1"))
        out.append(batch(plan_, f"loki-{tag}", "loki.checkout-api", f_logs, f"logs-{tag}-1"))
    return out


def build(batch_records, *, reverse_members=False):
    """A verified ``InvestigationInput``; ``reverse_members`` reverses the evidence-record order."""
    plan_, registry_ = plan(), registry()
    frozen = fi.seal(plan_, registry_, batch_records)
    members = {(m["evidence_id"], m["content_digest"]) for m in fi.collection_items(frozen, "evidence")}
    evidence = {}
    for record in batch_records:
        for item in acq.decode_batch(record, plan_, registry_).evidence:
            if (item.evidence_id, item.content_digest) in members:
                evidence[item.evidence_id] = item.to_record()
    ordered = [evidence[k] for k in sorted(evidence, reverse=reverse_members)]
    return inputs.build_input(frozen, plan_, registry_, ordered, scenario.clock_domain_records("config-cause"))


def scope_of(inp, evidence_id):
    e = inp.evidence(evidence_id)
    return (e.cluster_id, e.namespace)

