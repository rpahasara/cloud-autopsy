# Phase 1 Traceability and Backlog (Draft)

Maps SRS `0.3.0-draft`. All issues remain open; all requirements remain Draft. This table and the [requirement matrix](requirement-matrix.md) contain exact reverse issue/requirement edges; CA-001 governs the whole planning package in addition to its direct requirements. Planned tests are specifications, not results.

| Backlog / GitHub | Requirements | Decisions | Planned evidence | Status |
|---|---|---|---|---|
| [CA-001 / #1](https://github.com/rpahasara/cloud-autopsy/issues/1) | CA-FR-012 | CA-DEC-005, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-002 / #2](https://github.com/rpahasara/cloud-autopsy/issues/2) | CA-FR-001, CA-FR-002, CA-FR-010, CA-NFR-001, CA-NFR-005, CA-NFR-010, CA-SEC-007 | CA-DEC-001, CA-DEC-002, CA-DEC-005, CA-DEC-006, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-003 / #3](https://github.com/rpahasara/cloud-autopsy/issues/3) | CA-FR-003, CA-FR-004, CA-FR-010, CA-NFR-002 | CA-DEC-002, CA-DEC-003, CA-DEC-005, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-004 / #4](https://github.com/rpahasara/cloud-autopsy/issues/4) | CA-FR-001, CA-FR-014, CA-NFR-003, CA-NFR-004, CA-NFR-009, CA-SEC-001, CA-SEC-002, CA-SEC-005, CA-SEC-009 | CA-DEC-001, CA-DEC-004, CA-DEC-005, CA-DEC-007, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-005 / #5](https://github.com/rpahasara/cloud-autopsy/issues/5) | CA-FR-004, CA-FR-005, CA-FR-010, CA-NFR-001, CA-NFR-002, CA-NFR-005 | CA-DEC-002, CA-DEC-003, CA-DEC-005, CA-DEC-006, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-006 / #6](https://github.com/rpahasara/cloud-autopsy/issues/6) | CA-FR-005, CA-FR-006, CA-FR-009, CA-FR-012, CA-NFR-002 | CA-DEC-003, CA-DEC-005, CA-DEC-006, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-007 / #7](https://github.com/rpahasara/cloud-autopsy/issues/7) | CA-FR-007, CA-FR-008, CA-FR-013, CA-NFR-003, CA-NFR-004, CA-NFR-005, CA-SEC-003, CA-SEC-004, CA-SEC-006, CA-SEC-010 | CA-DEC-002, CA-DEC-004, CA-DEC-005, CA-DEC-006, CA-DEC-007, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-008 / #8](https://github.com/rpahasara/cloud-autopsy/issues/8) | CA-FR-010, CA-FR-011, CA-FR-012, CA-NFR-001, CA-NFR-003, CA-NFR-005, CA-NFR-006, CA-NFR-007, CA-NFR-008, CA-NFR-009, CA-NFR-010, CA-SEC-007, CA-SEC-008, CA-SEC-011 | CA-DEC-002, CA-DEC-005, CA-DEC-006, CA-DEC-007, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; versioned design and acceptance evidence | Draft / open |
| [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9) | CA-FR-002, CA-FR-003, CA-FR-004, CA-FR-005, CA-FR-006, CA-FR-007, CA-FR-008, CA-FR-009, CA-FR-010, CA-FR-011, CA-FR-013, CA-FR-014, CA-NFR-001, CA-NFR-002, CA-NFR-003, CA-NFR-007, CA-SEC-001, CA-SEC-002, CA-SEC-003, CA-SEC-004, CA-SEC-007, CA-SEC-009, CA-SEC-010 | CA-DEC-001, CA-DEC-002, CA-DEC-003, CA-DEC-004, CA-DEC-005, CA-DEC-006, CA-DEC-007, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; scenario A–E qualification, ground truth and integrity; full corpus is separate | Draft / open |
| [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10) | CA-FR-008, CA-FR-014, CA-NFR-001, CA-NFR-002, CA-NFR-003, CA-NFR-004, CA-NFR-005, CA-NFR-006, CA-NFR-007, CA-NFR-008, CA-NFR-009, CA-NFR-010, CA-SEC-001, CA-SEC-002, CA-SEC-003, CA-SEC-004, CA-SEC-005, CA-SEC-006, CA-SEC-007, CA-SEC-008, CA-SEC-009, CA-SEC-010, CA-SEC-011, CA-SEC-012 | CA-DEC-001, CA-DEC-002, CA-DEC-003, CA-DEC-004, CA-DEC-005, CA-DEC-006, CA-DEC-007, CA-DEC-008 | Linked CA-TEST entries in requirement matrix; STRIDE/risk and full corpus gate review, including provisional performance budgets | Draft / open |

## Traceability rules

- Update the SRS, both matrix directions, affected decision/threat/risk records, scenario tests and issue bodies together.
- Every run/test report names its requirement, test, scenario, fixtures, ground truth, scorer and manifest versions. Link failures as well as passes.
- The threat register defines exact threat/risk/requirement/test edges. Non-adversarial risks remain visible in the risk register.
- CA-DEC-007 belongs to CA-010 gate review. CA-FR-011 and CA-SEC-007 belong to CA-009 scenario verification as well as CA-008 harness design.
- A benchmark does not approve a budget. Named authorities and explicit approval records are required.
- Closing issues or merging documentation never approves requirements or authorizes implementation.

## Open prerequisites

- [ ] Named product, architecture, security, evaluation and risk authorities and independent review.
- [ ] Product-owner disposition of CA-DEC-001 through CA-DEC-008; separate egress/security approval before any external provider access.
- [ ] Benchmarked and approved quality metrics and performance/capacity budgets.
- [ ] Full 8–12-scenario corpus and reviewed held-out results.
- [ ] Explicit requirements baseline approval and separately authorized implementation plan.

## Phase 1C architecture proposal

[Architecture traceability](architecture/phase1c/traceability.md) gives detailed design evidence for issues #1 through #10 and all 36 stable requirements. The separate architecture draft is stacked on PR #11; no issue is closed or requirement/decision approved.
