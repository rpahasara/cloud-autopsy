# CA-DEC-005 — Evidence lifecycle and replay after expiry

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Security reviewer (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

Keep reviewed synthetic fixtures and ground truth versioned in Git. Propose 30 days for generated raw and normalized run evidence and 180 days for minimized manifests, hashes, provenance metadata, scores, approval records and security audits, measured from run completion. Purge within seven days of an authorized deletion request; earlier deletion overrides routine retention. Follow the lifecycle contract in ../../evidence-lifecycle.md. All periods are proposed and need product/security approval.

## Rationale

Bounded retention limits exposure while preserving an honest account of replay limitations.

## Alternatives

Indefinite raw retention aids replay but increases exposure; immediate deletion prevents diagnosis and repeatability.

## Security implications

Tombstones and provenance must not retain deleted payloads or sensitive identifiers. Git contains synthetic data only; accidental sensitive commits require separate history-cleanup handling.

## Review triggers

Retention approval, deletion obligation, sensitive-data discovery, storage limits or a replay/expiry failure.

## Traceability and validation

Requirements: [CA-FR-002](../../srs.md#ca-fr-002), [CA-FR-005](../../srs.md#ca-fr-005), [CA-FR-010](../../srs.md#ca-fr-010), [CA-FR-012](../../srs.md#ca-fr-012), [CA-NFR-001](../../srs.md#ca-nfr-001), [CA-NFR-004](../../srs.md#ca-nfr-004), [CA-NFR-010](../../srs.md#ca-nfr-010), [CA-SEC-007](../../srs.md#ca-sec-007), [CA-SEC-008](../../srs.md#ca-sec-008).

Backlog: [CA-001 / #1](https://github.com/rpahasara/cloud-autopsy/issues/1), [CA-002 / #2](https://github.com/rpahasara/cloud-autopsy/issues/2), [CA-003 / #3](https://github.com/rpahasara/cloud-autopsy/issues/3), [CA-004 / #4](https://github.com/rpahasara/cloud-autopsy/issues/4), [CA-005 / #5](https://github.com/rpahasara/cloud-autopsy/issues/5), [CA-006 / #6](https://github.com/rpahasara/cloud-autopsy/issues/6), [CA-007 / #7](https://github.com/rpahasara/cloud-autopsy/issues/7), [CA-008 / #8](https://github.com/rpahasara/cloud-autopsy/issues/8), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Separate short-lived payloads from minimized identity/provenance and lifecycle overlays. Freeze publication and replay availability checks must handle concurrent expiry; deletion is marked unavailable before purge and never rewrites the original manifest.

Detailed proposal: [Phase 1C data-model](../phase1c/data-model.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.
