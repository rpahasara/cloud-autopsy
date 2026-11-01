"""Synthesis boundary: disabled by default; fixture stub responses only; strict validation.

There is no model client in this spike and no network code. A stub response stands in
for an untrusted model output so the validator can be exercised. Validation rejects the
entire attempt on any structural or policy failure and never alters the ledger.

A passing attempt is only ``structurally_validated``: every claim cites a non-empty
evidence set exactly equal to its assertions' evidence, factual kinds cite satisfied
assertions and ``unresolved`` claims cite non-satisfied ones. The free text is not
checked semantically; it is kept as ``text_untrusted`` and the only fact exposed is
``supported_fact``, rendered from the deterministic ledger.
"""

from .canonical import CanonicalError, canonical_bytes, digest

CONTRACT_VERSION = "ca-synth/0.2-spike"
ALLOWED_TOP = {"contract_version", "bundle_digest", "claims", "limitations"}
ALLOWED_CLAIM = {"claim_id", "kind", "text", "evidence_ids", "assertion_keys"}
ALLOWED_KINDS = {"observed", "derived", "unresolved"}
PROHIBITED_KEYS = {"action", "actions", "command", "commands", "tool", "tools", "tool_calls", "approval",
                   "approve", "approved", "execute", "exec", "url", "urls"}
MAX_CLAIMS = 50
MAX_TEXT = 2000
MAX_RESPONSE_BYTES = 65536


def build_input(bundle, bundle_digest):
    """Minimized synthesis input contract: identifiers, assertions and statuses only."""
    assertions = [{"assertion_key": p["assertion_key"], "result": p["result"], "evidence_ids": p["evidence_ids"]}
                  for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"]]
    return {
        "contract_version": CONTRACT_VERSION,
        "bundle_digest": bundle_digest,
        "task": "Explain the supplied ledger with citations and limitations. Do not add causes or actions.",
        "allowed_evidence_ids": bundle["evidence_ids"],
        "assertions": assertions,
        "hypotheses": [{"hypothesis_id": h["hypothesis_id"], "mechanism": h["mechanism"], "status": h["status"]}
                       for h in bundle["ledger"]["hypotheses"]],
        "gaps": [{"gap_id": g["gap_id"], "type": g["gap_type"]} for g in bundle["gaps"]],
        "outcome": bundle["outcome"]["status"],
    }


def _find_prohibited(value, path="$"):
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in PROHIBITED_KEYS:
                found.append(f"{path}.{k}")
            found += _find_prohibited(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += _find_prohibited(v, f"{path}[{i}]")
    return found


def validate_response(response, bundle, bundle_digest):
    """Return (validated_claims, rejection_reasons, claim_count)."""
    reasons = []
    if not isinstance(response, dict):
        return [], ["response_not_object"], 0
    try:
        if len(canonical_bytes(response)) > MAX_RESPONSE_BYTES:
            reasons.append("response_too_large")
    except CanonicalError as exc:
        reasons.append(f"non_canonical:{exc}")
    reasons += [f"prohibited_field:{p}" for p in _find_prohibited(response)]
    reasons += [f"unexpected_field:{k}" for k in sorted(set(response) - ALLOWED_TOP)]
    reasons += [f"missing_field:{k}" for k in sorted(ALLOWED_TOP - set(response))]
    if response.get("contract_version") != CONTRACT_VERSION:
        reasons.append("contract_version_mismatch")
    if "bundle_digest" in response and response["bundle_digest"] != bundle_digest:
        reasons.append("bundle_digest_mismatch")

    claims = response.get("claims")
    if not isinstance(claims, list):
        return [], reasons + ["claims_not_list"], 0
    if len(claims) > MAX_CLAIMS:
        reasons.append("too_many_claims")
    allowed_ids = set(bundle["evidence_ids"])
    assertions = {p["assertion_key"]: p for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"]}
    facts = {p["assertion_key"]: (f"{h['mechanism']} {h['entity']['kind']}/{h['entity']['namespace']}/"
                                  f"{h['entity']['name']}: {p['key']} = {p['result']}")
             for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"]}
    validated = []
    for i, claim in enumerate(claims):
        tag = f"claim[{i}]"
        if not isinstance(claim, dict):
            reasons.append(f"{tag}:not_object")
            continue
        extra, missing = set(claim) - ALLOWED_CLAIM, ALLOWED_CLAIM - set(claim)
        reasons += [f"{tag}:unexpected_field:{k}" for k in sorted(extra)]
        reasons += [f"{tag}:missing_field:{k}" for k in sorted(missing)]
        if claim.get("kind") not in ALLOWED_KINDS:
            reasons.append(f"{tag}:prohibited_kind")
        text = claim.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            reasons.append(f"{tag}:invalid_text")
        ids = claim.get("evidence_ids") if isinstance(claim.get("evidence_ids"), list) else []
        keys = claim.get("assertion_keys") if isinstance(claim.get("assertion_keys"), list) else []
        if not ids:
            reasons.append(f"{tag}:empty_citation")
        bad_ids = [x for x in ids if x not in allowed_ids]
        if bad_ids:
            reasons.append(f"{tag}:citation_not_in_bundle:{len(bad_ids)}")
        if not keys:
            reasons.append(f"{tag}:no_assertion_key")
        known = [assertions[k] for k in keys if k in assertions]
        if len(known) != len(keys):
            reasons.append(f"{tag}:unknown_assertion_key")
        if known and ids:
            supported_ids = set().union(*(set(a["evidence_ids"]) for a in known))
            if not set(ids) <= supported_ids:
                reasons.append(f"{tag}:citation_not_in_assertion")
            elif set(ids) != supported_ids:
                reasons.append(f"{tag}:citation_set_differs_from_assertion")
        kind = claim.get("kind")
        if kind in ("observed", "derived") and any(a["result"] != "satisfied" for a in known):
            reasons.append(f"{tag}:assertion_not_satisfied")
        if kind == "unresolved" and any(a["result"] == "satisfied" for a in known):
            reasons.append(f"{tag}:unresolved_claim_on_satisfied_assertion")
        if not any(r.startswith(tag) for r in reasons):
            validated.append({
                "claim_id": claim["claim_id"], "kind": kind, "evidence_ids": sorted(ids),
                "assertion_keys": sorted(keys),
                # The only fact this attempt may present is rendered from the deterministic ledger.
                "supported_fact": "; ".join(sorted(facts[k] for k in keys)),
                "semantic_status": "unverified_model_text",
                "text_untrusted": text})
    if reasons:
        return [], reasons, len(claims)
    return validated, [], len(claims)


def run_synthesis(mode, stub, bundle, bundle_digest):
    """Return a synthesis attempt record. Never mutates the bundle or ledger."""
    contract = build_input(bundle, bundle_digest)
    record = {"mode": mode, "contract_version": CONTRACT_VERSION, "input_digest": digest(contract),
              "status": "disabled", "reasons": [], "response_digest": None, "claims_received": 0,
              "validated_claims": [],
              # Structural checks only: schema, citation membership, typed assertion status. Model
              # prose is never semantically verified and is never a supported finding.
              "semantic_validation": "not_performed"}
    if mode == "disabled":
        return record
    if mode != "stub":
        record.update(status="rejected", reasons=["mode_not_permitted"])
        return record
    behavior = (stub or {}).get("behavior")
    if behavior in ("timeout", "unavailable"):
        record.update(status="unavailable", reasons=[behavior])
        return record
    response = (stub or {}).get("response")
    try:
        record["response_digest"] = digest(response)
    except CanonicalError:
        record["response_digest"] = None
    validated, reasons, count = validate_response(response, bundle, bundle_digest)
    record["claims_received"] = count
    if reasons:
        record.update(status="rejected", reasons=reasons)
    else:
        record.update(status="structurally_validated", validated_claims=validated)
    return record
