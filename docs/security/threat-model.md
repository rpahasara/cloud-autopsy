# STRIDE Threat Model — Phase 1 (Draft)

Stable threat IDs are never reused. Treatments and tests are proposed; no security approval or executed test evidence exists. Assets: evidence/provenance, ground truth/scores, credentials, telemetry, policy boundaries and human trust. Trust boundaries are in [architecture context](../architecture/context.md).

| Threat ID | STRIDE category | Threat | Risks | Requirements | Planned tests / assertions |
|---|---|---|---|---|---|
| CA-THREAT-S-001 | Spoofing | Forged source identity or reused evidence ID | CA-RISK-001, CA-RISK-005, CA-RISK-007 | CA-FR-001, CA-FR-002, CA-SEC-001, CA-SEC-007 | CA-TEST-FR-001, CA-TEST-FR-002, CA-TEST-SEC-001, CA-TEST-SEC-007: Inject conflicting source identities and IDs; reject collisions without overwriting provenance. |
| CA-THREAT-T-001 | Tampering | Fixture, ground truth, rule or scorer altered after run | CA-RISK-001, CA-RISK-006, CA-RISK-007 | CA-FR-004, CA-FR-010, CA-FR-011, CA-NFR-001, CA-NFR-010, CA-SEC-007, CA-SEC-011 | CA-TEST-FR-004, CA-TEST-FR-010, CA-TEST-FR-011, CA-TEST-NFR-001, CA-TEST-NFR-010, CA-TEST-SEC-007, CA-TEST-SEC-011: Modify each protected input after manifest creation; detect mismatch. Reject unsupported schema or dependency provenance. |
| CA-THREAT-R-001 | Repudiation | Cannot reconstruct claim, rule, model or deletion history | CA-RISK-007, CA-RISK-010 | CA-FR-010, CA-FR-012, CA-NFR-002, CA-NFR-006, CA-SEC-007, CA-SEC-008, CA-SEC-012 | CA-TEST-FR-010, CA-TEST-FR-012, CA-TEST-NFR-002, CA-TEST-NFR-006, CA-TEST-SEC-007, CA-TEST-SEC-008, CA-TEST-SEC-012: Replay from retained manifest; verify audit correlation, tombstone and explicit incomplete-replay state after expiry. |
| CA-THREAT-I-001 | Information disclosure | Read credentials or telemetry disclose secrets to storage/model | CA-RISK-005 | CA-NFR-004, CA-SEC-001, CA-SEC-005, CA-SEC-006, CA-SEC-008 | CA-TEST-NFR-004, CA-TEST-SEC-001, CA-TEST-SEC-005, CA-TEST-SEC-006, CA-TEST-SEC-008: Seed secret canaries in inputs/audits; verify exclusion and disabled external egress; inspect least privilege. |
| CA-THREAT-D-001 | Denial of service | Unbounded telemetry or model latency exhausts evaluator | CA-RISK-004, CA-RISK-011 | CA-FR-013, CA-NFR-003, CA-NFR-008, CA-NFR-009, CA-SEC-009, CA-SEC-010 | CA-TEST-FR-013, CA-TEST-NFR-003, CA-TEST-NFR-008, CA-TEST-NFR-009, CA-TEST-SEC-009, CA-TEST-SEC-010: Exercise at/above byte, record, cardinality, window and retry bounds; model timeout preserves deterministic output. |
| CA-THREAT-E-001 | Elevation of privilege | Prompt injection or forged approval induces action/policy bypass | CA-RISK-002, CA-RISK-010 | CA-FR-007, CA-FR-008, CA-FR-014, CA-SEC-002, CA-SEC-003, CA-SEC-004, CA-SEC-010, CA-SEC-012 | CA-TEST-FR-007, CA-TEST-FR-008, CA-TEST-FR-014, CA-TEST-SEC-002, CA-TEST-SEC-003, CA-TEST-SEC-004, CA-TEST-SEC-010, CA-TEST-SEC-012: Scenario 001-C plus malicious annotation/tool response and forged approval; no action, mutation or approval status change. |

## Reverse mapping and treatment ownership

[Requirement matrix](../requirement-matrix.md) contains the reverse requirement-to-threat and test edges; [risk register](risk-register.md) contains reverse risk-to-threat edges and owning roles. Each test exercises its parent requirement acceptance criteria plus every threat assertion in the rows that reference it. Use the [scenario matrix](../scenarios/CA-SCENARIO-001.md) for A–E; standalone integrity, lifecycle, RBAC, egress, bounds and supply-chain tests are additional qualification work.

## Residual questions

Credential storage/rotation, independent risk acceptance, retention approval, external network policy and stronger signing/tamper evidence remain unresolved. Review on any changed source, model, permission, schema, expiry policy or trust boundary.

## Phase 1C boundary coverage

[Flow-by-flow STRIDE coverage](../architecture/phase1c/security.md) refines these six stable threats across TB0–TB5 and F1–F16 with specific controls, residual risks and required security-test artifacts. No threat is marked mitigated by documentation alone.
