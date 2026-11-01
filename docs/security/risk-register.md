# Risk Register — Phase 1 (Draft)

Ratings are preliminary (`L`, `M`, `H`) and require owner/reviewer confirmation.

| ID | Risk | Likelihood | Impact | Proposed treatment | Owner | Status |
|---|---|---:|---:|---|---|---|
| CA-RISK-001 | Confident but unsupported causal narrative | H | H | Deterministic bundle, citation checking, abstention scoring | Security reviewer | Open |
| CA-RISK-002 | Prompt injection through telemetry | H | H | Treat as data, no write tools, allowlists, security scenario | Security reviewer | Open |
| CA-RISK-003 | Timestamp skew creates false ordering | H | H | Timestamp provenance, uncertainty, clock-domain fixtures | Architecture lead | Open |
| CA-RISK-004 | Normal telemetry gaps are hidden | H | H | First-class gap records and missing-evidence variants | Evaluation engineer | Open |
| CA-RISK-005 | Read-only credentials expose sensitive data | M | H | Least privilege, minimization, fixture-only Phase 1 | Security reviewer | Open |
| CA-RISK-006 | Evaluation corpus overfits the engine | M | H | Versioned held-out variants and non-AI baseline | Evaluation engineer | Open |
| CA-RISK-007 | Ground truth or thresholds are manipulated | M | H | Reviewed version control and immutable run manifests | Evaluation engineer | Open |
| CA-RISK-008 | Scope expands into generic AI SRE platform | H | M | Charter exclusions and gated backlog | Product / requirements authority | Open |
| CA-RISK-009 | Incumbent bundled features erase differentiation | M | H | Validate replay/auditability wedge and monitor market | Product / requirements authority | Open |
| CA-RISK-010 | Commercial/security claims exceed evidence | M | H | Label hypotheses; prohibit fabricated signoff/certification | Product / requirements authority | Open |
| CA-RISK-011 | Resource exhaustion prevents complete evaluation | M | H | Configured bounds, timeout isolation and explicit truncation; CA-DEC-007 | Evaluation engineer | Open |

## Review cadence

Review at each Phase 1 gate and whenever a requirement, trust boundary, data source, model, or tool capability changes. Risk acceptance requires a named authorized approver; none is recorded here.


## Threat, requirement and test reverse links

The mappings below are exact reverse edges of the STRIDE register. Requirements and planned tests for each threat are defined there and reversed in the requirement matrix; no risk is accepted.

| Risk | Threats | Requirement/test lookup |
|---|---|---|
| CA-RISK-001 | CA-THREAT-S-001, CA-THREAT-T-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-002 | CA-THREAT-E-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-003 | No direct STRIDE threat; non-adversarial product, time or evaluation risk | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-004 | CA-THREAT-D-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-005 | CA-THREAT-S-001, CA-THREAT-I-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-006 | CA-THREAT-T-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-007 | CA-THREAT-S-001, CA-THREAT-T-001, CA-THREAT-R-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-008 | No direct STRIDE threat; non-adversarial product, time or evaluation risk | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-009 | No direct STRIDE threat; non-adversarial product, time or evaluation risk | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-010 | CA-THREAT-R-001, CA-THREAT-E-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |
| CA-RISK-011 | CA-THREAT-D-001 | [Threat requirements/tests](threat-model.md); [requirement reverse matrix](../requirement-matrix.md) |

## Exact reverse requirement and test edges

Includes direct SRS risk links and risk links inherited from mapped STRIDE threats.

| Risk | Requirements | Planned tests |
|---|---|---|
| CA-RISK-001 | CA-FR-001, CA-FR-002, CA-FR-004, CA-FR-006, CA-FR-007, CA-FR-008, CA-FR-010, CA-FR-011, CA-FR-013, CA-NFR-001, CA-NFR-010, CA-SEC-001, CA-SEC-004, CA-SEC-007, CA-SEC-010, CA-SEC-011 | CA-TEST-FR-001, CA-TEST-FR-002, CA-TEST-FR-004, CA-TEST-FR-006, CA-TEST-FR-007, CA-TEST-FR-008, CA-TEST-FR-010, CA-TEST-FR-011, CA-TEST-FR-013, CA-TEST-NFR-001, CA-TEST-NFR-010, CA-TEST-SEC-001, CA-TEST-SEC-004, CA-TEST-SEC-007, CA-TEST-SEC-010, CA-TEST-SEC-011 |
| CA-RISK-002 | CA-FR-007, CA-FR-008, CA-FR-014, CA-SEC-002, CA-SEC-003, CA-SEC-004, CA-SEC-010, CA-SEC-012 | CA-TEST-FR-007, CA-TEST-FR-008, CA-TEST-FR-014, CA-TEST-SEC-002, CA-TEST-SEC-003, CA-TEST-SEC-004, CA-TEST-SEC-010, CA-TEST-SEC-012 |
| CA-RISK-003 | CA-FR-003 | CA-TEST-FR-003 |
| CA-RISK-004 | CA-FR-005, CA-FR-006, CA-FR-009, CA-FR-013, CA-NFR-003, CA-NFR-008, CA-NFR-009, CA-SEC-009, CA-SEC-010 | CA-TEST-FR-005, CA-TEST-FR-006, CA-TEST-FR-009, CA-TEST-FR-013, CA-TEST-NFR-003, CA-TEST-NFR-008, CA-TEST-NFR-009, CA-TEST-SEC-009, CA-TEST-SEC-010 |
| CA-RISK-005 | CA-FR-001, CA-FR-002, CA-FR-014, CA-NFR-004, CA-SEC-001, CA-SEC-005, CA-SEC-006, CA-SEC-007, CA-SEC-008 | CA-TEST-FR-001, CA-TEST-FR-002, CA-TEST-FR-014, CA-TEST-NFR-004, CA-TEST-SEC-001, CA-TEST-SEC-005, CA-TEST-SEC-006, CA-TEST-SEC-007, CA-TEST-SEC-008 |
| CA-RISK-006 | CA-FR-004, CA-FR-010, CA-FR-011, CA-NFR-001, CA-NFR-010, CA-SEC-007, CA-SEC-011 | CA-TEST-FR-004, CA-TEST-FR-010, CA-TEST-FR-011, CA-TEST-NFR-001, CA-TEST-NFR-010, CA-TEST-SEC-007, CA-TEST-SEC-011 |
| CA-RISK-007 | CA-FR-001, CA-FR-002, CA-FR-004, CA-FR-010, CA-FR-011, CA-FR-012, CA-NFR-001, CA-NFR-002, CA-NFR-006, CA-NFR-010, CA-SEC-001, CA-SEC-007, CA-SEC-008, CA-SEC-011, CA-SEC-012 | CA-TEST-FR-001, CA-TEST-FR-002, CA-TEST-FR-004, CA-TEST-FR-010, CA-TEST-FR-011, CA-TEST-FR-012, CA-TEST-NFR-001, CA-TEST-NFR-002, CA-TEST-NFR-006, CA-TEST-NFR-010, CA-TEST-SEC-001, CA-TEST-SEC-007, CA-TEST-SEC-008, CA-TEST-SEC-011, CA-TEST-SEC-012 |
| CA-RISK-008 | Outside requirement conformance: product charter scope and differentiation review | Product / requirements authority review at Phase 1 gate |
| CA-RISK-009 | Outside requirement conformance: product charter scope and differentiation review | Product / requirements authority review at Phase 1 gate |
| CA-RISK-010 | CA-FR-007, CA-FR-008, CA-FR-010, CA-FR-012, CA-FR-014, CA-NFR-002, CA-NFR-006, CA-SEC-002, CA-SEC-003, CA-SEC-004, CA-SEC-007, CA-SEC-008, CA-SEC-010, CA-SEC-012 | CA-TEST-FR-007, CA-TEST-FR-008, CA-TEST-FR-010, CA-TEST-FR-012, CA-TEST-FR-014, CA-TEST-NFR-002, CA-TEST-NFR-006, CA-TEST-SEC-002, CA-TEST-SEC-003, CA-TEST-SEC-004, CA-TEST-SEC-007, CA-TEST-SEC-008, CA-TEST-SEC-010, CA-TEST-SEC-012 |
| CA-RISK-011 | CA-FR-013, CA-NFR-003, CA-NFR-008, CA-NFR-009, CA-SEC-009, CA-SEC-010 | CA-TEST-FR-013, CA-TEST-NFR-003, CA-TEST-NFR-008, CA-TEST-NFR-009, CA-TEST-SEC-009, CA-TEST-SEC-010 |

## Phase 1C residual-risk assessment

[Architecture security coverage](../architecture/phase1c/security.md) details residual semantic, disclosure, continuity, privileged-integrity, evaluation and resource-exhaustion risks. All existing ratings/statuses remain preliminary/open; no acceptance or downgrade is recorded.
