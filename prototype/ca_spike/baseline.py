"""Naive temporal-correlation baseline (CA-BENCH-B0 style diagnostic floor).

Picks the change event whose parsed timestamp is closest before the first error-ratio
sample above the alert threshold and reports that change by evidence ID. It ignores clock uncertainty, mechanisms,
consumption, contradictions and gaps, and it never abstains while any change exists.
It reads the same sealed evidence as the engine and never reads ground truth.
"""

from decimal import Decimal, InvalidOperation

from .timemodel import parse_rfc3339_ms

BASELINE_VERSION = "ca-baseline-naive/0.2-spike"
CHANGE_KINDS = {"configmap_change": "config_value_change", "deployment_rollout": "deployment_rollout"}


def _epoch(ev):
    t = ev.primary_time()
    try:
        return parse_rfc3339_ms(t.raw) if t else None
    except ValueError:
        return None


def naive_temporal_correlation(evidence, plan):
    symptom = plan["symptom"]
    threshold = Decimal(symptom["error_ratio_threshold"])
    onset = None
    for ev in evidence:
        if ev.observation_kind != "metric_sample" or ev.attributes.get("series") != symptom["error_ratio_series"]:
            continue
        try:
            above = Decimal(ev.attributes.get("value")) > threshold
        except (InvalidOperation, TypeError):
            continue
        epoch = _epoch(ev)
        if above and epoch is not None and (onset is None or (epoch, ev.evidence_id) < onset):
            onset = (epoch, ev.evidence_id)

    candidates = []
    if onset is not None:
        for ev in evidence:
            epoch = _epoch(ev)
            if ev.observation_kind in CHANGE_KINDS and epoch is not None and epoch <= onset[0]:
                candidates.append({"evidence_id": ev.evidence_id, "source_ref": ev.source_ref,
                                   "mechanism": CHANGE_KINDS[ev.observation_kind], "entity": ev.entity,
                                   "lead_ms": onset[0] - epoch})
    candidates.sort(key=lambda c: (c["lead_ms"], c["evidence_id"]))
    selected = candidates[0] if candidates else None
    return {
        "method": BASELINE_VERSION,
        "symptom_onset_evidence_id": onset[1] if onset else None,
        "candidates": candidates,
        "outcome": {"status": "resolved" if selected else "abstained",
                    "mechanism": selected["mechanism"] if selected else None,
                    "entity": selected["entity"] if selected else None,
                    "change_evidence_id": selected["evidence_id"] if selected else None,
                    "reasons": [] if selected else ["no_change_before_symptom_onset"]},
    }
