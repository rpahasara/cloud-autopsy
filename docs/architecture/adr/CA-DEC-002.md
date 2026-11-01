# CA-DEC-002 — Evidence store and provenance

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Architecture lead (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

PostgreSQL relational tables for evidence identities, provenance edges, gaps, runs, hypotheses and citations; JSONB for source-specific payloads only. Append-only logical evidence, content hashes, strict foreign keys, schema versions and transactionally created manifests. No graph database or object store in MVP.

## Rationale

Relational integrity supports inspectable provenance with a small operational footprint.

## Alternatives

SQLite simplifies local operation but changes concurrency/integrity assumptions; graph databases add operational complexity before graph access patterns are measured.

## Security implications

Hashes detect changes against a trusted manifest; they are not signatures or protection against a privileged database attacker. Restrict credentials and preserve raw/derived separation.

## Review triggers

Measured query or capacity limits, new storage boundary, schema migration or stronger tamper-evidence needs.

## Traceability and validation

Requirements: [CA-FR-002](../../srs.md#ca-fr-002), [CA-FR-004](../../srs.md#ca-fr-004), [CA-NFR-005](../../srs.md#ca-nfr-005), [CA-NFR-010](../../srs.md#ca-nfr-010), [CA-SEC-007](../../srs.md#ca-sec-007).

Backlog: [CA-002 / #2](https://github.com/rpahasara/cloud-autopsy/issues/2), [CA-003 / #3](https://github.com/rpahasara/cloud-autopsy/issues/3), [CA-005 / #5](https://github.com/rpahasara/cloud-autopsy/issues/5), [CA-007 / #7](https://github.com/rpahasara/cloud-autopsy/issues/7), [CA-008 / #8](https://github.com/rpahasara/cloud-autopsy/issues/8), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Specify relational identities, same-run composite foreign keys, payload/metadata separation, canonical-byte digests, immutable manifests and bounded snapshot sealing. Logical schema is review material, not a migration.

Detailed proposal: [Phase 1C data-model](../phase1c/data-model.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.
