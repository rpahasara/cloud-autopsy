# CA-DEC-003 — Timestamp provenance and skew

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Architecture lead (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

Retain raw timestamp text, parsed UTC, timestamp type, clock domain, precision, observation/ingestion times, declared offset and uncertainty. Overlapping uncertainty intervals are unordered. Propose a ±2-second ambiguity interval when precision is unknown, flag offsets over 2 seconds and treat offsets over 30 seconds as unreliable unless fixture-declared. Stable-ID order is display-only and never causal evidence. These numeric heuristics are provisional pending clock-fixture benchmarking.

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
