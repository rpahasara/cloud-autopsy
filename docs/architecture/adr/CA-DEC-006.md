# CA-DEC-006 — Evaluation and security gates

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Evaluation engineer (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

Five CA-SCENARIO-001 variants qualify the initial investigation harness only. The full gate needs a planned 8–12-scenario corpus with held-out cases. Provisional review targets: 100% valid in-bundle citation IDs; at least 90% supported factual claims overall and 80% per scenario; zero unsupported confirmed causal claims; zero false-cause selections; 100% correct abstention on designated gap cases; 100% deterministic equivalence; zero mutation/tool-policy bypasses or secret-canary propagation; no unresolved Critical/High security finding. Supersede the historical 70% hypothesis only after benchmark review and explicit approval.

## Rationale

Separate citation existence from factual support and prevent one easy scenario from masking failures.

## Alternatives

The historical 70% aggregate alone permits severe errors; a single blended score can hide safety failures.

## Security implications

Security failures cannot be averaged away. The zero-bypass and no-secret requirements remain proposed security constraints; measured quality targets do not constitute signoff.

## Review triggers

Corpus/scorer/ground-truth change, first benchmark, failed security case or threshold proposal.

## Traceability and validation

Requirements: [CA-FR-006](../../srs.md#ca-fr-006), [CA-FR-008](../../srs.md#ca-fr-008), [CA-FR-009](../../srs.md#ca-fr-009), [CA-FR-011](../../srs.md#ca-fr-011), [CA-NFR-001](../../srs.md#ca-nfr-001), [CA-NFR-007](../../srs.md#ca-nfr-007), [CA-SEC-004](../../srs.md#ca-sec-004), [CA-SEC-010](../../srs.md#ca-sec-010), [CA-SEC-012](../../srs.md#ca-sec-012).

Backlog: [CA-002 / #2](https://github.com/rpahasara/cloud-autopsy/issues/2), [CA-005 / #5](https://github.com/rpahasara/cloud-autopsy/issues/5), [CA-006 / #6](https://github.com/rpahasara/cloud-autopsy/issues/6), [CA-007 / #7](https://github.com/rpahasara/cloud-autopsy/issues/7), [CA-008 / #8](https://github.com/rpahasara/cloud-autopsy/issues/8), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Require independent frozen truth/scorer, full-corpus versus initial-harness separation and versioned denominators. Numeric quality targets remain provisional until benchmarked and explicitly approved; documentation is not gate evidence.

Detailed proposal: [Phase 1C signoff](../phase1c/signoff.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.

## Phase 1D approval request — 2026-11-01

- **Product-owner disposition requested:** Confirm separate design and empirical gates, initial harness versus full corpus, independent frozen truth/scorer and explicit denominators; unresolved Critical/High findings block the current proposed gate.
- **Provisional assumptions excluded from acceptance:** All quality metrics/targets, historical 70% versus proposed stricter values and exact corpus/aggregation choices remain provisional until benchmarked and explicitly approved before gate scoring.
- **Specialist reviewers required:** Independent evaluation/gate and security reviewers.
- **Accepted terms:** None; no approval recorded.
- **Current disposition:** Proposed; awaiting named product and specialist review.
- **Approval record fields:** reviewed commit/digest, scoped accept/revise/defer/reject disposition, excluded assumptions, named authorities/reviewers and dates, independence/conflicts, evidence links, residual-risk disposition and review triggers. All fields remain unrecorded.

See the [complete approval matrix](../../reviews/phase1d/approvals.md), [consistency review](../../reviews/phase1d/consistency-review.md) and [formal completion checklist](../../reviews/phase1d/completion-checklist.md). A partial or deferred disposition is recorded separately and does not mark this entire ADR Accepted. No implementation or external access is authorized.
