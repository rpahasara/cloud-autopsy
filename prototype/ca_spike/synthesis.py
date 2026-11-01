"""Synthesis boundary: disabled by default; fixture stub responses only; strict validation.

There is no model client in this spike and no network code. A stub response stands in
for an untrusted model output so the validator can be exercised. Validation rejects the
entire attempt on any structural or policy failure and never alters the ledger.

A passing attempt is only ``structurally_validated``: every claim cites a non-empty
evidence set exactly equal to its assertions' evidence, factual kinds cite satisfied
assertions and ``unresolved`` claims cite non-satisfied ones. The free text is not
checked semantically; it is kept as ``text_untrusted`` and the only fact exposed is
``supported_fact``, rendered from the deterministic ledger.

Malformed responses (non-JSON Python values, unhashable or mistyped fields, excessive
depth or size) are rejected with deterministic reason codes before any field logic runs;
the validator never raises into the investigation.
"""

from .canonical import CanonicalError, canonical_bytes, digest

CONTRACT_VERSION = "ca-synth/0.2-spike"
VALIDATOR_VERSION = "ca-synth-validator/0.3-spike"
ALLOWED_TOP = {"contract_version", "bundle_digest", "claims", "limitations"}
ALLOWED_CLAIM = {"claim_id", "kind", "text", "evidence_ids", "assertion_keys"}
ALLOWED_KINDS = {"observed", "derived", "unresolved"}
PROHIBITED_KEYS = {"action", "actions", "command", "commands", "tool", "tools", "tool_calls", "approval",
                   "approve", "approved", "execute", "exec", "url", "urls"}
MAX_CLAIMS = 50
MAX_TEXT = 2000
MAX_RESPONSE_BYTES = 65536
MAX_DEPTH = 16
MAX_NODES = 20000
MAX_LIMITATIONS = 50


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


def _shape_problems(value):
    """Iteratively check that ``value`` is a bounded strict-JSON value. Returns sorted codes."""
    problems, nodes, stack = set(), 0, [(value, 1)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            problems.add("malformed:too_many_nodes")
            break
        if depth > MAX_DEPTH:
            problems.add("malformed:depth_exceeded")
            continue
        if node is None or isinstance(node, (bool, int)):
            continue
        if isinstance(node, str):
            try:
                node.encode("utf-8")
            except UnicodeEncodeError:
                problems.add("malformed:unencodable_string")
            continue
        if type(node) is list:
            stack.extend((item, depth + 1) for item in node)
        elif type(node) is dict:
            for key, item in node.items():
                if not isinstance(key, str):
                    problems.add("malformed:non_string_key")
                stack.append((item, depth + 1))
        else:
            problems.add(f"malformed:unsupported_type:{type(node).__name__}")
    return sorted(problems)


def _str_list(value):
    """True for a JSON array whose items are all strings."""
    return type(value) is list and all(isinstance(v, str) for v in value)


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
    """Return (validated_claims, rejection_reasons, claim_count). Never raises on response content."""
    if type(response) is not dict:
        return [], ["response_not_object"], 0
    shape = _shape_problems(response)
    if shape:
        claims = response.get("claims")
        return [], shape, len(claims) if type(claims) is list else 0
    reasons = []
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
    limitations = response.get("limitations")
    if "limitations" in response and (not _str_list(limitations) or len(limitations) > MAX_LIMITATIONS
                                      or any(len(x) > MAX_TEXT for x in limitations)):
        reasons.append("invalid_limitations")

    claims = response.get("claims")
    if type(claims) is not list:
        return [], reasons + ["claims_not_list"], 0
    if len(claims) > MAX_CLAIMS:
        reasons.append("too_many_claims")
    allowed_ids = set(bundle["evidence_ids"])
    assertions = {p["assertion_key"]: p for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"]}
    facts = {p["assertion_key"]: (f"{h['mechanism']} {h['entity']['kind']}/{h['entity']['namespace']}/"
                                  f"{h['entity']['name']}: {p['key']} = {p['result']}")
             for h in bundle["ledger"]["hypotheses"] for p in h["prerequisites"]}
    validated, seen_claim_ids = [], set()
    for i, claim in enumerate(claims):
        tag = f"claim[{i}]"
        if type(claim) is not dict:
            reasons.append(f"{tag}:not_object")
            continue
        extra, missing = set(claim) - ALLOWED_CLAIM, ALLOWED_CLAIM - set(claim)
        reasons += [f"{tag}:unexpected_field:{k}" for k in sorted(extra)]
        reasons += [f"{tag}:missing_field:{k}" for k in sorted(missing)]
        # Type checks first: every later step hashes or compares these values.
        claim_id, kind, text = claim.get("claim_id"), claim.get("kind"), claim.get("text")
        ids, keys = claim.get("evidence_ids"), claim.get("assertion_keys")
        if "claim_id" in claim and (not isinstance(claim_id, str) or not claim_id):
            reasons.append(f"{tag}:invalid_claim_id")
        elif isinstance(claim_id, str):
            if claim_id in seen_claim_ids:
                reasons.append(f"{tag}:duplicate_claim_id")
            seen_claim_ids.add(claim_id)
        if "kind" in claim and not isinstance(kind, str):
            reasons.append(f"{tag}:invalid_kind")
            kind = None
        elif isinstance(kind, str) and kind not in ALLOWED_KINDS:
            reasons.append(f"{tag}:prohibited_kind")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            reasons.append(f"{tag}:invalid_text")
        if "evidence_ids" in claim and not _str_list(ids):
            reasons.append(f"{tag}:invalid_evidence_ids")
        if "assertion_keys" in claim and not _str_list(keys):
            reasons.append(f"{tag}:invalid_assertion_keys")
        ids = ids if _str_list(ids) else []
        keys = keys if _str_list(keys) else []

        if not ids:
            reasons.append(f"{tag}:empty_citation")
        if len(set(ids)) != len(ids):
            reasons.append(f"{tag}:duplicate_citation")
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
        if kind in ("observed", "derived") and any(a["result"] != "satisfied" for a in known):
            reasons.append(f"{tag}:assertion_not_satisfied")
        if kind == "unresolved" and any(a["result"] == "satisfied" for a in known):
            reasons.append(f"{tag}:unresolved_claim_on_satisfied_assertion")
        if not any(r.startswith(tag + ":") for r in reasons):
            validated.append({
                "claim_id": claim_id, "kind": kind, "evidence_ids": sorted(ids),
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
    record = {"mode": mode, "contract_version": CONTRACT_VERSION, "validator_version": VALIDATOR_VERSION,
              "input_digest": digest(contract),
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
    if type(stub) is not dict:
        record.update(status="rejected", reasons=["stub_not_object"])
        return record
    behavior = stub.get("behavior")
    if behavior in ("timeout", "unavailable"):
        record.update(status="unavailable", reasons=[behavior])
        return record
    response = stub.get("response")
    if not _shape_problems(response):
        try:
            record["response_digest"] = digest(response)
        except CanonicalError:
            record["response_digest"] = None
    try:
        validated, reasons, count = validate_response(response, bundle, bundle_digest)
    except Exception as exc:  # fail closed: a validator defect rejects the attempt, never crashes the run
        validated, reasons, count = [], [f"validator_error:{type(exc).__name__}"], 0
    record["claims_received"] = count
    if reasons:
        record.update(status="rejected", reasons=reasons)
    else:
        record.update(status="structurally_validated", validated_claims=validated)
    return record
