# CA-DEC-007 — Performance and capacity budgets

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Evaluation engineer (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

Benchmark a documented 4-vCPU/8-GiB reference environment with one concurrent investigation. Provisional workload: 45-minute window, 10,000 evidence records, 50 MB input. Provisional targets: deterministic ingestion/assembly p95 ≤60 seconds and total excluding synthesis ≤90 seconds. Proposed hard bounds: 60-minute window, 100,000 records, 250 MB payload and bounded retries with explicit truncation/rejection. Model latency is separate and must not block deterministic output. Numeric targets and bounds require benchmark validation and approval before becoming gate budgets.

## Rationale

Measure a reproducible workload before making performance promises.

## Alternatives

Unbounded acquisition is unsafe; premature production SLAs misrepresent an unbenchmarked prototype. Smaller bounds may be needed after measurement.

## Security implications

Test byte/record/time/retry boundaries and fail closed on resource limits; record incomplete evidence rather than claiming a complete result.

## Review triggers

First benchmark, reference hardware/concurrency change, p95 regression or any bound exhaustion.

## Traceability and validation

Requirements: [CA-NFR-003](../../srs.md#ca-nfr-003), [CA-NFR-006](../../srs.md#ca-nfr-006), [CA-NFR-008](../../srs.md#ca-nfr-008), [CA-NFR-009](../../srs.md#ca-nfr-009), [CA-SEC-009](../../srs.md#ca-sec-009).

Backlog: [CA-004 / #4](https://github.com/rpahasara/cloud-autopsy/issues/4), [CA-007 / #7](https://github.com/rpahasara/cloud-autopsy/issues/7), [CA-008 / #8](https://github.com/rpahasara/cloud-autopsy/issues/8), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Apply finite per-stage input, retry, response and concurrency limits with backpressure. Idempotent accepted operations persist request/outcome digests; benchmark method, retry/key horizon and numeric budgets remain open.

Detailed proposal: [Phase 1C api](../phase1c/api.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.

## Phase 1D approval request — 2026-11-01

- **Product-owner disposition requested:** Confirm bounded single-investigation measurement, separate stage timing and model-latency isolation with explicit truncation/rejection.
- **Provisional assumptions excluded from acceptance:** Reference hardware, workload, sample plan, p95 targets, numeric bounds, retry deadline and idempotency horizon remain provisional; finite approved execution settings are prerequisites.
- **Specialist reviewers required:** Performance/evaluation, architecture and security reviewers.
- **Accepted terms:** None; no approval recorded.
- **Current disposition:** Proposed; awaiting named product and specialist review.
- **Approval record fields:** reviewed commit/digest, scoped accept/revise/defer/reject disposition, excluded assumptions, named authorities/reviewers and dates, independence/conflicts, evidence links, residual-risk disposition and review triggers. All fields remain unrecorded.

See the [complete approval matrix](../../reviews/phase1d/approvals.md), [consistency review](../../reviews/phase1d/consistency-review.md) and [formal completion checklist](../../reviews/phase1d/completion-checklist.md). A partial or deferred disposition is recorded separately and does not mark this entire ADR Accepted. No implementation or external access is authorized.
