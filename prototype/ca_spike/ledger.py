"""Hypothesis ledger: finite versioned mechanism templates, support, contradiction, abstention.

Temporal proximity is recorded as correlation only and never counts as support. A
hypothesis is ``supported`` only when every prerequisite is satisfied, no mandatory gap
affects its mechanism and no contradiction was observed. Exactly one supported
hypothesis resolves the investigation; otherwise the engine abstains with reasons.
"""

from decimal import Decimal, InvalidOperation

from .canonical import canonical_bytes, sha256_hex

LEDGER_RULE_VERSION = "ca-ledger/0.1-spike"

CATALOG = {
    "version": "ca-mech/0.1-spike",
    "config_value_change": {
        # config key -> symptom template expected when the limit is reduced
        "symptom_by_config_key": {"pool.maxConnections": "POOL_EXHAUSTED"},
    },
    "deployment_rollout": {
        # changed pod-template field -> symptom template; image changes map to nothing
        "symptom_by_changed_field": {},
    },
}

CONFIG_TEMPLATES = ("CONFIG_LOADED", "CONFIG_RELOADED")


def _dec(text):
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError):
        return None


def _hyp_id(mechanism, entity):
    return "hyp:" + sha256_hex(canonical_bytes(
        {"mechanism": mechanism, "entity": entity, "rule": LEDGER_RULE_VERSION}))[:16]


def _prereq(key, result, evidence=(), gaps=(), reason=None):
    return {"key": key, "result": result, "evidence_ids": sorted(set(evidence)),
            "gap_ids": sorted(set(gaps)), "reason": reason}


def _status(prereqs, contradictions, blocking_gaps):
    if contradictions or any(p["result"] == "contradicted" for p in prereqs):
        return "contradicted"
    if not blocking_gaps and all(p["result"] == "satisfied" for p in prereqs):
        return "supported"
    return "unresolved"


def _blocking_gaps(ctx, mechanism):
    return [g for g in ctx.gaps if mechanism in g.affects_mechanisms]


def _symptom_evidence(ctx):
    return sorted(r.inputs[0] for r in ctx.relations if r.relation_type in ("metric_symptom", "alert_symptom"))


def _latest_config_before(ctx, pod_name, symptom_log, data_key):
    """Latest config load/reload log in the same pod strictly before the symptom, if determinable."""
    prior = [c for c in ctx.logs(pod_name, CONFIG_TEMPLATES)
             if c.attributes.get("fields", {}).get("config_key") == data_key and ctx.order(c, symptom_log) == "before"]
    for c in prior:
        if all(o is c or ctx.order(o, c) == "before" for o in prior):
            return c
    return None


def _correlations(ctx, change):
    rows = []
    for sid in _symptom_evidence(ctx):
        rows.append({"change": change.evidence_id, "symptom": sid, "order": ctx.order(change, ctx.by_id[sid]),
                     "note": "temporal proximity only; not mechanism support"})
    return rows


def evaluate_config(ctx, cm_name, namespace):
    mechanism = "config_value_change"
    entity = {"kind": "ConfigMap", "namespace": namespace, "name": cm_name}
    gaps = _blocking_gaps(ctx, mechanism)
    gap_ids = [g.gap_id for g in gaps]
    changes = sorted(ctx.cm_changes.get(cm_name, []), key=lambda e: e.evidence_id)
    prereqs, contradictions, correlations = [], [], []
    missing = "blocked_by_gap" if gaps else "unsatisfied"

    if not changes:
        reason = "change_evidence_unavailable" if gaps else "no_change_observed"
        for key in ("change_observed", "mechanism_mapped", "consumed_by_symptomatic_pods",
                    "symptom_after_consumption"):
            prereqs.append(_prereq(key, missing, gaps=gap_ids, reason=reason))
    else:
        prereqs.append(_prereq("change_observed", "satisfied", [c.evidence_id for c in changes]))
        mapped, mapping_ev, symptom_template, mapping_reason = "unsatisfied", [], None, "unmapped_config_key"
        for c in changes:
            key = c.attributes.get("data_key")
            template = CATALOG[mechanism]["symptom_by_config_key"].get(key)
            before, after = _dec(c.attributes.get("before_value")), _dec(c.attributes.get("after_value"))
            if template is None:
                continue
            if before is None or after is None:
                mapping_reason = "non_numeric_value"
            elif after < before:
                mapped, mapping_ev, symptom_template, mapping_reason = "satisfied", [c.evidence_id], template, None
                break
            else:
                mapped, mapping_ev, mapping_reason = "contradicted", [c.evidence_id], "limit_not_reduced"
        prereqs.append(_prereq("mechanism_mapped", mapped, mapping_ev, reason=mapping_reason))

        consumed = {}
        for r in ctx.relations:
            if r.relation_type == "config_value_consumed" and r.inputs[2] in {c.evidence_id for c in changes}:
                pod_name = ctx.by_id[r.inputs[1]].entity["name"]
                consumed.setdefault(pod_name, []).append(r)
        symptomatic = {p: ctx.logs(p, (symptom_template,)) for p in ctx.workload_pods()} if symptom_template else {}
        symptomatic = {p: logs for p, logs in symptomatic.items() if logs}
        both = sorted(set(symptomatic) & set(consumed))
        cons_ev = [i for p in both for r in consumed[p] for i in r.inputs]
        prereqs.append(_prereq("consumed_by_symptomatic_pods", "satisfied" if both else "unsatisfied", cons_ev,
                               reason=None if both else "no_symptomatic_pod_consumed_new_value"))

        ordered_ev = []
        for p in both:
            for r in consumed[p]:
                cons_log = ctx.by_id[r.inputs[0]]
                for sym in symptomatic[p]:
                    if ctx.order(cons_log, sym) == "before":
                        ordered_ev += [cons_log.evidence_id, sym.evidence_id]
        prereqs.append(_prereq("symptom_after_consumption", "satisfied" if ordered_ev else "unsatisfied",
                               ordered_ev + (_symptom_evidence(ctx) if ordered_ev else []),
                               reason=None if ordered_ev else "no_strictly_ordered_consumption_then_symptom"))

        change_key = changes[0].attributes.get("data_key")
        after_sha = {c.attributes.get("after_value_sha256") for c in changes}
        for p, logs in sorted(symptomatic.items()):
            for sym in sorted(logs, key=lambda e: e.evidence_id):
                latest = _latest_config_before(ctx, p, sym, change_key)
                if latest is not None and latest.attributes["fields"].get("value_sha256") not in after_sha:
                    contradictions.append({"key": "symptom_with_previous_value",
                                           "evidence_ids": sorted([latest.evidence_id, sym.evidence_id])})
        for c in changes:
            correlations += _correlations(ctx, c)

    status = _status(prereqs, contradictions, gaps)
    return _hypothesis(mechanism, entity, status, prereqs, contradictions, correlations, gap_ids)


def evaluate_rollout(ctx, deployment_name, namespace):
    mechanism = "deployment_rollout"
    entity = {"kind": "Deployment", "namespace": namespace, "name": deployment_name}
    gaps = _blocking_gaps(ctx, mechanism)
    gap_ids = [g.gap_id for g in gaps]
    rollouts = sorted(ctx.rollouts.get(deployment_name, []), key=lambda e: e.evidence_id)
    prereqs, contradictions, correlations = [], [], []
    if not rollouts:
        if not gaps:
            return None
        for key in ("rollout_observed", "changed_field_mapped", "symptom_confined_to_new_revision"):
            prereqs.append(_prereq(key, "blocked_by_gap", gaps=gap_ids, reason="rollout_evidence_unavailable"))
        return _hypothesis(mechanism, entity, "unresolved", prereqs, [], [], gap_ids)

    prereqs.append(_prereq("rollout_observed", "satisfied", [r.evidence_id for r in rollouts]))
    field_map = CATALOG[mechanism]["symptom_by_changed_field"]
    mapped = [r.evidence_id for r in rollouts
              if any(f in field_map for f in r.attributes.get("changed_fields", []))]
    prereqs.append(_prereq("changed_field_mapped", "satisfied" if mapped else "unsatisfied",
                           mapped or [r.evidence_id for r in rollouts],
                           reason=None if mapped else "no_mechanism_maps_changed_fields"))

    templates = set(CATALOG["config_value_change"]["symptom_by_config_key"].values()) | set(field_map.values())
    new_rs = {r.attributes.get("new_replicaset") for r in rollouts}
    confined, unknown = [], False
    for pod_name in ctx.workload_pods():
        pod = ctx.pods[pod_name]
        for sym in sorted(ctx.logs(pod_name, tuple(templates)), key=lambda e: e.evidence_id):
            owner = pod.attributes.get("owner_replicaset")
            rs = ctx.replicasets.get(owner)
            if rs is None:
                unknown = True
            elif owner in new_rs:
                confined.append(sym.evidence_id)
            else:
                contradictions.append({"key": "symptom_on_previous_revision_pod",
                                       "evidence_ids": sorted([sym.evidence_id, pod.evidence_id, rs.evidence_id])})
    if contradictions:
        result, reason = "contradicted", "symptom_on_previous_revision_pod"
    elif confined and not unknown:
        result, reason = "satisfied", None
    else:
        result, reason = "unsatisfied", "revision_of_symptomatic_pods_unknown"
    prereqs.append(_prereq("symptom_confined_to_new_revision", result,
                           confined + [i for c in contradictions for i in c["evidence_ids"]], reason=reason))
    for r in rollouts:
        correlations += _correlations(ctx, r)
    status = _status(prereqs, contradictions, gaps)
    return _hypothesis(mechanism, entity, status, prereqs, contradictions, correlations, gap_ids)


def _hypothesis(mechanism, entity, status, prereqs, contradictions, correlations, gap_ids):
    hyp_id = _hyp_id(mechanism, entity)
    for p in prereqs:
        p["assertion_key"] = f"{hyp_id}#{p['key']}"
    return {"hypothesis_id": hyp_id, "mechanism": mechanism, "entity": entity, "status": status,
            "rule_version": LEDGER_RULE_VERSION, "prerequisites": prereqs,
            "contradictions": sorted(contradictions, key=lambda c: (c["key"], c["evidence_ids"])),
            "correlations": sorted(correlations, key=lambda c: (c["change"], c["symptom"])),
            "limiting_gap_ids": sorted(gap_ids)}


def evaluate(ctx):
    """Enumerate scenario-declared candidates and return (ledger, outcome)."""
    workload = ctx.plan["candidate_scope"]["workload"]
    namespace = workload["namespace"]
    configmaps = set(ctx.cm_changes)
    for pod_name in ctx.workload_pods():
        for vol in ctx.pods[pod_name].attributes.get("configmap_volumes", []):
            configmaps.add(vol.get("configmap"))
    hypotheses = [evaluate_config(ctx, name, namespace) for name in sorted(n for n in configmaps if n)]
    rollout = evaluate_rollout(ctx, workload["name"], namespace)
    if rollout is not None:
        hypotheses.append(rollout)
    hypotheses.sort(key=lambda h: h["hypothesis_id"])

    supported = [h for h in hypotheses if h["status"] == "supported"]
    if len(supported) == 1:
        outcome = {"status": "resolved", "best_supported": supported[0]["hypothesis_id"],
                   "mechanism": supported[0]["mechanism"], "entity": supported[0]["entity"], "reasons": []}
    else:
        reasons = ["multiple_supported_hypotheses"] if supported else ["no_supported_hypothesis"]
        for h in hypotheses:
            if h["status"] == "unresolved":
                blocked = sorted({g for p in h["prerequisites"] for g in p["gap_ids"]})
                reasons.append(f"{h['hypothesis_id']}:unresolved" + (f":gaps={','.join(blocked)}" if blocked else ""))
        outcome = {"status": "abstained", "best_supported": None, "mechanism": None, "entity": None,
                   "reasons": reasons}
    ledger = {"rule_version": LEDGER_RULE_VERSION, "catalog_version": CATALOG["version"],
              "hypotheses": hypotheses}
    return ledger, outcome
