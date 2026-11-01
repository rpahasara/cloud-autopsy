# Phase 1 independent-review remediation (Draft)

Date: 2026-11-01. Review basis: independent review of PR #11 head `380c787`, recorded in the Codex chat “Review Cloud Autopsy PR #11” on 2026-11-01. This report records remediation, not a new independent approval.

| Review finding | Remediation | Reviewable artifact |
|---|---|---|
| P1: 36 requirements lacked owners | Assign accountable architecture, evaluation and security owning roles; authority remains separate | [SRS 0.3.0-draft](../srs.md), [36-row matrix](../requirement-matrix.md) |
| P1: Five variants confused with full gate | Initial harness qualification only; ten planned families including held-out cases, within 8–12 scope | [Corpus plan](../scenarios/corpus-plan.md) |
| P1: Traceability drift | Exact issue/requirement reverse matrices, decision reverse edges, CA-DEC-007 in gate review; explicit scenario scoring and integrity assertions | [Backlog](../traceability.md), [scenario matrix](../scenarios/CA-SCENARIO-001.md); synchronized issue #9/#10 bodies |
| P2: Unstable STRIDE trace | Six stable threat IDs; exact reverse threat/risk/requirement/planned-test mappings; explicit resource-exhaustion risk CA-RISK-011 | [STRIDE](../security/threat-model.md), [risks](../security/risk-register.md) |
| P2: Expired evidence obscures replay | Proposed 30/180-day lifecycle, seven-day authorized deletion, minimized tombstones, provenance expiry and explicit replay states | [Lifecycle contract](../evidence-lifecycle.md), [CA-DEC-005](../architecture/adr/CA-DEC-005.md) |
| P3: Formatting claim contradicted base diff | Remove extra EOF blank line in historical setup audit and rerun complete base diff check | [Setup audit](phase1-setup-audit.md), documentation validator |

CA-DEC-001 through CA-DEC-008 are substantive proposed records using the review's recommended MVP positions, with rationale, alternatives, security implications, accountable decision role, approval status and review triggers. Numeric quality targets, skew heuristics and performance/capacity budgets remain provisional pending benchmark and approval. External AI-provider access requires separate data-egress and security approval and remains disabled by default.

## Verification

Run `python tools/validate_docs.py` and `git diff --check origin/main` from the repository root. The validator checks all 36 requirements, exact issue/decision/threat/risk reverse edges, planned test IDs, five scenario variants, relative links and explicit anchors, table widths and EOF formatting. It does not execute product tests. Final PR verification records the actual results and remote issue/PR state.

## Remaining risks and approval work

Owning roles are assigned, but named product, architecture, security, evaluation and risk authorities are still pending CA-DEC-008. No corpus fixtures beyond the initial specification, implementation, benchmark or executed security evidence exists. Retention and tombstone semantics need implementation validation under separately authorized work. Hashes alone do not defend against a privileged attacker. All risks remain open; none is accepted.

Product-owner disposition is required for all eight decisions: boundary/source allowlists, PostgreSQL/provenance architecture, timestamp/skew policy, model/egress boundary, retention/deletion periods, corpus and quality gates, performance/capacity budgets, and approval authorities/independence. Architecture and security review remain separate responsibilities. No decision is accepted; no implementation or release is authorized.
