# CA-DEC-004 — Model boundary, provider and data egress

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Security reviewer (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

Qualify the baseline with synthesis disabled or a local model. External AI-provider access stays disabled and requires separate data-egress and security approval naming provider, region/route, outbound allowlist, fields, redaction, no-training and zero-retention terms. Send only structured minimized fields, strip credentials, secret-like values, raw headers, personal identifiers and unrelated log fields; use stable aliases for correlation.

## Rationale

The deterministic baseline can be evaluated without exporting telemetry.

## Alternatives

Always-on external synthesis introduces privacy and provider dependencies; local synthesis reduces egress but still requires input/output validation and dependency review.

## Security implications

No provider is selected or authorized here. Product or architecture approval alone cannot enable external access. Test blocked egress and canary exclusion before any future enablement.

## Review triggers

Provider/model, terms, region, route, redaction or data-classification change; any external enablement request.

## Traceability and validation

Requirements: [CA-FR-007](../../srs.md#ca-fr-007), [CA-FR-008](../../srs.md#ca-fr-008), [CA-FR-013](../../srs.md#ca-fr-013), [CA-NFR-004](../../srs.md#ca-nfr-004), [CA-SEC-003](../../srs.md#ca-sec-003), [CA-SEC-004](../../srs.md#ca-sec-004), [CA-SEC-005](../../srs.md#ca-sec-005), [CA-SEC-006](../../srs.md#ca-sec-006), [CA-SEC-010](../../srs.md#ca-sec-010).

Backlog: [CA-004 / #4](https://github.com/rpahasara/cloud-autopsy/issues/4), [CA-007 / #7](https://github.com/rpahasara/cloud-autopsy/issues/7), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Specify separate no-tool model sandbox, data-only contracts, deterministic fact templates, route broker and rechecked approval context. External routes and provider credentials remain disabled/unselected.

Detailed proposal: [Phase 1C ai](../phase1c/ai.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.

## Phase 1D approval request — 2026-11-01

- **Product-owner disposition requested:** Confirm disabled-by-default synthesis and separately sandboxed local-only evaluation without tools, authority or cluster/DB access; do not enable external providers.
- **Provisional assumptions excluded from acceptance:** Local model artifact/weights/license and limits remain unselected. Any external provider/region/route/terms/field/retention enablement requires a separate data-egress and security approval.
- **Specialist reviewers required:** Security/privacy and licensing reviewers; separate egress authority only if later requested.
- **Accepted terms:** None; no approval recorded.
- **Current disposition:** Proposed; awaiting named product and specialist review.
- **Approval record fields:** reviewed commit/digest, scoped accept/revise/defer/reject disposition, excluded assumptions, named authorities/reviewers and dates, independence/conflicts, evidence links, residual-risk disposition and review triggers. All fields remain unrecorded.

See the [complete approval matrix](../../reviews/phase1d/approvals.md), [consistency review](../../reviews/phase1d/consistency-review.md) and [formal completion checklist](../../reviews/phase1d/completion-checklist.md). A partial or deferred disposition is recorded separately and does not mark this entire ADR Accepted. No implementation or external access is authorized.
