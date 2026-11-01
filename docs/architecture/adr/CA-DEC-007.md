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
