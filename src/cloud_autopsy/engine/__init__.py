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
RESULT_VERSION = "ca-investigation-result/0.1-provisional"
RESULT_DIGEST_ALGORITHM = "ca-investigation-result-sha256/0.1-provisional"
TIMELINE_RULES_VERSION = "ca-timeline-rules/0.1-provisional"
CATALOG_VERSION = "ca-mechanism-catalog/0.1-provisional"

RULE_VERSIONS = {
    "investigation-engine": ENGINE_VERSION,
    "investigation-result": RESULT_VERSION,
    "mechanism-catalog": CATALOG_VERSION,
    "timeline-rules": TIMELINE_RULES_VERSION,
}


def required_rule_versions():
    return dict(RULE_VERSIONS)
