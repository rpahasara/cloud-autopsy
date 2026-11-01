# Phase 1 Traceability and Backlog (Draft)

This register maps proposed issues to draft requirements and evidence. GitHub issue numbers are recorded after issue creation; `CA-*` identifiers remain stable.

| ID | GitHub | Backlog item | Primary trace | Planned evidence | Status |
|---|---|---|---|---|---|
| CA-001 | [#1](https://github.com/rpahasara/cloud-autopsy/issues/1) | Baseline Phase 1 planning package | Charter; all requirements | Reviewed charter/SRS/architecture/security set | Draft |
| CA-002 | [#2](https://github.com/rpahasara/cloud-autopsy/issues/2) | Define evidence schema and provenance model | CA-FR-001, CA-FR-003, CA-NFR-002 | Schema proposal + fixtures + ADR candidate | Draft |
| CA-003 | [#3](https://github.com/rpahasara/cloud-autopsy/issues/3) | Specify timestamp provenance and alignment rules | CA-FR-002 | Clock-domain fixture + deterministic ordering tests | Draft |
| CA-004 | [#4](https://github.com/rpahasara/cloud-autopsy/issues/4) | Define read-only Kubernetes evidence collector | CA-FR-001, CA-FR-008 | RBAC review + collector design + tests | Draft |
| CA-005 | [#5](https://github.com/rpahasara/cloud-autopsy/issues/5) | Define deterministic evidence assembler | CA-FR-003, CA-NFR-003 | Rule/version format + repeatability tests | Draft |
| CA-006 | [#6](https://github.com/rpahasara/cloud-autopsy/issues/6) | Define hypothesis ledger and abstention contract | CA-FR-004 | Supported/contradicted/missing fixtures | Draft |
| CA-007 | [#7](https://github.com/rpahasara/cloud-autopsy/issues/7) | Define constrained synthesis and citation checking | CA-FR-005 | Claim-to-evidence scorer + model-failure tests | Draft |
| CA-008 | [#8](https://github.com/rpahasara/cloud-autopsy/issues/8) | Specify the Phase 1 evaluation harness | CA-FR-007 | Machine-readable score report | Draft |
| CA-009 | [#9](https://github.com/rpahasara/cloud-autopsy/issues/9) | Build and validate CA-SCENARIO-001 | CA-FR-002–007 | Versioned scenario, ground truth, false-cause result | Draft |
| CA-010 | [#10](https://github.com/rpahasara/cloud-autopsy/issues/10) | Complete Phase 1 security and gate review | CA-FR-008; CA-NFR-001–005 | STRIDE/risk updates + gate report | Draft |

## Traceability rules

- Each implementation or test change should reference at least one stable `CA-*` backlog ID and applicable requirement IDs.
- Acceptance evidence must link to a versioned artifact or test result; narrative assertion alone is insufficient.
- Closing an issue does not approve its parent requirement.
- Requirement changes update this table and the SRS in the same reviewed change.

