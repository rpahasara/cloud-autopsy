# Phase 1 Traceability and Backlog (Draft)

This register maps GitHub backlog items to the proposed `CA-SRS-P1` version
`0.2.0-draft`. Requirement identifiers are stable; all requirements remain unapproved.

| ID | GitHub | Backlog item | Primary trace | Planned evidence | Status |
|---|---|---|---|---|---|
| CA-001 | [#1](https://github.com/rpahasara/cloud-autopsy/issues/1) | Baseline Phase 1 planning package | Document control; roles; all requirement classes; `CA-DEC-008` | Reviewed SRS/audit/traceability set and explicit approval record | Draft |
| CA-002 | [#2](https://github.com/rpahasara/cloud-autopsy/issues/2) | Define evidence schema and provenance model | `CA-FR-002/010`, `CA-NFR-001/010`, `CA-SEC-007` | Schema proposal, integrity rules, fixtures, replay tests, ADR candidate | Draft |
| CA-003 | [#3](https://github.com/rpahasara/cloud-autopsy/issues/3) | Specify timestamp provenance and alignment rules | `CA-FR-003/004`, `CA-NFR-002`, `CA-DEC-003` | Clock-domain fixture, uncertainty model, deterministic ordering tests | Draft |
| CA-004 | [#4](https://github.com/rpahasara/cloud-autopsy/issues/4) | Define read-only Kubernetes evidence collector | `CA-FR-001/014`, `CA-SEC-001/002/005/009` | RBAC review, bounded connector design, negative mutation tests | Draft |
| CA-005 | [#5](https://github.com/rpahasara/cloud-autopsy/issues/5) | Define deterministic evidence assembler | `CA-FR-004/005`, `CA-NFR-002/005` | Rule/version format, repeatability, gap, and provenance tests | Draft |
| CA-006 | [#6](https://github.com/rpahasara/cloud-autopsy/issues/6) | Define hypothesis ledger and abstention contract | `CA-FR-006/009/012`, `CA-RISK-001/004` | Support/contradiction/gap fixtures and abstention evidence | Draft |
| CA-007 | [#7](https://github.com/rpahasara/cloud-autopsy/issues/7) | Define constrained synthesis and citation checking | `CA-FR-007/008/013`, `CA-SEC-003/004/006/010` | Citation scorer, injection, invalid-output, and model-failure tests | Draft |
| CA-008 | [#8](https://github.com/rpahasara/cloud-autopsy/issues/8) | Specify the Phase 1 evaluation harness | `CA-FR-010/011`, `CA-NFR-001/006–010`, `CA-SEC-007/008/011` | Immutable machine-readable score report and run manifest | Draft |
| CA-009 | [#9](https://github.com/rpahasara/cloud-autopsy/issues/9) | Build and validate CA-SCENARIO-001 | Scenario matrix `A–E`; `CA-FR-003–009/013/014` | Ground truth; false-cause, gap, injection, skew, and failure results | Draft |
| CA-010 | [#10](https://github.com/rpahasara/cloud-autopsy/issues/10) | Complete Phase 1 security and gate review | All `CA-SEC-*`; `CA-DEC-004/005/006/008` | STRIDE/risk updates, security evidence, measured gate report | Draft |

## Traceability rules

- Each implementation or test change should reference at least one stable `CA-*` backlog ID and applicable requirement IDs.
- Acceptance evidence must link to a versioned artifact or test result; narrative assertion alone is insufficient.
- Closing an issue does not approve its parent requirement.
- Requirement changes update this table and the SRS in the same reviewed change.
- A `TBD-APPROVAL` remains open until a named authorized owner records a decision; implementation must not invent a value.
- Verification success, issue closure, or PR merge does not change a requirement from `Draft` to `Approved`.

## Baseline completeness checks

- [x] Functional, non-functional, and security requirement identifiers are defined.
- [x] Human roles and approval separation are defined.
- [x] `CA-SCENARIO-001` variants map to draft requirements.
- [x] GitHub issues `CA-001` through `CA-010` map to planned evidence.
- [ ] Requirement, security, and architecture approvers are named.
- [ ] Approval decisions `CA-DEC-001` through `CA-DEC-008` are resolved.
- [ ] Requirement baseline approval is recorded.

