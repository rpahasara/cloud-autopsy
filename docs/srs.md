# Software Requirements Specification — Phase 1 (Draft)

**Status:** Initial draft; requirements and acceptance criteria are not approved.

## Functional requirements

### CA-FR-001 — Evidence ingestion

The prototype shall ingest selected Kubernetes events/changes and selected observability evidence into a normalized evidence store while retaining the source, source identifier, observed timestamp, event timestamp, ingestion timestamp, and raw payload reference.

**Acceptance criteria**

- Given a fixture containing a Deployment change, ConfigMap change, and node event, each is stored with an immutable evidence identifier and timestamp provenance.
- Raw source content is distinguishable from derived fields.
- Duplicate ingestion is detectable and does not create indistinguishable evidence nodes.

### CA-FR-002 — Time alignment

The prototype shall build an incident-window timeline without silently treating timestamps from different clock domains as equivalent.

**Acceptance criteria**

- Timeline entries expose timestamp type and source.
- Known skew/uncertainty is recorded rather than erased.
- Ordering ties and ambiguous ordering are visible in the output.

### CA-FR-003 — Deterministic evidence bundle

Given an alert and incident window, the engine shall produce a reproducible evidence bundle and provenance relationships using deterministic logic.

**Acceptance criteria**

- Identical fixtures and configuration produce the same ordered evidence identifiers.
- Every derived relationship identifies its rule/version and input evidence.
- Missing expected evidence is represented as a gap record.

### CA-FR-004 — Hypothesis ledger

The system shall represent candidate hypotheses with supporting, contradicting, and missing evidence.

**Acceptance criteria**

- A hypothesis cannot be labeled supported without at least one evidence link.
- Contradicting evidence remains visible in narrative output.
- Insufficient evidence yields unresolved/abstained status rather than a fabricated root cause.

### CA-FR-005 — Constrained synthesis

Any AI-generated narrative shall be derived from structured evidence and shall cite evidence identifiers for factual claims.

**Acceptance criteria**

- Unsupported factual claims are detected by the scoring harness.
- Raw telemetry is treated as untrusted content, not instructions.
- Model failure does not corrupt or discard the deterministic evidence bundle.

### CA-FR-006 — Replayable investigation

The prototype shall persist enough versioned input, rule, and output metadata to replay an investigation.

**Acceptance criteria**

- Replay identifies connector, schema, rule, scenario, and model/prompt versions where applicable.
- Replay does not require production write access.
- Differences between two runs can be enumerated.

### CA-FR-007 — Evaluation harness

The evaluation harness shall execute versioned scenarios and score evidence-citation accuracy, false-cause handling, abstention behavior, and security-policy compliance.

**Acceptance criteria**

- `CA-SCENARIO-001` has declared ground truth and expected non-causes.
- Results include failures; scores are not manually overwritten.
- Threshold changes are version-controlled and reviewable.

### CA-FR-008 — Read-only enforcement

The Phase 1 prototype shall not expose production-remediation tools or require Kubernetes write permissions.

**Acceptance criteria**

- The proposed RBAC manifest can be reviewed as read-only.
- A malicious telemetry payload cannot invoke a write action.
- Any future action recommendation is descriptive only and clearly unexecuted.

## Non-functional requirements

### CA-NFR-001 — Security

Apply least privilege, secret exclusion, input sanitization boundaries, dependency review, and auditable security testing consistent with [SECURITY.md](../SECURITY.md).

### CA-NFR-002 — Reproducibility

Fixtures, ground truth, scoring configuration, and result provenance shall be versioned.

### CA-NFR-003 — Explainability

Users shall be able to inspect why evidence was included, excluded, or related.

### CA-NFR-004 — Data minimization

Only evidence necessary for the declared scenario and evaluation shall be collected; customer or real production data is out of scope.

### CA-NFR-005 — Reliability

Failures of connectors or the model shall surface as explicit partial results or gaps, not silent success.

### CA-NFR-006 — Maintainability

Connectors, evidence normalization, deterministic reasoning, synthesis, and scoring shall have explicit boundaries, with deviations documented by ADR.

## Assumptions and open questions

- PostgreSQL with JSONB is the initial evidence-store hypothesis, not an approved decision.
- Python/FastAPI is a candidate orchestration stack, not a committed production architecture.
- The target cluster, data-retention period, model provider, and UI scope remain undecided.
- Commercial claims, competitor claims, pricing, and willingness to pay require independent validation.

