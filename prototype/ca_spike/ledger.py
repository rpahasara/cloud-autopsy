"""Hypothesis ledger: finite versioned mechanism templates, support, contradiction, abstention.

Each hypothesis is bound to one specific change (one ConfigMap resourceVersion or one
Deployment rollout); mapping, consumption and symptom evidence must all belong to that
same change. Temporal proximity is recorded as correlation only and never counts as
support. A hypothesis is ``supported`` only when every prerequisite is satisfied, no
mandatory gap affects its mechanism and no contradiction was observed. Exactly one
supported hypothesis resolves the investigation; otherwise the engine abstains.
"""

from decimal import Decimal, InvalidOperation

from .canonical import canonical_bytes, sha256_hex

LEDGER_RULE_VERSION = "ca-ledger/0.2-spike"

CATALOG = {
    "version": "ca-mech/0.2-spike",
    "config_value_change": {
        # ConfigMap data key -> symptom template expected when the limit is reduced
        "symptom_by_config_key": {"pool.maxConnections": "POOL_EXHAUSTED"},
    },
    "deployment_rollout": {
        # Only pod-template field changes that carry a typed config_key and before/after values
        # are mapped. Image-only changes have no mechanism template in this catalog.
        "symptom_by_config_key": {"pool.maxConnections": "POOL_EXHAUSTED"},
    },
}

CONFIG_TEMPLATES = ("CONFIG_LOADED", "CONFIG_RELOADED")


def symptom_template_set():
    return {t for m in ("config_value_change", "deployment_rollout")
            for t in CATALOG[m]["symptom_by_config_key"].values()}


def _dec(text):
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError):
        return None


def _hyp_id(mechanism, entity, change_id):
    return "hyp:" + sha256_hex(canonical_bytes(
        {"mechanism": mechanism, "entity": entity, "change": change_id, "rule": LEDGER_RULE_VERSION}))[:16]


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


def _global_symptoms(ctx):
    return sorted(r.inputs[0] for r in ctx.relations if r.relation_type in ("metric_symptom", "alert_symptom"))


def _any_symptom(ctx):
    return bool(_global_symptoms(ctx)) or any(r.relation_type == "symptom_on_pod" for r in ctx.relations)


def _mapping(prereq_key, value_changes, symptom_map, evidence_id, unmapped_reason):
    """Map typed (key, before, after) value changes to a symptom template; a reduction is required."""
    result, template, reason = "unsatisfied", None, unmapped_reason
    for key, before, after in value_changes:
        mapped = symptom_map.get(key)
        if mapped is None:
            continue
        b, a = _dec(before), _dec(after)
        if b is None or a is None:
            result, reason = "unsatisfied", "non_numeric_value"
        elif a < b:
            return _prereq(prereq_key, "satisfied", [evidence_id]), mapped, key
        else:
            result, reason = "contradicted", "limit_not_reduced"
    return _prereq(prereq_key, result, [evidence_id], reason=reason), template, None


def _consumption_chain(ctx, change, relation_type, template, pods):
    """Prerequisites linking this specific change to consumption and then symptom, per pod."""
    consumed = {}
    for r in ctx.relations:
        if r.relation_type == relation_type and r.inputs[2] == change.evidence_id:
            consumed.setdefault(r.inputs[1], []).append(r)
    symptomatic = {p.evidence_id: ctx.logs(p, (template,)) for p in pods} if template else {}
    symptomatic = {pid: logs for pid, logs in symptomatic.items() if logs}
    both = sorted(set(symptomatic) & set(consumed))
    cons_ev = [i for pid in both for r in consumed[pid] for i in r.inputs]
    consumed_prereq = _prereq("consumed_by_symptomatic_pods", "satisfied" if both else "unsatisfied", cons_ev,
                              reason=None if both else "no_symptomatic_pod_consumed_this_change")
    ordered_ev = []
    for pid in both:
        for r in consumed[pid]:
            cons_log = ctx.by_id[r.inputs[0]]
            for sym in symptomatic[pid]:
                if ctx.order(cons_log, sym) == "before":
                    ordered_ev += [cons_log.evidence_id, sym.evidence_id]
    after_prereq = _prereq("symptom_after_consumption", "satisfied" if ordered_ev else "unsatisfied",
                           ordered_ev + (_global_symptoms(ctx) if ordered_ev else []),
                           reason=None if ordered_ev else "no_strictly_ordered_consumption_then_symptom")
    return consumed_prereq, after_prereq, symptomatic


def _latest_config_before(ctx, pod, symptom_log, config_key):
    """Latest config load/reload log in the same pod strictly before the symptom, if determinable."""
    prior = [c for c in ctx.logs(pod, CONFIG_TEMPLATES)
             if c.attributes.get("fields", {}).get("config_key") == config_key and ctx.order(c, symptom_log) == "before"]
    for c in prior:
        if all(o is c or ctx.order(o, c) == "before" for o in prior):
            return c
    return None


def _correlations(ctx, change):
    return [{"change": change.evidence_id, "symptom": sid, "order": ctx.order(change, ctx.by_id[sid]),
             "note": "temporal proximity only; not mechanism support"} for sid in _global_symptoms(ctx)]


def _hypothesis(mechanism, entity, change_id, status, prereqs, contradictions, correlations, gap_ids):
    hyp_id = _hyp_id(mechanism, entity, change_id)
    for p in prereqs:
        p["assertion_key"] = f"{hyp_id}#{p['key']}"
    return {"hypothesis_id": hyp_id, "mechanism": mechanism, "entity": entity, "change_evidence_id": change_id,
            "status": status, "rule_version": LEDGER_RULE_VERSION, "prerequisites": prereqs,
            "contradictions": sorted(contradictions, key=lambda c: (c["key"], c["evidence_ids"])),
            "correlations": sorted(correlations, key=lambda c: (c["change"], c["symptom"])),
            "limiting_gap_ids": sorted(gap_ids)}


def _without_change(ctx, mechanism, entity, keys, unavailable_reason, absent_reason):
    gaps = _blocking_gaps(ctx, mechanism)
    result = "blocked_by_gap" if gaps else "unsatisfied"
    reason = unavailable_reason if gaps else absent_reason
    prereqs = [_prereq(k, result, gaps=[g.gap_id for g in gaps], reason=reason) for k in keys]
    return _hypothesis(mechanism, entity, None, "unresolved", prereqs, [], [], [g.gap_id for g in gaps])


CONFIG_KEYS = ("change_observed", "mechanism_mapped", "consumed_by_symptomatic_pods", "symptom_after_consumption")
ROLLOUT_KEYS = ("rollout_observed", "changed_field_mapped", "consumed_by_symptomatic_pods",
                "symptom_after_consumption", "symptom_confined_to_new_revision")


def evaluate_config_change(ctx, change):
    mechanism = "config_value_change"
    entity = {"kind": "ConfigMap", "namespace": change.entity["namespace"], "name": change.entity["name"]}
    gaps = _blocking_gaps(ctx, mechanism)
    a = change.attributes
    value_change = (a.get("data_key"), a.get("before_value"), a.get("after_value"))
    mapped, template, key = _mapping("mechanism_mapped", [value_change], CATALOG[mechanism]["symptom_by_config_key"],
                                     change.evidence_id, "unmapped_config_key")
    pods = [p for p in ctx.workload_pods() if p.entity.get("namespace") == entity["namespace"]]
    consumed, after, symptomatic = _consumption_chain(ctx, change, "config_value_consumed", template, pods)
    contradictions = []
    for pid, logs in sorted(symptomatic.items()):
        for sym in logs:
            latest = _latest_config_before(ctx, ctx.by_id[pid], sym, key)
            if latest is not None and latest.attributes["fields"].get("value_sha256") != a.get("after_value_sha256"):
                contradictions.append({"key": "symptom_with_previous_value",
                                       "evidence_ids": sorted([latest.evidence_id, sym.evidence_id])})
    prereqs = [_prereq("change_observed", "satisfied", [change.evidence_id]), mapped, consumed, after]
    return _hypothesis(mechanism, entity, change.evidence_id, _status(prereqs, contradictions, gaps), prereqs,
                       contradictions, _correlations(ctx, change), [g.gap_id for g in gaps])


def evaluate_rollout(ctx, rollout):
    mechanism = "deployment_rollout"
    entity = {"kind": "Deployment", "namespace": rollout.entity["namespace"], "name": rollout.entity["name"]}
    gaps = _blocking_gaps(ctx, mechanism)
    changes = [(fc.get("config_key"), fc.get("before_value"), fc.get("after_value"))
               for fc in rollout.attributes.get("field_changes", [])]
    mapped, template, _key = _mapping("changed_field_mapped", changes, CATALOG[mechanism]["symptom_by_config_key"],
                                      rollout.evidence_id, "no_mechanism_maps_changed_fields")
    pods = [p for p in ctx.workload_pods() if p.entity.get("namespace") == entity["namespace"]]
    consumed, after, _symptomatic = _consumption_chain(ctx, rollout, "rollout_value_consumed", template, pods)

    new_rs = rollout.attributes.get("new_replicaset")
    confined, contradictions, unknown = [], [], False
    for pod in pods:
        for sym in ctx.logs(pod, tuple(sorted(symptom_template_set()))):
            rs = ctx.owner_replicaset(pod)
            if rs is None:
                unknown = True
            elif rs.entity["name"] == new_rs:
                confined.append(sym.evidence_id)
            else:
                contradictions.append({"key": "symptom_on_previous_revision_pod",
                                       "evidence_ids": sorted([sym.evidence_id, pod.evidence_id, rs.evidence_id])})
    if contradictions:
        result, reason = "contradicted", "symptom_on_previous_revision_pod"
    elif confined and not unknown:
        result, reason = "satisfied", None
    elif not confined and not unknown:
        result, reason = "unsatisfied", "no_symptom_observed"
    else:
        result, reason = "unsatisfied", "revision_of_symptomatic_pods_unknown"
    confined_prereq = _prereq("symptom_confined_to_new_revision", result,
                              confined + [i for c in contradictions for i in c["evidence_ids"]], reason=reason)
    prereqs = [_prereq("rollout_observed", "satisfied", [rollout.evidence_id]), mapped, consumed, after,
               confined_prereq]
    return _hypothesis(mechanism, entity, rollout.evidence_id, _status(prereqs, contradictions, gaps), prereqs,
                       contradictions, _correlations(ctx, rollout), [g.gap_id for g in gaps])


def evaluate(ctx):
    """Enumerate scenario-declared candidates (one per specific change) and return (ledger, outcome)."""
    workload = ctx.plan["candidate_scope"]["workload"]
    ns = workload["namespace"]
    hypotheses = []
    mounted = {vol.get("configmap") for pod in ctx.workload_pods() for vol in pod.attributes.get("configmap_volumes", [])}
    for name in sorted(n for n in mounted | {n for (cns, n) in ctx.cm_changes if cns == ns} if n):
        changes = ctx.cm_changes.get((ns, name), [])
        if changes:
            hypotheses += [evaluate_config_change(ctx, c) for c in changes]
        else:
            hypotheses.append(_without_change(ctx, "config_value_change",
                                              {"kind": "ConfigMap", "namespace": ns, "name": name}, CONFIG_KEYS,
                                              "change_evidence_unavailable", "no_change_observed"))
    rollouts = ctx.rollouts.get((ns, workload["name"]), [])
    if rollouts:
        hypotheses += [evaluate_rollout(ctx, r) for r in rollouts]
    elif _blocking_gaps(ctx, "deployment_rollout"):
        hypotheses.append(_without_change(ctx, "deployment_rollout",
                                          {"kind": "Deployment", "namespace": ns, "name": workload["name"]},
                                          ROLLOUT_KEYS, "rollout_evidence_unavailable", "no_rollout_observed"))
    hypotheses.sort(key=lambda h: h["hypothesis_id"])

    supported = [h for h in hypotheses if h["status"] == "supported"]
    if len(supported) == 1:
        outcome = {"status": "resolved", "best_supported": supported[0]["hypothesis_id"],
                   "mechanism": supported[0]["mechanism"], "entity": supported[0]["entity"],
                   "change_evidence_id": supported[0]["change_evidence_id"], "reasons": []}
    else:
        reasons = [] if _any_symptom(ctx) else ["no_symptom_observed"]
        reasons.append("multiple_supported_hypotheses" if supported else "no_supported_hypothesis")
        for h in hypotheses:
            if h["status"] == "unresolved":
                blocked = sorted({g for p in h["prerequisites"] for g in p["gap_ids"]})
                reasons.append(f"{h['hypothesis_id']}:unresolved" + (f":gaps={','.join(blocked)}" if blocked else ""))
        outcome = {"status": "abstained", "best_supported": None, "mechanism": None, "entity": None,
                   "change_evidence_id": None, "reasons": reasons}
    ledger = {"rule_version": LEDGER_RULE_VERSION, "catalog_version": CATALOG["version"],
              "hypotheses": hypotheses}
    return ledger, outcome
