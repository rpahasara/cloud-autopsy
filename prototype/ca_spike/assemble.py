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
from .ledger import CATALOG, LEDGER_RULE_VERSION, evaluate
from .model import IDENTITY_ALGORITHM, SCHEMA_VERSION, Gap, NormalizationError, Relation, normalize
from .timemodel import TIME_RULE_VERSION, compare

MANIFEST_VERSION = "ca-manifest/0.1-spike"
BUNDLE_VERSION = "ca-bundle/0.1-spike"
RELATION_RULE_VERSION = "ca-rel/0.1-spike"
GAP_RULE_VERSION = "ca-gap/0.1-spike"
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


def detect_gaps(plan, outcomes, conflicts, rejected):
    by_query = {o.query_id: o for o in outcomes}
    found = []
    for expected in plan["expected_acquisitions"]:
        outcome = by_query.get(expected["query_id"])
        if outcome is None:
            gap_type, reason = "missing", "acquisition_absent"
        elif outcome.status == "failed":
            gap_type, reason = "failed", outcome.reason or "unspecified_failure"
        elif outcome.status == "denied":
            gap_type, reason = "failed", "authorization_denied"
        elif outcome.status == "truncated":
            gap_type, reason = "truncated", outcome.reason or "bound_exceeded"
        else:
            continue
        found.append((expected, gap_type, reason))
    plan_by_query = {e["query_id"]: e for e in plan["expected_acquisitions"]}
    for query_id, reason in sorted(set(conflicts) | set(rejected)):
        expected = plan_by_query.get(query_id, {"query_id": query_id, "source_id": None, "mandatory_for": []})
        found.append((expected, "unverifiable", reason))

    gaps = []
    for expected, gap_type, reason in found:
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
        "acquisitions": sorted((asdict(o) for o in outcomes), key=lambda o: o["query_id"]),
        "evidence": [[e.evidence_id, e.content_digest] for e in ordered],
        "quarantined_identity_conflicts": sorted(conflicted),
        "gaps": [g.gap_id for g in gaps],
        "excluded_volatile_fields": list(VOLATILE_FIELDS),
    }
    return {"manifest": manifest, "manifest_digest": digest(manifest), "evidence": ordered, "gaps": gaps,
            "outcomes": outcomes, "duplicates_dropped": duplicates}


class Context:
    """Indexed view of sealed evidence used by relation and ledger rules."""

    def __init__(self, evidence, gaps, plan):
        self.plan = plan
        self.gaps = gaps
        self.by_id = {e.evidence_id: e for e in evidence}
        self.pods, self.replicasets, self.rollouts, self.cm_changes = {}, {}, {}, {}
        self.logs_by_pod, self.metric_samples, self.alerts = {}, [], []
        for e in evidence:
            name = e.entity.get("name")
            if e.observation_kind == "pod":
                self.pods[name] = e
            elif e.observation_kind == "replicaset":
                self.replicasets[name] = e
            elif e.observation_kind == "deployment_rollout":
                self.rollouts.setdefault(name, []).append(e)
            elif e.observation_kind == "configmap_change":
                self.cm_changes.setdefault(name, []).append(e)
            elif e.observation_kind == "log_line":
                self.logs_by_pod.setdefault(e.attributes.get("pod"), []).append(e)
            elif e.observation_kind == "metric_sample":
                self.metric_samples.append(e)
            elif e.observation_kind == "alert_firing":
                self.alerts.append(e)
        self._order_cache = {}
        self.relations = []

    def order(self, a, b):
        """Order of evidence a relative to b using primary (event) timestamps."""
        key = (a.evidence_id, b.evidence_id)
        if key not in self._order_cache:
            ta, tb = a.primary_time(), b.primary_time()
            self._order_cache[key] = compare(ta, tb) if ta and tb else ("unordered", "no_timestamp")
        return self._order_cache[key][0]

    def logs(self, pod_name, templates):
        return [e for e in self.logs_by_pod.get(pod_name, []) if e.attributes.get("template") in templates]

    def workload_pods(self):
        workload = self.plan["candidate_scope"]["workload"]["name"]
        names = []
        for name, pod in self.pods.items():
            rs = self.replicasets.get(pod.attributes.get("owner_replicaset"))
            if rs is not None and rs.attributes.get("owner_deployment") == workload:
                names.append(name)
        return sorted(names)

    def add_relation(self, relation_type, inputs, **attributes):
        inputs = tuple(inputs)
        descriptor = {"type": relation_type, "inputs": list(inputs), "rule": RELATION_RULE_VERSION}
        self.relations.append(Relation(relation_id=_short_id("rel", descriptor), relation_type=relation_type,
                                       inputs=inputs, rule_version=RELATION_RULE_VERSION, attributes=attributes))


def derive_relations(ctx):
    symptom_templates = set(CATALOG["config_value_change"]["symptom_by_config_key"].values())
    for name, pod in sorted(ctx.pods.items()):
        rs = ctx.replicasets.get(pod.attributes.get("owner_replicaset"))
        if rs is not None:
            ctx.add_relation("pod_owned_by_replicaset", [pod.evidence_id, rs.evidence_id])
        for vol in pod.attributes.get("configmap_volumes", []):
            ctx.add_relation("pod_mounts_configmap", [pod.evidence_id], configmap=vol.get("configmap"),
                             sub_path=bool(vol.get("sub_path")), hot_reload_eligible=not vol.get("sub_path"))
        for log in sorted(ctx.logs_by_pod.get(name, []), key=lambda e: e.evidence_id):
            ctx.add_relation("log_from_pod", [log.evidence_id, pod.evidence_id])
            if log.attributes.get("template") in symptom_templates:
                ctx.add_relation("symptom_on_pod", [log.evidence_id, pod.evidence_id],
                                 template=log.attributes["template"])
    for name, rs in sorted(ctx.replicasets.items()):
        for rollout in ctx.rollouts.get(rs.attributes.get("owner_deployment"), []):
            role = ("new" if rollout.attributes.get("new_replicaset") == name else
                    "old" if rollout.attributes.get("old_replicaset") == name else None)
            if role:
                ctx.add_relation("replicaset_in_rollout", [rs.evidence_id, rollout.evidence_id], role=role)
    for cm_name, changes in sorted(ctx.cm_changes.items()):
        for change in changes:
            for pod_name, pod in sorted(ctx.pods.items()):
                mounts = [v for v in pod.attributes.get("configmap_volumes", []) if v.get("configmap") == cm_name]
                if not mounts:
                    continue
                eligible = any(not v.get("sub_path") for v in mounts)
                for log in sorted(ctx.logs(pod_name, CONFIG_TEMPLATES), key=lambda e: e.evidence_id):
                    fields = log.attributes.get("fields", {})
                    if (fields.get("config_key") != change.attributes.get("data_key") or
                            fields.get("value_sha256") != change.attributes.get("after_value_sha256")):
                        continue
                    mode = "reload" if log.attributes["template"] == "CONFIG_RELOADED" else "load"
                    if mode == "reload" and not eligible:
                        continue
                    order = ctx.order(log, change)
                    if order == "before":
                        continue
                    ctx.add_relation("config_value_consumed",
                                     [log.evidence_id, pod.evidence_id, change.evidence_id],
                                     mode=mode, log_vs_change=order)
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
