# Risk Register — Phase 1 (Draft)

Ratings are preliminary (`L`, `M`, `H`) and require owner/reviewer confirmation.

| ID | Risk | Likelihood | Impact | Proposed treatment | Owner | Status |
|---|---|---:|---:|---|---|---|
| CA-RISK-001 | Confident but unsupported causal narrative | H | H | Deterministic bundle, citation checking, abstention scoring | Unassigned | Open |
| CA-RISK-002 | Prompt injection through telemetry | H | H | Treat as data, no write tools, allowlists, security scenario | Unassigned | Open |
| CA-RISK-003 | Timestamp skew creates false ordering | H | H | Timestamp provenance, uncertainty, clock-domain fixtures | Unassigned | Open |
| CA-RISK-004 | Normal telemetry gaps are hidden | H | H | First-class gap records and missing-evidence variants | Unassigned | Open |
| CA-RISK-005 | Read-only credentials expose sensitive data | M | H | Least privilege, minimization, fixture-only Phase 1 | Unassigned | Open |
| CA-RISK-006 | Evaluation corpus overfits the engine | M | H | Versioned held-out variants and non-AI baseline | Unassigned | Open |
| CA-RISK-007 | Ground truth or thresholds are manipulated | M | H | Reviewed version control and immutable run manifests | Unassigned | Open |
| CA-RISK-008 | Scope expands into generic AI SRE platform | H | M | Charter exclusions and gated backlog | Unassigned | Open |
| CA-RISK-009 | Incumbent bundled features erase differentiation | M | H | Validate replay/auditability wedge and monitor market | Unassigned | Open |
| CA-RISK-010 | Commercial/security claims exceed evidence | M | H | Label hypotheses; prohibit fabricated signoff/certification | Unassigned | Open |

## Review cadence

Review at each Phase 1 gate and whenever a requirement, trust boundary, data source, model, or tool capability changes. Risk acceptance requires a named authorized approver; none is recorded here.

