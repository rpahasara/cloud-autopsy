"""Sealing, derived relations, gaps, ordering and deterministic bundle assembly.

Determinism boundary: the bundle digest covers sorted evidence identities/digests,
relations, gaps, ordering, ledger and rule versions. Run IDs, wall-clock times, stage
timings, delivery order, duplicate counts and synthesis output are excluded and
listed in the manifest.
"""

from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from . import ENGINE_VERSION
from .canonical import CANON_VERSION, canonical_bytes, digest, sha256_hex
from .ledger import CATALOG, LEDGER_RULE_VERSION, evaluate, symptom_template_set
from .model import IDENTITY_ALGORITHM, SCHEMA_VERSION, Gap, NormalizationError, Relation, normalize
from .timemodel import TIME_RULE_VERSION, compare

MANIFEST_VERSION = "ca-manifest/0.2-spike"
BUNDLE_VERSION = "ca-bundle/0.2-spike"
RELATION_RULE_VERSION = "ca-rel/0.2-spike"
GAP_RULE_VERSION = "ca-gap/0.2-spike"
VOLATILE_FIELDS = (
    "run_id", "wall_clock_times", "stage_timings_ns", "delivery_order", "duplicate_deliveries",
    "variant_label", "synthesis_attempt", "host_environment")

CONFIG_TEMPLATES = ("CONFIG_LOADED", "CONFIG_RELOADED")


def versions():
    return {
        "engine": ENGINE_VERSION, "schema": SCHEMA_VERSION, "identity": IDENTITY_ALGORITHM,
        "canonicalization": CANON_VERSION, "time_rule": TIME_RULE_VERSION,
        "relation_rule": RELATION_RULE_VERSION, "gap_rule": GAP_RULE_VERSION,
        "mechanism_catalog": CATALOG["version"], "ledger_rule": LEDGER_RULE_VERSION,
        "manifest": MANIFEST_VERSION, "bundle": BUNDLE_VERSION,
    }


def _short_id(prefix, value):
    return f"{prefix}:{sha256_hex(canonical_bytes(value))[:24]}"


def _decimal(text):
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError):
        return None


def _outcome_gap(outcome):
    """Gap (type, reason) for one acquisition outcome; only complete and clean-empty close coverage."""
    if outcome.status in ("complete", "empty"):
        return None
    if outcome.status == "failed":
        return "failed", outcome.reason or "unspecified_failure"
    if outcome.status == "denied":
        return "failed", "authorization_denied"
    if outcome.status == "truncated":
        return "truncated", outcome.reason or "bound_exceeded"
    if outcome.status == "partial":
        return "missing", "partial_coverage"
    return "unverifiable", f"unknown_status:{outcome.status}"


def detect_gaps(plan, outcomes, conflicts, rejected):
    """Fail closed: every expected query must have exactly one complete or clean-empty outcome."""
    by_query = {}
    for o in outcomes:
        by_query.setdefault(o.query_id, []).append(o)
    found = set()
    for expected in plan["expected_acquisitions"]:
        query_outcomes = by_query.get(expected["query_id"], [])
        if not query_outcomes:
            found.add((expected["query_id"], "missing", "acquisition_absent"))
        if len(query_outcomes) > 1:
            found.add((expected["query_id"], "unverifiable", "duplicate_acquisition"))
        for outcome in query_outcomes:
            gap = _outcome_gap(outcome)
            if gap:
                found.add((expected["query_id"],) + gap)
    for query_id, reason in set(conflicts) | set(rejected):
        found.add((query_id, "unverifiable", reason))

    plan_by_query = {e["query_id"]: e for e in plan["expected_acquisitions"]}
    gaps = []
    for query_id, gap_type, reason in sorted(found):
        expected = plan_by_query.get(query_id, {"query_id": query_id, "source_id": None, "mandatory_for": []})
        descriptor = {"query_id": expected["query_id"], "type": gap_type, "reason": reason,
                      "window": plan["incident_window"], "rule": GAP_RULE_VERSION}
        gaps.append(Gap(gap_id=_short_id("gap", descriptor), query_id=expected["query_id"],
                        source_id=expected.get("source_id"), gap_type=gap_type, reason=reason,
                        window=plan["incident_window"], detector_rule=GAP_RULE_VERSION,
                        affects_mechanisms=tuple(sorted(expected.get("mandatory_for", [])))))
    return sorted(gaps, key=lambda g: g.gap_id)


def seal(outcomes, deliveries, clock_domains, plan, fixture_info):
    """Normalize deliveries into a frozen evidence set and an immutable manifest."""
    evidence, conflicted, rejected = {}, set(), set()
    conflicts, duplicates = set(), 0
    for query_id, source_id, obs in deliveries:
        try:
            ev = normalize(obs, query_id, source_id, clock_domains)
        except NormalizationError:
            rejected.add((query_id, "normalization_rejected"))
            continue
        if ev.evidence_id in conflicted:
            continue
        prior = evidence.get(ev.evidence_id)
        if prior is None:
            evidence[ev.evidence_id] = ev
        elif prior.content_digest == ev.content_digest:
            duplicates += 1
        else:
            conflicted.add(ev.evidence_id)
            conflicts.add((prior.query_id, "identity_conflict"))
            del evidence[ev.evidence_id]

    gaps = detect_gaps(plan, outcomes, conflicts, rejected)
    ordered = [evidence[k] for k in sorted(evidence)]
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "versions": versions(),
        "fixture": fixture_info,
        "source_plan": {"plan_id": plan["plan_id"], "plan_version": plan["plan_version"], "digest": digest(plan)},
        "clock_domains_digest": digest(clock_domains),
        "acquisitions": sorted((asdict(o) for o in outcomes), key=canonical_bytes),
        "evidence": [[e.evidence_id, e.content_digest] for e in ordered],
        "quarantined_identity_conflicts": sorted(conflicted),
        "gaps": [g.gap_id for g in gaps],
        "excluded_volatile_fields": list(VOLATILE_FIELDS),
    }
    return {"manifest": manifest, "manifest_digest": digest(manifest), "evidence": ordered, "gaps": gaps,
            "outcomes": outcomes, "duplicates_dropped": duplicates}


class Context:
    """Indexed view of sealed evidence used by relation and ledger rules.

    Kubernetes objects are joined by (namespace, name) within one source; logs join to pods
    by the pod UID carried as the log's source UID. If one (kind, namespace, name) maps to
    more than one source UID, the identity is ambiguous: it is reported and excluded from
    every join rather than resolved by last-write-wins.
    """

    def __init__(self, evidence, gaps, plan):
        self.plan = plan
        self.gaps = gaps
        self.by_id = {e.evidence_id: e for e in evidence}
        self.metric_samples, self.alerts, self.ambiguities = [], [], []
        grouped = {}
        for e in evidence:
            key = (e.observation_kind, e.source_id, str(e.entity.get("namespace")), str(e.entity.get("name")))
            if e.observation_kind in ("pod", "replicaset", "deployment_rollout", "configmap_change"):
                grouped.setdefault(key, []).append(e)
            elif e.observation_kind == "metric_sample":
                self.metric_samples.append(e)
            elif e.observation_kind == "alert_firing":
                self.alerts.append(e)
        self.pods, self.replicasets, self.rollouts, self.cm_changes = {}, {}, {}, {}
        for (kind, _source, ns, name), items in sorted(grouped.items()):
            if len({e.source_uid for e in items}) > 1:
                self.ambiguities.append({"kind": kind, "namespace": ns, "name": name,
                                         "evidence_ids": sorted(e.evidence_id for e in items)})
                continue
            items = sorted(items, key=lambda e: e.evidence_id)
            if kind == "pod" and len(items) == 1:
                self.pods[(ns, name)] = items[0]
            elif kind == "replicaset" and len(items) == 1:
                self.replicasets[(ns, name)] = items[0]
            elif kind == "deployment_rollout":
                self.rollouts[(ns, name)] = items
            elif kind == "configmap_change":
                self.cm_changes[(ns, name)] = items
            else:
                self.ambiguities.append({"kind": kind, "namespace": ns, "name": name,
                                         "evidence_ids": [e.evidence_id for e in items]})
        pods_by_uid = {p.source_uid: p for p in self.pods.values()}
        self.logs_by_pod = {}
        for e in evidence:
            if e.observation_kind != "log_line":
                continue
            owner = pods_by_uid.get(e.source_uid)
            if owner is not None and owner.entity.get("namespace") == e.entity.get("namespace"):
                self.logs_by_pod.setdefault(owner.evidence_id, []).append(e)
        self._order_cache = {}
        self.relations = []
        self.chronology_rejections = []

    def order(self, a, b):
        """Order of evidence a relative to b using primary (event) timestamps."""
        key = (a.evidence_id, b.evidence_id)
        if key not in self._order_cache:
            ta, tb = a.primary_time(), b.primary_time()
            self._order_cache[key] = compare(ta, tb) if ta and tb else ("unordered", "no_timestamp")
        return self._order_cache[key][0]

    def logs(self, pod, templates):
        found = (e for e in self.logs_by_pod.get(pod.evidence_id, []) if e.attributes.get("template") in templates)
        return sorted(found, key=lambda e: e.evidence_id)

    def owner_replicaset(self, pod):
        return self.replicasets.get((pod.entity.get("namespace"), pod.attributes.get("owner_replicaset")))

    def workload_pods(self):
        workload = self.plan["candidate_scope"]["workload"]
        pods = []
        for (ns, _name), pod in sorted(self.pods.items()):
            rs = self.owner_replicaset(pod)
            if (ns == workload["namespace"] and rs is not None
                    and rs.attributes.get("owner_deployment") == workload["name"]):
                pods.append(pod)
        return pods

    def add_relation(self, relation_type, inputs, **attributes):
        inputs = tuple(inputs)
        descriptor = {"type": relation_type, "inputs": list(inputs), "rule": RELATION_RULE_VERSION}
        self.relations.append(Relation(relation_id=_short_id("rel", descriptor), relation_type=relation_type,
                                       inputs=inputs, rule_version=RELATION_RULE_VERSION, attributes=attributes))

    def consumption(self, relation_type, log, pod, change, mode):
        """Accept a value consumption only when the log is strictly after the change (fail closed)."""
        order = self.order(log, change)
        if order == "after":
            self.add_relation(relation_type, [log.evidence_id, pod.evidence_id, change.evidence_id], mode=mode)
            return
        self.chronology_rejections.append({
            "relation_type": relation_type, "inputs": [log.evidence_id, pod.evidence_id, change.evidence_id],
            "order": order,
            "reason": "consumption_precedes_change" if order == "before" else "consumption_order_unknown"})


def _matches(log, config_key, after_sha):
    fields = log.attributes.get("fields", {})
    return fields.get("config_key") == config_key and fields.get("value_sha256") == after_sha


def derive_relations(ctx):
    symptom_templates = symptom_template_set()
    for _key, pod in sorted(ctx.pods.items()):
        rs = ctx.owner_replicaset(pod)
        if rs is not None:
            ctx.add_relation("pod_owned_by_replicaset", [pod.evidence_id, rs.evidence_id])
        for vol in pod.attributes.get("configmap_volumes", []):
            ctx.add_relation("pod_mounts_configmap", [pod.evidence_id], configmap=vol.get("configmap"),
                             sub_path=bool(vol.get("sub_path")), hot_reload_eligible=not vol.get("sub_path"))
        for log in sorted(ctx.logs_by_pod.get(pod.evidence_id, []), key=lambda e: e.evidence_id):
            ctx.add_relation("log_from_pod", [log.evidence_id, pod.evidence_id])
            if log.attributes.get("template") in symptom_templates:
                ctx.add_relation("symptom_on_pod", [log.evidence_id, pod.evidence_id],
                                 template=log.attributes["template"])
    for (ns, name), rs in sorted(ctx.replicasets.items()):
        for rollout in ctx.rollouts.get((ns, rs.attributes.get("owner_deployment")), []):
            role = ("new" if rollout.attributes.get("new_replicaset") == name else
                    "old" if rollout.attributes.get("old_replicaset") == name else None)
            if role:
                ctx.add_relation("replicaset_in_rollout", [rs.evidence_id, rollout.evidence_id], role=role)
    for (ns, cm_name), changes in sorted(ctx.cm_changes.items()):
        for change in changes:
            for (pod_ns, _pod_name), pod in sorted(ctx.pods.items()):
                mounts = [v for v in pod.attributes.get("configmap_volumes", []) if v.get("configmap") == cm_name]
                if pod_ns != ns or not mounts:
                    continue
                eligible = any(not v.get("sub_path") for v in mounts)
                for log in ctx.logs(pod, CONFIG_TEMPLATES):
                    if not _matches(log, change.attributes.get("data_key"),
                                    change.attributes.get("after_value_sha256")):
                        continue
                    mode = "reload" if log.attributes["template"] == "CONFIG_RELOADED" else "load"
                    if mode == "reload" and not eligible:
                        continue
                    ctx.consumption("config_value_consumed", log, pod, change, mode)
    for (ns, _deployment), rollouts in sorted(ctx.rollouts.items()):
        for rollout in rollouts:
            new_rs = rollout.attributes.get("new_replicaset")
            for fc in rollout.attributes.get("field_changes", []):
                for pod in ctx.workload_pods():
                    if pod.entity.get("namespace") != ns or pod.attributes.get("owner_replicaset") != new_rs:
                        continue
                    for log in ctx.logs(pod, ("CONFIG_LOADED",)):
                        if _matches(log, fc.get("config_key"), fc.get("after_value_sha256")):
                            ctx.consumption("rollout_value_consumed", log, pod, rollout, "load")
    symptom = ctx.plan["symptom"]
    threshold = _decimal(symptom["error_ratio_threshold"])
    for sample in sorted(ctx.metric_samples, key=lambda e: e.evidence_id):
        if sample.attributes.get("series") != symptom["error_ratio_series"]:
            continue
        value = _decimal(sample.attributes.get("value"))
        if value is not None and threshold is not None and value > threshold:
            ctx.add_relation("metric_symptom", [sample.evidence_id], series=symptom["error_ratio_series"])
    for alert in sorted(ctx.alerts, key=lambda e: e.evidence_id):
        if alert.attributes.get("rule") == symptom["alert_rule"]:
            ctx.add_relation("alert_symptom", [alert.evidence_id], rule=symptom["alert_rule"])
    ctx.relations.sort(key=lambda r: r.relation_id)
    ctx.chronology_rejections.sort(key=lambda r: (r["relation_type"], r["inputs"]))


def ordering_table(ctx):
    """Pairwise order of all non-metric evidence (metrics are excluded to bound size)."""
    items = sorted((e for e in ctx.by_id.values() if e.evidence_class != "METRIC"), key=lambda e: e.evidence_id)
    table = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            ta, tb = a.primary_time(), b.primary_time()
            order, basis = compare(ta, tb) if ta and tb else ("unordered", "no_timestamp")
            table.append({"a": a.evidence_id, "b": b.evidence_id, "order": order, "basis": basis})
    return table


def timeline(ctx):
    rows = []
    for e in ctx.by_id.values():
        for t in e.times:
            rows.append({"evidence_id": e.evidence_id, "source_ref": e.source_ref, "time_type": t.type,
                         "raw": t.raw, "clock_domain": t.clock_domain, "clock_status": t.clock_status,
                         "parse_status": t.parse_status, "parsed_utc": t.parsed_utc,
                         "lower_ms": t.lower_ms, "upper_ms": t.upper_ms})
    rows.sort(key=lambda r: (r["lower_ms"] is None, r["lower_ms"] or 0, r["evidence_id"], r["time_type"]))
    return rows


def assemble(sealed, plan):
    """Build the deterministic bundle from sealed evidence; returns (bundle, bundle_digest)."""
    ctx = Context(sealed["evidence"], sealed["gaps"], plan)
    derive_relations(ctx)
    ledger, outcome = evaluate(ctx)
    partial = [g.gap_id for g in sealed["gaps"]]
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "manifest_digest": sealed["manifest_digest"],
        "versions": versions(),
        "evidence_ids": [e.evidence_id for e in sealed["evidence"]],
        "acquisitions": sealed["manifest"]["acquisitions"],
        "gaps": [asdict(g) for g in sealed["gaps"]],
        "relations": [asdict(r) for r in ctx.relations],
        "chronology_rejections": ctx.chronology_rejections,
        "identity_ambiguities": ctx.ambiguities,
        "timeline": timeline(ctx),
        "timeline_note": "Rows are sorted by reference-interval lower bound, then evidence ID. This display order "
                         "is not causal evidence; use the ordering table, where overlap/unknown is unordered.",
        "ordering": ordering_table(ctx),
        "ledger": ledger,
        "outcome": outcome,
        "deterministic_state": "partial" if partial else "deterministic_complete",
        "partial_reasons": [f"gap:{g.query_id}:{g.gap_type}" for g in sealed["gaps"]],
        "limitations": [
            "Synthetic fixture only; no live connector, RBAC or cluster behaviour is exercised.",
            "Supported means supported by these observations under versioned rules, not proof of causality.",
            "Clock bounds are fixture-declared assumptions, not measured skew.",
        ],
        "trust_note": "All evidence attributes are untrusted source data and are never interpreted as instructions.",
    }
    return bundle, digest(bundle)
