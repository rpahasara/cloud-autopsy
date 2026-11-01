# CA-DEC-003 — Timestamp provenance and skew

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Architecture lead (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

Retain raw timestamp text, parsed UTC, timestamp type, clock domain, precision, observation/ingestion times, declared offset and uncertainty. Overlapping uncertainty intervals are unordered. Unknown or unbounded clock uncertainty remains unordered. A ±2-second interval may be used only as a declared synthetic fixture assumption, never as a bound inferred from unknown precision. The 2-second offset flag and 30-second reliability flag are provisional diagnostics requiring fixture/measurement justification. Stable-ID order is display-only and never causal evidence. These numeric heuristics are provisional pending clock-fixture benchmarking.

## Rationale

Explicit uncertainty avoids turning temporal correlation into causal certainty.

## Alternatives

One normalized timestamp loses provenance; automatic clock correction hides assumptions. A fully unordered fallback remains available when clock information is absent.

## Security implications

Untrusted source clocks cannot override ingestion provenance; unknown skew remains visible.

## Review triggers

Clock-fixture benchmark, new clock domain, precision change or false ordering result.

## Traceability and validation

Requirements: [CA-FR-003](../../srs.md#ca-fr-003), [CA-FR-004](../../srs.md#ca-fr-004), [CA-NFR-002](../../srs.md#ca-nfr-002).

Backlog: [CA-003 / #3](https://github.com/rpahasara/cloud-autopsy/issues/3), [CA-005 / #5](https://github.com/rpahasara/cloud-autopsy/issues/5), [CA-006 / #6](https://github.com/rpahasara/cloud-autopsy/issues/6), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Define offset sign and interval comparison. Unknown clock bounds stay unordered; the provisional numeric heuristics cannot certify bounded uncertainty. Resource versions and display ties never establish cross-source causality.

Detailed proposal: [Phase 1C engine](../phase1c/engine.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.

## Phase 1D approval request — 2026-11-01

- **Product-owner disposition requested:** Confirm preserved original time/clock provenance, interval comparison and unordered unknown/overlapping clocks; no causal inference from display ordering.
- **Provisional assumptions excluded from acceptance:** ±2/2/30-second values remain provisional synthetic/diagnostic assumptions, not bounds on unknown clocks or approved scoring thresholds.
- **Specialist reviewers required:** Distributed-systems/architecture and independent evaluation reviewers.
- **Accepted terms:** None; no approval recorded.
- **Current disposition:** Proposed; awaiting named product and specialist review.
- **Approval record fields:** reviewed commit/digest, scoped accept/revise/defer/reject disposition, excluded assumptions, named authorities/reviewers and dates, independence/conflicts, evidence links, residual-risk disposition and review triggers. All fields remain unrecorded.

See the [complete approval matrix](../../reviews/phase1d/approvals.md), [consistency review](../../reviews/phase1d/consistency-review.md) and [formal completion checklist](../../reviews/phase1d/completion-checklist.md). A partial or deferred disposition is recorded separately and does not mark this entire ADR Accepted. No implementation or external access is authorized.
