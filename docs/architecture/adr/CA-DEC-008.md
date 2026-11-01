# CA-DEC-008 — Accountability and approval authorities

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Product / requirements authority (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

Assign accountable owning roles to all requirements. Name Product/Requirements Authority, Security Reviewer, Architecture Approver, Evaluation/Gate Reviewer and Risk Acceptance Authority before baseline approval. The scenario author cannot solely approve their ground truth or scorer. Product and architecture roles may be combined for a small team; High-risk acceptance and security approval require a second independent person. Repository maintainership grants no approval authority.

## Rationale

Ownership drives evidence and change impact; approval needs explicit authority and independent challenge.

## Alternatives

Maintainer-as-universal-approver conflates access with authority; a larger review board may be unnecessary for MVP.

## Security implications

Role ownership does not confer risk acceptance. Named incumbents, independence and approval records are still missing.

## Review triggers

Staffing/authority change, baseline request, High-risk acceptance, conflict of interest or repository transfer.

## Traceability and validation

Requirements: [CA-FR-001](../../srs.md#ca-fr-001), [CA-FR-002](../../srs.md#ca-fr-002), [CA-FR-003](../../srs.md#ca-fr-003), [CA-FR-004](../../srs.md#ca-fr-004), [CA-FR-005](../../srs.md#ca-fr-005), [CA-FR-006](../../srs.md#ca-fr-006), [CA-FR-007](../../srs.md#ca-fr-007), [CA-FR-008](../../srs.md#ca-fr-008), [CA-FR-009](../../srs.md#ca-fr-009), [CA-FR-010](../../srs.md#ca-fr-010), [CA-FR-011](../../srs.md#ca-fr-011), [CA-FR-012](../../srs.md#ca-fr-012), [CA-FR-013](../../srs.md#ca-fr-013), [CA-FR-014](../../srs.md#ca-fr-014), [CA-NFR-001](../../srs.md#ca-nfr-001), [CA-NFR-002](../../srs.md#ca-nfr-002), [CA-NFR-003](../../srs.md#ca-nfr-003), [CA-NFR-004](../../srs.md#ca-nfr-004), [CA-NFR-005](../../srs.md#ca-nfr-005), [CA-NFR-006](../../srs.md#ca-nfr-006), [CA-NFR-007](../../srs.md#ca-nfr-007), [CA-NFR-008](../../srs.md#ca-nfr-008), [CA-NFR-009](../../srs.md#ca-nfr-009), [CA-NFR-010](../../srs.md#ca-nfr-010), [CA-SEC-001](../../srs.md#ca-sec-001), [CA-SEC-002](../../srs.md#ca-sec-002), [CA-SEC-003](../../srs.md#ca-sec-003), [CA-SEC-004](../../srs.md#ca-sec-004), [CA-SEC-005](../../srs.md#ca-sec-005), [CA-SEC-006](../../srs.md#ca-sec-006), [CA-SEC-007](../../srs.md#ca-sec-007), [CA-SEC-008](../../srs.md#ca-sec-008), [CA-SEC-009](../../srs.md#ca-sec-009), [CA-SEC-010](../../srs.md#ca-sec-010), [CA-SEC-011](../../srs.md#ca-sec-011), [CA-SEC-012](../../srs.md#ca-sec-012).

Backlog: [CA-001 / #1](https://github.com/rpahasara/cloud-autopsy/issues/1), [CA-002 / #2](https://github.com/rpahasara/cloud-autopsy/issues/2), [CA-003 / #3](https://github.com/rpahasara/cloud-autopsy/issues/3), [CA-004 / #4](https://github.com/rpahasara/cloud-autopsy/issues/4), [CA-005 / #5](https://github.com/rpahasara/cloud-autopsy/issues/5), [CA-006 / #6](https://github.com/rpahasara/cloud-autopsy/issues/6), [CA-007 / #7](https://github.com/rpahasara/cloud-autopsy/issues/7), [CA-008 / #8](https://github.com/rpahasara/cloud-autopsy/issues/8), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Distinguish component runtime scopes from human approval authority. No API or model output can create approval; local credential lifecycle and named independent approvers remain unresolved. Architecture completion is not implementation authorization.

Detailed proposal: [Phase 1C signoff](../phase1c/signoff.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.

## Phase 1D approval request — 2026-11-01

- **Product-owner disposition requested:** Name product, architecture, security, independent evaluation and risk authorities; confirm separation of approval, verification and repository access, and distinct Phase 2 authorization.
- **Provisional assumptions excluded from acceptance:** Individual reviewers/conflicts, API credential storage/rotation, approved retry/key horizon and exact delegated authority remain pending.
- **Specialist reviewers required:** Product owner plus qualified independent architecture, security, evaluation, database/privacy and licensing specialists as scoped.
- **Accepted terms:** None; no approval recorded.
- **Current disposition:** Proposed; awaiting named product and specialist review.
- **Approval record fields:** reviewed commit/digest, scoped accept/revise/defer/reject disposition, excluded assumptions, named authorities/reviewers and dates, independence/conflicts, evidence links, residual-risk disposition and review triggers. All fields remain unrecorded.

See the [complete approval matrix](../../reviews/phase1d/approvals.md), [consistency review](../../reviews/phase1d/consistency-review.md) and [formal completion checklist](../../reviews/phase1d/completion-checklist.md). A partial or deferred disposition is recorded separately and does not mark this entire ADR Accepted. No implementation or external access is authorized.
