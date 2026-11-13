"""Deterministic investigation engine (CA-P2-005a slice). All versions are provisional.

Pure functions over a verified sealed input: no I/O, no database driver, no model calls and
no access to evaluation data. The flow is:

  verified frozen input + its evidence records + declared clock domains
    -> timeline (interval ordering that never invents chronology)
    -> hypothesis ledger over a small explicit mechanism catalog
    -> versioned investigation result with exact citations, gaps, contradictions or abstention

The run plan pins the rule versions below (``plan.rule_versions``), so a result can always be
traced to the exact rules that produced it, and a plan that pins other versions is refused.
"""

ENGINE_VERSION = "ca-engine/0.1-provisional"
# 0.2 (CA-P2-006a): ``inputs.clock_declaration_digest`` binds the result to the run's frozen
# clock-domain declaration. A 0.1 result never carried it; 0.1 is not produced or accepted.
RESULT_VERSION = "ca-investigation-result/0.2-provisional"
RESULT_DIGEST_ALGORITHM = "ca-investigation-result-sha256/0.2-provisional"
CLOCK_DECLARATION_VERSION = "ca-clock-declaration/0.1-provisional"
CLOCK_DECLARATION_ALGORITHM = "ca-clock-declaration-sha256/0.1-provisional"
TIMELINE_RULES_VERSION = "ca-timeline-rules/0.1-provisional"
CATALOG_VERSION = "ca-mechanism-catalog/0.1-provisional"

# CA-P2-005b: timeline rules 0.2 choose a record's ``observed`` stamp for causal ordering when it has
# one (no fallback to ``event``), and its ``event`` stamp otherwise. 0.1 always uses ``event``.
TIMELINE_RULES_VERSION_V2 = "ca-timeline-rules/0.2-provisional"

RULE_VERSIONS = {
    "clock-declaration": CLOCK_DECLARATION_VERSION,
    "investigation-engine": ENGINE_VERSION,
    "investigation-result": RESULT_VERSION,
    "mechanism-catalog": CATALOG_VERSION,
    "timeline-rules": TIMELINE_RULES_VERSION,
}
# Rule profiles: a plan pins exactly one. Profile 1 is every existing plan and stays the default, so
# existing plans, results and digests are byte-identical. Profile 2 differs in timeline rules alone and
# is accepted only with contract profile 3 (observation kinds 0.3, the only records with ``observed``).
RULE_PROFILES = (
    RULE_VERSIONS,
    {**RULE_VERSIONS, "timeline-rules": TIMELINE_RULES_VERSION_V2},
)


def required_rule_versions(profile=1):
    """The rule versions a plan pins for ``profile`` (1, the default, or 2)."""
    if profile not in (1, 2):
        raise ValueError("unknown rule profile")
    return dict(RULE_PROFILES[profile - 1])


def rule_profile(rule_versions):
    """1 or 2 when ``rule_versions`` is exactly one profile, else None."""
    for n, profile in enumerate(RULE_PROFILES, 1):
        if dict(rule_versions) == profile:
            return n
    return None
