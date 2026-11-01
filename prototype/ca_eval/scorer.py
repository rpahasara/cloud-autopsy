"""Score engine and naive-baseline outputs against pinned ground truth.

Reports raw counts and denominators only; no pass/fail threshold is applied. A zero
denominator is reported as not_evaluated, never 100%.
"""

import hashlib
import json
from pathlib import Path

from . import SCORER_VERSION

PROHIBITED_OUTPUT_KEYS = {"action", "actions", "command", "commands", "tool_calls", "approval", "approved",
                          "execute"}


class TruthIntegrityError(RuntimeError):
    pass


def load_truth(prototype_root, fixture_id, pins_path=None):
    root = Path(prototype_root)
    pins = json.loads((Path(pins_path) if pins_path else root / "ca_eval" / "truth-pins.json").read_bytes())
    pin = pins["truth"][fixture_id]
    data = (root / pin["path"]).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != pin["sha256"]:
        raise TruthIntegrityError({"fixture_id": fixture_id, "expected": pin["sha256"], "actual": actual})
    return json.loads(data), "sha256:" + actual


def ratio(num, den):
    return {"numerator": num, "denominator": den,
            "value": f"{num}/{den}" if den else "not_evaluated", "status": "measured" if den else "not_evaluated"}


def _same_entity(a, b):
    return bool(a and b) and all(a.get(k) == b.get(k) for k in ("kind", "namespace", "name"))


# Evaluator-side mapping from change observation kind to mechanism (kept apart from the engine).
_CHANGE_KIND_MECHANISM = {"configmap_change": "config_value_change", "deployment_rollout": "deployment_rollout"}


def _selected_change(outcome, evidence_by_id):
    """Resolve a resolved outcome's ``change_evidence_id`` to the sealed change's ``source_ref``.

    ``identity`` is ``resolved`` only when the ID names a sealed change record whose kind and
    entity agree with the outcome. Otherwise it is ``missing`` (no change-level identity, as in
    ca-baseline-naive/0.1), ``not_in_evidence`` or ``inconsistent_with_outcome``, and the
    outcome can be neither credited nor cleared of selecting a false cause.
    """
    if outcome.get("status") != "resolved":
        return {"identity": "not_applicable", "change_evidence_id": None, "source_ref": None}
    cid = outcome.get("change_evidence_id")
    if not isinstance(cid, str) or not cid:
        return {"identity": "missing", "change_evidence_id": None, "source_ref": None}
    record = evidence_by_id.get(cid)
    if record is None:
        return {"identity": "not_in_evidence", "change_evidence_id": cid, "source_ref": None}
    consistent = (_CHANGE_KIND_MECHANISM.get(record.get("observation_kind")) == outcome.get("mechanism")
                  and _same_entity(record.get("entity"), outcome.get("entity")))
    return {"identity": "resolved" if consistent else "inconsistent_with_outcome",
            "change_evidence_id": cid, "source_ref": record.get("source_ref")}


def _attribution(outcome, selected, truth, variant_truth):
    """Classify against truth: correct / incorrect / abstained / identity_unverifiable.

    Correct requires the exact causal change (``source_ref``), not just its mechanism and entity.
    """
    if outcome["status"] != "resolved":
        return "abstained"
    if selected["identity"] != "resolved":
        return "identity_unverifiable"
    expected = truth["causal_change"] if variant_truth["expected_cause"] == "causal_change" else None
    if expected and selected["source_ref"] == expected["source_ref"] and outcome["mechanism"] == expected[
            "mechanism"] and _same_entity(outcome["entity"], expected["entity"]):
        return "correct"
    return "incorrect"


def _result_correct(attribution, expected_outcome):
    """Correct cause when one is expected; abstention when truth says the case is unresolvable."""
    return attribution == ("abstained" if expected_outcome == "abstained" else "correct")


def _non_causes(truth):
    """Declared non-causal changes: a single ``false_cause`` or a ``non_causes`` list (benign cases)."""
    return truth.get("non_causes") or ([truth["false_cause"]] if truth.get("false_cause") else [])


def _false_cause(outcome, selected, truth, evidence_by_id, hypotheses=None):
    """Whether a declared non-causal change was selected, judged per exact change (``source_ref``)."""
    non_cause_refs = {fc["source_ref"] for fc in _non_causes(truth)}
    if outcome["status"] == "resolved":
        if selected["identity"] != "resolved":
            return "identity_unverifiable"
        if selected["source_ref"] in non_cause_refs:
            return "selected"
    if hypotheses is None:
        return "not_selected"

    def change_ref(h):
        cid = h.get("change_evidence_id")
        return evidence_by_id.get(cid, {}).get("source_ref") if isinstance(cid, str) else None

    match = [h for h in hypotheses if change_ref(h) in non_cause_refs]
    if not match:
        return "not_evaluated"
    return "rejected" if all(h["status"] in ("contradicted", "unresolved") for h in match) else "not_selected"


def _scan_keys(value, found, path="$"):
    if isinstance(value, dict):
        for k, v in value.items():
            if k.lower() in PROHIBITED_OUTPUT_KEYS:
                found.append(f"{path}.{k}")
            _scan_keys(v, found, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _scan_keys(v, found, f"{path}[{i}]")


def score_run(store, truth, truth_digest, equivalence=None, reference_bundle_digests=None):
    """Score one run directory (an ArtifactStore). ``equivalence`` is the harness repeat result."""
    run = store.get("run.json")
    bundle = store.get("bundle.json")["bundle"]
    evidence = store.get("evidence.json")
    baseline = store.get("baseline.json")
    synthesis = store.get("synthesis.json")
    variant = run["variant"]
    vt = truth["variants"][variant]
    evidence_by_id = {e["evidence_id"]: e for e in evidence}
    id_by_ref = {e["source_ref"]: e["evidence_id"] for e in evidence}
    in_bundle = set(bundle["evidence_ids"])
    hypotheses = bundle["ledger"]["hypotheses"]

    withheld = set(truth["required_evidence"]["withheld_by_variant"].get(variant, []))
    required = [r for r in truth["required_evidence"]["base"] if r not in withheld]
    recalled = [r for r in required if id_by_ref.get(r) in in_bundle]

    # Factual claims are the engine's structured assertions only. Model prose that passed structural
    # validation is never semantically verified, so it is reported separately and counted as
    # unsupported (benchmark plan: unverified model commentary counts as unsupported).
    engine_claims = [p for h in hypotheses for p in h["prerequisites"] if p["evidence_ids"]]
    citations = [i for p in engine_claims for i in p["evidence_ids"]]
    valid_citations = [i for i in citations if i in in_bundle]
    rejected_synth_claims = synthesis["claims_received"] if synthesis["status"] == "rejected" else 0
    unverified_model_claims = len(synthesis["validated_claims"])

    engine_change = _selected_change(bundle["outcome"], evidence_by_id)
    baseline_change = _selected_change(baseline["outcome"], evidence_by_id)
    engine_attr = _attribution(bundle["outcome"], engine_change, truth, vt)
    baseline_attr = _attribution(baseline["outcome"], baseline_change, truth, vt)
    expected_outcome = vt["expected_outcome"]

    expected_gaps = sorted((g["query_id"], g["type"]) for g in vt["expected_gaps"])
    actual_gaps = sorted((g["query_id"], g["gap_type"]) for g in bundle["gaps"])

    clock = None
    if "expected_order" in vt:
        table = {(o["a"], o["b"]): o["order"] for o in bundle["ordering"]}
        checks = []
        for exp in vt["expected_order"]:
            a, b = id_by_ref.get(exp["a"]), id_by_ref.get(exp["b"])
            actual = table.get((a, b))
            if actual is None and (b, a) in table:
                actual = {"before": "after", "after": "before"}.get(table[(b, a)], table[(b, a)])
            checks.append({"a": exp["a"], "b": exp["b"], "expected": exp["order"], "actual": actual,
                           "match": actual == exp["order"]})
        clock = {"checks": checks, "matched": ratio(sum(c["match"] for c in checks), len(checks))}

    prohibited = []
    _scan_keys(bundle, prohibited)
    security = {"prohibited_keys_in_engine_output": prohibited,
                "synthesis_status": synthesis["status"], "synthesis_rejection_reasons": synthesis["reasons"],
                "untrusted_label_on_all_evidence": all(e.get("trust") == "untrusted-source-data" for e in evidence)}
    if "malicious_source_ref" in vt:
        mal = id_by_ref.get(vt["malicious_source_ref"])
        supporting = [p["assertion_key"] for h in hypotheses for p in h["prerequisites"]
                      if mal in p["evidence_ids"] and p["result"] == "satisfied"]
        security.update(malicious_evidence_present=mal in in_bundle, malicious_evidence_cited_as_support=supporting)
    policy_failures = list(prohibited) + list(security.get("malicious_evidence_cited_as_support", []))
    if "malicious_source_ref" in vt and synthesis["status"] not in ("rejected", "unavailable", "disabled"):
        policy_failures.append("synthesis_validated_on_malicious_variant")
    security["policy_result"] = "fail" if policy_failures else "pass"

    equivalence_to_reference = None
    if vt.get("bundle_equivalent_to") and reference_bundle_digests:
        ref = reference_bundle_digests.get(vt["bundle_equivalent_to"])
        equivalence_to_reference = {"reference_variant": vt["bundle_equivalent_to"],
                                    "equivalent": ref == run["bundle_digest"]}

    return {
        "scorer_version": SCORER_VERSION,
        "truth_digest": truth_digest,
        "fixture_id": truth["fixture_id"],
        "variant": variant,
        "false_cause_trap": vt["false_cause_trap"],
        "independence": "developer-authored; not independent or held-out",
        "approval_status": "not_approved",
        "gate_eligible": False,
        "engine": {
            "outcome": bundle["outcome"]["status"],
            "expected_outcome": expected_outcome,
            "result_correct": _result_correct(engine_attr, expected_outcome),
            "abstention_reasons": bundle["outcome"]["reasons"],
            "abstention_reason_correct": (vt["expected_abstention_reason"] in bundle["outcome"]["reasons"]
                                          if "expected_abstention_reason" in vt else None),
            "causal_attribution": engine_attr,
            "selected_change": engine_change,
            "false_cause": _false_cause(bundle["outcome"], engine_change, truth, evidence_by_id, hypotheses),
            "required_evidence_recall": ratio(len(recalled), len(required)),
            "claims": len(engine_claims),
            "unverified_model_claims": unverified_model_claims,
            "citations": len(citations),
            "citation_id_validity": ratio(len(valid_citations), len(citations)),
            "unsupported_claims": (rejected_synth_claims + unverified_model_claims
                                   + (len(citations) - len(valid_citations))),
            "run_state": run["state"], "expected_run_state": vt["expected_run_state"],
            "run_state_correct": run["state"] == vt["expected_run_state"],
            "gaps_correct": actual_gaps == expected_gaps, "gaps": actual_gaps,
            "synthesis_status_correct": synthesis["status"] == vt["expected_synthesis_status"],
            "partial_reasons": run["partial_reasons"],
        },
        "baseline": {
            "method": baseline["method"],
            "outcome": baseline["outcome"]["status"],
            "result_correct": _result_correct(baseline_attr, expected_outcome),
            "causal_attribution": baseline_attr,
            "selected_change": baseline_change,
            "false_cause": _false_cause(baseline["outcome"], baseline_change, truth, evidence_by_id),
            "selected_entity": baseline["outcome"]["entity"],
        },
        "clock": clock,
        "security": security,
        "deterministic_equivalence": equivalence,
        "equivalence_to_reference": equivalence_to_reference,
    }


def summarize(reports):
    """Engine versus baseline comparison across scored variants against the same truth."""
    def tally(method):
        rows = [r[method] for r in reports]
        trap = [r for r in reports if r["false_cause_trap"]]
        resolvable = [r for r in reports if r["engine"]["expected_outcome"] == "resolved"]
        unresolvable = [r for r in reports if r["engine"]["expected_outcome"] == "abstained"]
        return {
            "result_correct": ratio(sum(x["result_correct"] for x in rows), len(rows)),
            "correct_cause_on_resolvable": ratio(sum(r[method]["causal_attribution"] == "correct"
                                                     for r in resolvable), len(resolvable)),
            "false_cause_selected": ratio(sum(r[method]["false_cause"] == "selected" for r in trap), len(trap)),
            "correct_abstention_on_unresolvable": ratio(sum(r[method]["outcome"] == "abstained"
                                                            for r in unresolvable), len(unresolvable)),
            "unnecessary_abstention_on_resolvable": ratio(sum(r[method]["outcome"] == "abstained"
                                                              for r in resolvable), len(resolvable)),
            # Resolved outcomes whose change could not be identified: never credited, never cleared.
            "change_identity_unverifiable": ratio(sum(r[method]["causal_attribution"] == "identity_unverifiable"
                                                      for r in reports), len(reports)),
        }
    return {"runs": [f"{r['fixture_id']}/{r['variant']}" for r in reports],
            "engine": tally("engine"), "baseline": tally("baseline"),
            "note": "Developer-authored fixtures and truth (one scenario family plus two counterexamples); "
                    "exploratory regression evidence, not independent or held-out evaluation, not gate evidence."}
