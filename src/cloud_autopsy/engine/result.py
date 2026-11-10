"""Investigation result ``ca-investigation-result/0.2-provisional`` and its verification.

The result is one canonical JSON document. It records what it was derived from (plan, registry,
manifest digest and status, the frozen clock declaration and its digest, rule versions), the
timeline, every
hypothesis with its prerequisites, citations, orderings, contradictions and limiting gaps, every
manifest gap with the mechanisms it affects, and an outcome that is either ``resolved`` (exactly
one supported hypothesis and no unresolved competitor) or ``abstained`` with machine-readable
reasons and gap IDs and no substitute cause. Synthesis is reported unavailable: the plan's
synthesis mode is ``disabled``, and the deterministic result never depends on a model.

``result_digest`` covers every other field. Run and investigation IDs, wall-clock times and
database row order are excluded, so the same sealed input always gives the same bytes, whichever
run, delivery order or retry produced it.

``verify_result`` re-checks a result against its input without trusting it: digest, exact
citations (every evidence ID cited is a sealed member, every gap ID a sealed gap), outcome
consistency, and byte-identical replay.
"""

import hashlib

from ..contracts import canonical
from . import ENGINE_VERSION, RESULT_DIGEST_ALGORITHM, RESULT_VERSION, mechanisms, timeline
from .inputs import InputError

EXCLUDED_FROM_DIGEST = ("run_id", "investigation_id", "wall-clock and stage timings", "database row order",
                        "batch delivery order, duplicates and attempts")


def _gap_view(gap, hypotheses):
    affects = sorted(h["hypothesis_id"] for h in hypotheses if gap["gap_id"] in h["limiting_gap_ids"])
    return {"gap_id": gap["gap_id"], "subject": gap["subject"], "gap_type": gap["gap_type"],
            "reasons": list(gap["reasons"]), "source_id": gap["source_id"], "query_id": gap["query_id"],
            "mandatory": gap["mandatory"], "evidence_id": gap["evidence_id"], "interval_ms": gap["interval_ms"],
            "affects_hypothesis_ids": affects}


def build(inp):
    """Return ``(result_dict, result_bytes)`` for a verified ``InvestigationInput``."""
    hypotheses, outcome = mechanisms.evaluate(inp)
    plan = inp.plan
    body = {
        "contract_version": RESULT_VERSION,
        "result_algorithm": RESULT_DIGEST_ALGORITHM,
        "engine_version": ENGINE_VERSION,
        "rule_versions": dict(plan.rule_versions),
        "mechanism_catalog": mechanisms.CATALOG,
        "inputs": {
            "plan_id": plan.plan_id, "plan_digest": plan.digest,
            "registry_id": inp.registry.registry_id, "registry_digest": inp.registry.digest,
            "manifest_digest": inp.manifest_digest, "manifest_status": inp.manifest_status,
            "manifest_limitations": list(inp.manifest_limitations),
            "window": {"start": plan.window_start, "end": plan.window_end},
            "clock_domains": list(inp.clock_domain_records),
            "clock_declaration_digest": inp.clock_declaration.digest,
            "evidence_count": len(inp.members),
            "unverified_evidence_ids": sorted(m.evidence.evidence_id for m in inp.members
                                              if m.coverage != "verified"),
        },
        "timeline": timeline.build(inp),
        "hypotheses": hypotheses,
        "gaps": [_gap_view(g, hypotheses) for g in inp.gaps],
        "outcome": outcome,
        "synthesis": {"mode": plan.synthesis_mode, "status": "unavailable", "reason": "synthesis_disabled"},
        "excluded_from_digest": list(EXCLUDED_FROM_DIGEST),
    }
    digest = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
    result = {**body, "result_digest": digest}
    return result, canonical.canonical_bytes(result)


def investigate(inp):
    return build(inp)[1]


def _fail(code, message):
    raise InputError(code, message)


def _is_str(value, nullable=False):
    return isinstance(value, str) or (nullable and value is None)


def _str_list(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _dict_with(value, keys):
    return isinstance(value, dict) and all(k in value for k in keys)


def check_shape(result):
    """Refuse a document whose structure verification relies on is wrong (``result_malformed``).

    This runs before any other check, so a corrupt or deliberately reshaped document (for
    example ``"rule_versions": []``) fails closed with one stable code instead of an arbitrary
    TypeError deep inside verification. It checks types only; content is checked afterwards.
    """
    ok = (_dict_with(result, ("result_digest", "contract_version", "engine_version", "rule_versions", "inputs",
                              "hypotheses", "outcome"))
          and _is_str(result["result_digest"]) and _is_str(result["contract_version"])
          and _is_str(result["engine_version"])
          and isinstance(result["rule_versions"], dict) and all(_is_str(v) for v in result["rule_versions"].values())
          and _dict_with(result["inputs"], ("plan_digest", "manifest_digest", "clock_declaration_digest"))
          and all(_is_str(result["inputs"][k]) for k in ("plan_digest", "manifest_digest", "clock_declaration_digest"))
          and _dict_with(result["outcome"], ("status", "hypothesis_id", "mechanism", "evidence_ids", "reasons",
                                             "gap_ids"))
          and _is_str(result["outcome"]["status"]) and _is_str(result["outcome"]["hypothesis_id"], True)
          and _is_str(result["outcome"]["mechanism"], True)
          and all(_str_list(result["outcome"][k]) for k in ("evidence_ids", "reasons", "gap_ids"))
          and isinstance(result["hypotheses"], list))
    for h in result["hypotheses"] if ok else ():
        ok = (_dict_with(h, ("hypothesis_id", "status", "prerequisites", "contradictions", "limiting_gap_ids"))
              and _is_str(h["hypothesis_id"]) and _is_str(h["status"]) and _str_list(h["limiting_gap_ids"])
              and isinstance(h["prerequisites"], list) and isinstance(h["contradictions"], list)
              and all(_dict_with(p, ("result", "evidence_ids", "orderings", "gap_ids")) and _is_str(p["result"])
                      and _str_list(p["evidence_ids"]) and _str_list(p["gap_ids"])
                      and isinstance(p["orderings"], list)
                      and all(_dict_with(o, ("a", "b")) and _is_str(o["a"]) and _is_str(o["b"])
                              for o in p["orderings"])
                      for p in h["prerequisites"])
              and all(_dict_with(c, ("evidence_ids",)) and _str_list(c["evidence_ids"]) for c in h["contradictions"]))
        if not ok:
            break
    if not ok:
        _fail("result_malformed", "result document does not have the expected structure")


def verify_result(result_bytes, inp):
    """Verify a stored or received result against its input; return the decoded result."""
    result = canonical.loads(bytes(result_bytes))
    check_shape(result)
    body = {k: v for k, v in result.items() if k != "result_digest"}
    expected = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
    if result.get("result_digest") != expected:
        _fail("result_digest_mismatch", "result digest does not match its content")
    members = {m.evidence.evidence_id for m in inp.members}
    gap_ids = {g["gap_id"] for g in inp.gaps}
    hypothesis_ids = {h["hypothesis_id"] for h in result["hypotheses"]}
    for hypothesis in result["hypotheses"]:
        cited = [e for p in hypothesis["prerequisites"] for e in p["evidence_ids"]]
        cited += [e for c in hypothesis["contradictions"] for e in c["evidence_ids"]]
        cited += [e for p in hypothesis["prerequisites"] for o in p["orderings"] for e in (o["a"], o["b"])]
        if not set(cited) <= members:
            _fail("citation_invalid", "a hypothesis cites evidence outside the sealed manifest")
        gaps = list(hypothesis["limiting_gap_ids"]) + [g for p in hypothesis["prerequisites"] for g in p["gap_ids"]]
        if not set(gaps) <= gap_ids:
            _fail("citation_invalid", "a hypothesis cites a gap outside the sealed manifest")
        if hypothesis["status"] == mechanisms.SUPPORTED and any(
                p["result"] != mechanisms.SATISFIED or not p["evidence_ids"] for p in hypothesis["prerequisites"]):
            _fail("support_invalid", "a supported hypothesis has a prerequisite without satisfied, cited evidence")
    outcome = result["outcome"]
    if outcome["status"] == "resolved":
        chosen = [h for h in result["hypotheses"] if h["hypothesis_id"] == outcome["hypothesis_id"]]
        if len(chosen) != 1 or chosen[0]["status"] != mechanisms.SUPPORTED or not set(outcome["evidence_ids"]) <= members:
            _fail("outcome_invalid", "a resolved outcome must name one supported hypothesis with sealed citations")
    elif outcome["status"] == "abstained":
        if outcome["hypothesis_id"] is not None or outcome["mechanism"] is not None or not outcome["reasons"]:
            _fail("outcome_invalid", "an abstention carries reasons and no substitute cause")
        if not set(outcome["gap_ids"]) <= gap_ids or not set(outcome["gap_ids"]) <= {
                g for h in result["hypotheses"] if h["hypothesis_id"] in hypothesis_ids for g in h["limiting_gap_ids"]}:
            _fail("citation_invalid", "an abstention cites a gap outside the sealed manifest or ledger")
    else:
        _fail("outcome_invalid", "outcome status must be resolved or abstained")
    if investigate(inp) != canonical.canonical_bytes(result):
        _fail("replay_mismatch", "re-running the engine on the same input does not reproduce these bytes")
    return result
