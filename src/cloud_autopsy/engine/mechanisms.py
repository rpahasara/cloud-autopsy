"""Hypothesis ledger over the explicit mechanism catalog ``ca-mechanism-catalog/0.1-provisional``.

Two mechanisms, each evaluated once per observed change (never per entity or per guess):

``config_limit_reduction`` -- a ConfigMap change lowers a mapped limit, a pod that mounts that
ConfigMap loads the new value (``CONFIG_LOADED``/``CONFIG_RELOADED`` with the same key and the
SHA-256 of the new value) strictly after the change, and that pod then logs the mapped symptom
strictly after loading it. Contradiction: a mapped symptom on a mounting pod strictly before
the change.

``rollout_limit_reduction`` -- a Deployment rollout whose typed ``field_changes`` lower a mapped
limit, and a pod of the new ReplicaSet logs the mapped symptom strictly after the rollout.
An image-only rollout maps to no mechanism and can never be supported. Contradiction: a
mapped symptom on any pod strictly before the rollout.

Rules:
- Support needs every prerequisite ``satisfied`` with cited evidence. Closeness in time is
  never support: orderings come only from ``timeinterval.compare`` and an unknown order is
  ``unknown``, never assumed.
- A gap on any source that produces an observation kind a mechanism needs is a *limiting
  gap*: the hypothesis cannot be supported, and an ``unobserved_change`` placeholder records
  that a change of that kind may be missing.
- Log messages are free text from an untrusted source and are never read; only the typed
  ``template`` and ``fields`` are.
Status precedence: contradicted, then unresolved (limiting gap or unknown order), then
supported (all satisfied), else not_supported.
"""

from decimal import Decimal, InvalidOperation

from ..contracts import canonical
from ..contracts import timeinterval as ti
from ..contracts.evidence import KINDS
from . import CATALOG_VERSION
from .timeline import event_order

SATISFIED, UNSATISFIED, CONTRADICTED, UNKNOWN, BLOCKED = (
    "satisfied", "unsatisfied", "contradicted", "unknown", "blocked_by_gap")
SUPPORTED, NOT_SUPPORTED, UNRESOLVED, CONTRADICTED_STATUS = "supported", "not_supported", "unresolved", "contradicted"

SYMPTOM_BY_CONFIG_KEY = {"pool.maxConnections": "POOL_EXHAUSTED"}
CONSUMPTION_TEMPLATES = ("CONFIG_LOADED", "CONFIG_RELOADED")
MECHANISMS = {
    "config_limit_reduction": {"change_kind": "configmap_change",
                               "needs_kinds": ("configmap_change", "pod", "log_line")},
    "rollout_limit_reduction": {"change_kind": "deployment_rollout",
                                "needs_kinds": ("deployment_rollout", "pod", "log_line")},
}
CATALOG = {"version": CATALOG_VERSION, "symptom_by_config_key": SYMPTOM_BY_CONFIG_KEY,
           "consumption_templates": list(CONSUMPTION_TEMPLATES),
           "mechanisms": {name: {"change_kind": m["change_kind"], "needs_kinds": list(m["needs_kinds"])}
                          for name, m in MECHANISMS.items()}}


def _decimal(text):
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError):
        return None


class _Context:
    def __init__(self, inp):
        self.inp = inp
        self.domains = inp.clock_domains
        self.by_kind = {}
        for member in inp.members:
            self.by_kind.setdefault(member.evidence.observation_kind, []).append(member.evidence)
        self.pods = {p.entity["name"]: p for p in self.by_kind.get("pod", [])}
        self.logs_by_pod = {}
        for log in self.by_kind.get("log_line", []):
            self.logs_by_pod.setdefault(log.attributes["pod"], []).append(log)
        kinds_by_source_kind = {}
        for spec in KINDS.values():
            kinds_by_source_kind.setdefault(spec.source_kind, set()).add(spec.observation_kind)
        self.source_kinds = {s.source_id: kinds_by_source_kind.get(s.source_kind, set())
                             for s in inp.registry.sources}

    def order(self, a, b):
        return event_order(a, b, self.domains)

    def logs(self, pod_name, templates):
        return [log for log in self.logs_by_pod.get(pod_name, []) if log.attributes["template"] in templates]

    def limiting_gaps(self, mechanism):
        needed = set(MECHANISMS[mechanism]["needs_kinds"])
        return sorted(g["gap_id"] for g in self.inp.gaps if self.source_kinds.get(g["source_id"], set()) & needed)

    def symptom_templates(self):
        return tuple(sorted(set(SYMPTOM_BY_CONFIG_KEY.values())))


def _ordering(a, b, ordering):
    return {"a": a.evidence_id, "b": b.evidence_id, "order": ordering.order, "basis": ordering.basis}


def _prereq(key, result, evidence=(), reason=None, orderings=(), gap_ids=()):
    return {"key": key, "result": result, "reason": reason,
            "evidence_ids": sorted({e.evidence_id for e in evidence}),
            "orderings": sorted(orderings, key=lambda o: (o["a"], o["b"])), "gap_ids": sorted(set(gap_ids))}


def _limit_reduction(key, value_changes, evidence, unmapped_reason):
    """Prerequisite for a typed (config_key, before, after) change lowering a mapped limit."""
    result, reason = UNSATISFIED, unmapped_reason
    for config_key, before, after in value_changes:
        if config_key not in SYMPTOM_BY_CONFIG_KEY:
            continue
        b, a = _decimal(before), _decimal(after)
        if b is None or a is None:
            result, reason = UNSATISFIED, "non_numeric_value"
        elif a < b:
            return _prereq(key, SATISFIED, [evidence]), SYMPTOM_BY_CONFIG_KEY[config_key]
        else:
            result, reason = CONTRADICTED, "limit_not_reduced"
    return _prereq(key, result, [evidence], reason=reason), None


def _status(prereqs, contradictions, limiting):
    if contradictions or any(p["result"] == CONTRADICTED for p in prereqs):
        return CONTRADICTED_STATUS
    if limiting or any(p["result"] in (UNKNOWN, BLOCKED) for p in prereqs):
        return UNRESOLVED
    if all(p["result"] == SATISFIED for p in prereqs):
        return SUPPORTED
    return NOT_SUPPORTED


def _hypothesis(mechanism, change, prereqs, contradictions, limiting):
    change_id = None if change is None else change.evidence_id
    hypothesis_id = canonical.digest({"catalog": CATALOG_VERSION, "mechanism": mechanism, "change": change_id})
    return {"hypothesis_id": hypothesis_id, "mechanism": mechanism, "change_evidence_id": change_id,
            "entity": None if change is None else dict(change.entity),
            "status": _status(prereqs, contradictions, limiting), "prerequisites": prereqs,
            "contradictions": sorted(contradictions, key=lambda c: (c["key"], c["evidence_ids"])),
            "limiting_gap_ids": limiting}


def _ordered_chain(ctx, first, second):
    """Split (a, b) pairs into strictly ordered (a before b) and order-unknown pairs."""
    ordered, unknown = [], []
    for a, b in ((a, b) for a in first for b in second):
        o = ctx.order(a, b)
        if o.order == ti.BEFORE:
            ordered.append((a, b, o))
        elif o.order == ti.UNORDERED:
            unknown.append((a, b, o))
    return ordered, unknown


def _chain_prereq(key, ordered, unknown, missing_reason, extra=()):
    if ordered:
        return _prereq(key, SATISFIED, [x for a, b, _ in ordered for x in (a, b)] + list(extra),
                       orderings=[_ordering(a, b, o) for a, b, o in ordered])
    if unknown:
        return _prereq(key, UNKNOWN, [x for a, b, _ in unknown for x in (a, b)] + list(extra),
                       reason="ordering_unknown", orderings=[_ordering(a, b, o) for a, b, o in unknown])
    return _prereq(key, UNSATISFIED, list(extra), reason=missing_reason)


def evaluate_config_change(ctx, change):
    mechanism = "config_limit_reduction"
    attrs = change.attributes
    key = attrs["data_key"]
    mapped, template = _limit_reduction("limit_reduced", [(key, attrs["before_value"], attrs["after_value"])],
                                        change, "unmapped_config_key")
    mounting = [ctx.pods[name] for name in sorted(ctx.pods)
                if any(v["configmap"] == change.entity["name"] for v in ctx.pods[name].attributes["configmap_volumes"])]
    loads = [log for pod in mounting for log in ctx.logs(pod.entity["name"], CONSUMPTION_TEMPLATES)
             if log.attributes["fields"].get("config_key") == key
             and log.attributes["fields"].get("value_sha256") == attrs["after_value_sha256"]]
    consumed_ordered, consumed_unknown = _ordered_chain(ctx, [change], loads)
    consumed = _chain_prereq("loaded_by_mounting_pod_after_change", consumed_ordered, consumed_unknown,
                             "no_load_of_new_value_observed",
                             extra=[ctx.pods[b.attributes["pod"]] for _, b, _ in consumed_ordered + consumed_unknown])

    symptoms = []
    if template is None:
        symptom = _prereq("symptom_after_load", UNSATISFIED, reason="no_mapped_symptom")
    else:
        pairs_ok, pairs_unknown = [], []
        for _, load, load_order in consumed_ordered + consumed_unknown:
            for sym in ctx.logs(load.attributes["pod"], (template,)):
                o = ctx.order(load, sym)
                if o.order == ti.BEFORE and load_order.order == ti.BEFORE:
                    pairs_ok.append((load, sym, o))
                elif o.order in (ti.BEFORE, ti.UNORDERED):
                    pairs_unknown.append((load, sym, o))
        symptom = _chain_prereq("symptom_after_load", pairs_ok, pairs_unknown, "no_symptom_after_load")
        symptoms = [s for pod in mounting for s in ctx.logs(pod.entity["name"], (template,))]

    contradictions = []
    for sym in symptoms:
        o = ctx.order(sym, change)
        if o.order == ti.BEFORE:
            contradictions.append({"key": "symptom_precedes_change",
                                   "evidence_ids": sorted([sym.evidence_id, change.evidence_id]),
                                   "orderings": [_ordering(sym, change, o)]})
    prereqs = [_prereq("change_observed", SATISFIED, [change]), mapped, consumed, symptom]
    return _hypothesis(mechanism, change, prereqs, contradictions, ctx.limiting_gaps(mechanism))


def evaluate_rollout(ctx, rollout):
    mechanism = "rollout_limit_reduction"
    attrs = rollout.attributes
    changes = [(fc["config_key"], fc["before_value"], fc["after_value"]) for fc in attrs.get("field_changes", ())]
    mapped, template = _limit_reduction("changed_field_lowers_mapped_limit", changes, rollout,
                                        "no_mechanism_maps_changed_fields")
    templates = (template,) if template else ctx.symptom_templates()
    new_pods = [ctx.pods[n] for n in sorted(ctx.pods)
                if ctx.pods[n].attributes["owner_replicaset"] == attrs["new_replicaset"]]
    new_symptoms = [s for pod in new_pods for s in ctx.logs(pod.entity["name"], templates)]
    ordered, unknown = _ordered_chain(ctx, [rollout], new_symptoms)
    symptom = _chain_prereq("symptom_on_new_revision_after_rollout", ordered, unknown,
                            "no_symptom_on_new_revision")
    contradictions = []
    for name in sorted(ctx.pods):
        for sym in ctx.logs(name, templates):
            o = ctx.order(sym, rollout)
            if o.order == ti.BEFORE:
                contradictions.append({"key": "symptom_precedes_rollout",
                                       "evidence_ids": sorted([sym.evidence_id, rollout.evidence_id]),
                                       "orderings": [_ordering(sym, rollout, o)]})
    prereqs = [_prereq("rollout_observed", SATISFIED, [rollout]), mapped, symptom]
    return _hypothesis(mechanism, rollout, prereqs, contradictions, ctx.limiting_gaps(mechanism))


def _unobserved(ctx, mechanism, limiting):
    prereq = _prereq("change_observed", BLOCKED, reason="change_evidence_may_be_missing", gap_ids=limiting)
    return _hypothesis(mechanism, None, [prereq], [], limiting)


def evaluate(inp):
    """Return (hypotheses, outcome) for a verified ``InvestigationInput``."""
    ctx = _Context(inp)
    hypotheses = [evaluate_config_change(ctx, c) for c in ctx.by_kind.get("configmap_change", [])]
    hypotheses += [evaluate_rollout(ctx, r) for r in ctx.by_kind.get("deployment_rollout", [])]
    for mechanism in sorted(MECHANISMS):
        limiting = ctx.limiting_gaps(mechanism)
        if limiting:
            hypotheses.append(_unobserved(ctx, mechanism, limiting))
    hypotheses.sort(key=lambda h: h["hypothesis_id"])

    symptom_seen = any(log.attributes["template"] in ctx.symptom_templates()
                       for log in ctx.by_kind.get("log_line", [])) or bool(ctx.by_kind.get("alert_firing"))
    supported = [h for h in hypotheses if h["status"] == SUPPORTED]
    unresolved = [h for h in hypotheses if h["status"] == UNRESOLVED]
    if symptom_seen and len(supported) == 1 and not unresolved:
        chosen = supported[0]
        cited = sorted({e for p in chosen["prerequisites"] for e in p["evidence_ids"]})
        return hypotheses, {"status": "resolved", "hypothesis_id": chosen["hypothesis_id"],
                            "mechanism": chosen["mechanism"], "change_evidence_id": chosen["change_evidence_id"],
                            "evidence_ids": cited, "reasons": [], "gap_ids": []}
    reasons = set()
    if not symptom_seen:
        reasons.add("no_symptom_observed")
    reasons.add("multiple_supported_hypotheses" if len(supported) > 1 else
                "unresolved_competing_hypotheses" if supported else "no_supported_hypothesis")
    if unresolved:
        reasons.add("unresolved_hypotheses_present")
    if any(p["reason"] == "ordering_unknown" for h in hypotheses for p in h["prerequisites"]):
        reasons.add("ordering_unknown")
    if any(h["contradictions"] for h in hypotheses):
        reasons.add("contradicting_evidence_present")
    gap_ids = sorted({g for h in hypotheses for g in h["limiting_gap_ids"]})
    if gap_ids:
        reasons.add("limiting_evidence_gaps")
    return hypotheses, {"status": "abstained", "hypothesis_id": None, "mechanism": None, "change_evidence_id": None,
                        "evidence_ids": [], "reasons": sorted(reasons), "gap_ids": gap_ids}
