# Architecture Decision Record Register

CA-DEC identifiers are the canonical decision IDs used by the SRS. The previous ADR-001 through ADR-006 entries were topic placeholders, never accepted records; their evidence-store, time, connector, rule, model and replay topics are now covered by CA-DEC-001/002/003/004/005. No old approval is implied.

| Decision | Topic | Status |
|---|---|---|
| [CA-DEC-001](CA-DEC-001.md) | System boundary and allowed sources | Proposed |
| [CA-DEC-002](CA-DEC-002.md) | Evidence store and provenance | Proposed |
| [CA-DEC-003](CA-DEC-003.md) | Timestamp provenance and skew | Proposed |
| [CA-DEC-004](CA-DEC-004.md) | Model boundary, provider and data egress | Proposed |
| [CA-DEC-005](CA-DEC-005.md) | Evidence lifecycle and replay after expiry | Proposed |
| [CA-DEC-006](CA-DEC-006.md) | Evaluation and security gates | Proposed |
| [CA-DEC-007](CA-DEC-007.md) | Performance and capacity budgets | Proposed |
| [CA-DEC-008](CA-DEC-008.md) | Accountability and approval authorities | Proposed |

Use [the template](ADR-000-template.md) for future proposals. Every record requires rationale, alternatives, security implications, decision owner, approval status and review triggers. Merge and issue closure never accept a decision.

## Phase 1C refinements

Each CA-DEC-001 through CA-DEC-008 now links its [detailed architecture refinement](../phase1c/README.md), preserving Proposed status, existing rationale/alternatives, owner and review triggers. No authority or provider access is approved.
