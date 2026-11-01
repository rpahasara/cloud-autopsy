# Phase 1 Traceability and Backlog (Draft)

This register maps proposed issues to draft requirements and evidence. GitHub issue numbers are recorded after issue creation; `CA-*` identifiers remain stable.

| ID | Backlog item | Primary trace | Planned evidence | Status |
|---|---|---|---|---|
| CA-001 | Baseline and approve Phase 1 planning package | Charter; all requirements | Reviewed charter/SRS/architecture/security set | Draft |
| CA-002 | Define evidence schema and provenance model | CA-FR-001, CA-FR-003, CA-NFR-002 | Schema proposal + fixtures + ADR candidate | Draft |
| CA-003 | Specify timestamp provenance and alignment rules | CA-FR-002 | Clock-domain fixture + deterministic ordering tests | Draft |
| CA-004 | Define read-only Kubernetes evidence collector | CA-FR-001, CA-FR-008 | RBAC review + collector design + tests | Draft |
| CA-005 | Define deterministic evidence assembler | CA-FR-003, CA-NFR-003 | Rule/version format + repeatability tests | Draft |
| CA-006 | Define hypothesis ledger and abstention contract | CA-FR-004 | Supported/contradicted/missing fixtures | Draft |
| CA-007 | Define constrained synthesis and citation checking | CA-FR-005 | Claim-to-evidence scorer + model-failure tests | Draft |
| CA-008 | Implement evaluation harness specification | CA-FR-007 | Machine-readable score report | Draft |
| CA-009 | Build and validate CA-SCENARIO-001 | CA-FR-002–007 | Versioned scenario, ground truth, false-cause result | Draft |
| CA-010 | Complete Phase 1 security and gate review | CA-FR-008; CA-NFR-001–005 | STRIDE/risk updates + gate report | Draft |

## Traceability rules

- Each implementation or test change should reference at least one stable `CA-*` backlog ID and applicable requirement IDs.
- Acceptance evidence must link to a versioned artifact or test result; narrative assertion alone is insufficient.
- Closing an issue does not approve its parent requirement.
- Requirement changes update this table and the SRS in the same reviewed change.

