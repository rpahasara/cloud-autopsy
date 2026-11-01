# Cloud Autopsy Software Requirements Specification — Phase 1

| Field | Value |
|---|---|
| Document ID | `CA-SRS-P1` |
| Version | `0.3.0-draft` |
| Status | Draft for review — not approved and not baselined |
| Product | Cloud Autopsy |
| Lifecycle stage | Phase 1 planning and evaluation prototype |
| Current repository owner | `rpahasara` |
| Intended future product owner | AU4 Labs |
| Requirement authority | Unassigned; approval required |
| Security reviewer | Unassigned; approval required |
| Last updated | 2026-11-01 |

> This document is a proposed requirements baseline. A pull-request merge, issue closure,
> milestone completion, or repository transfer does not approve these requirements. No
> application development is authorized by this document.

## 1. Document control

### 1.1 Revision history

| Version | Date | Change | Approval status |
|---|---|---|---|
| `0.1.0-draft` | 2026-11-01 | Initial functional and non-functional requirements | Not approved |
| `0.2.0-draft` | 2026-11-01 | Expanded roles, security requirements, acceptance criteria, traceability, scenario verification, and change control | Not approved |
| `0.3.0-draft` | 2026-11-01 | Independent review remediation: ownership, corpus, traceability, threats, lifecycle and proposed decisions | Not approved |

### 1.2 Baseline and change-control rules

1. Stable requirement identifiers shall not be reused for a different meaning.
2. Proposed requirement changes shall identify affected issues, scenarios, risks, ADRs, and acceptance evidence.
3. A requirement may be marked `Approved` only by the named requirement authority after security and architecture review responsibilities are assigned.
4. Superseded requirements remain in version history; they are not silently deleted.
5. Test success demonstrates conformance only; it does not constitute requirement approval.
6. Until an approval record exists, every requirement in this document has status `Draft`.

### 1.3 Requirement language and attributes

- **Shall** denotes a mandatory proposed requirement.
- **Should** denotes a proposed objective that may be deferred with an explicit rationale.
- **May** denotes a permitted capability, not an obligation.
- Priority uses `Must`, `Should`, or `Could` for Phase 1 planning.
- Verification uses `Inspection`, `Test`, `Analysis`, or `Demonstration`.
- Acceptance criteria are normative only after the parent requirement is approved.

## 2. Purpose and scope

Cloud Autopsy is a proposed deterministic, evidence-first incident reconstruction product. Phase 1 evaluates whether a read-only system can assemble a replayable, provenance-linked timeline from Kubernetes and observability evidence, distinguish causal evidence from correlation, expose missing evidence, and constrain AI-generated explanations to supported claims.

Phase 1 is an evaluation prototype, not a production release. It uses synthetic or explicitly authorized sanitized data and shall not operate autonomous remediation tools.

### 2.1 Phase 1 objectives

- Establish a deterministic non-AI evidence baseline.
- Make timestamp provenance and uncertainty inspectable.
- Represent supporting, contradicting, and missing evidence explicitly.
- Measure evidence-citation accuracy, false-cause handling, abstention, and security-policy compliance with reproducible scenarios.
- Produce evidence that supports a later go/no-go decision without claiming commercial, security, or production readiness.

### 2.2 In scope

- One local or isolated demo Kubernetes environment.
- Selected Kubernetes events and object changes.
- Selected metrics, logs, and deployment metadata used by declared scenarios.
- Normalized evidence, provenance relationships, incident-window time alignment, evidence bundles, a hypothesis ledger, constrained synthesis, replay metadata, and evaluation output.
- Initial investigation-harness qualification using the five `CA-SCENARIO-001` variants; the full evaluation gate requires the planned 8–12-scenario [corpus](scenarios/corpus-plan.md). Variants do not count as independent scenarios.
- Read-only access design and security-policy tests.

### 2.3 Out of scope

- Production deployment or production customer telemetry.
- Autonomous or approval-gated remediation execution.
- Kubernetes write permissions.
- Multi-tenancy, billing, production SLAs, or compliance certification.
- A production user interface or accessibility conformance claim.
- General multi-cloud AIOps coverage.
- Final technology selection where an ADR and owner approval are still required.

## 3. References

- [Phase 1 product charter](product-charter.md)
- [Architecture context](architecture/context.md)
- [ADR register](architecture/adr/README.md)
- [CA-SCENARIO-001](scenarios/CA-SCENARIO-001.md)
- [STRIDE threat model](security/threat-model.md)
- [Risk register](security/risk-register.md)
- [Phase 1 traceability and backlog](traceability.md)
- [Security practices](../SECURITY.md)

## 4. Definitions

| Term | Definition |
|---|---|
| Evidence node | Immutable logical record that identifies a source observation and its provenance. |
| Derived evidence | A value or relationship computed from one or more evidence nodes with a recorded rule/version. |
| Evidence bundle | Ordered, versioned set of evidence, relationships, and explicit gaps assembled for an incident window. |
| Evidence gap | Expected evidence that is unavailable, failed retrieval, out of scope, or otherwise unverified. |
| Hypothesis ledger | Structured set of candidate explanations and their supporting, contradicting, and missing evidence. |
| Claim | A factual statement in a generated or deterministic investigation output. |
| Citation | Reference from a claim to one or more valid evidence identifiers. |
| Abstention | Explicit refusal to select or confirm a cause because evidence is insufficient or conflicting. |
| Replay | Re-execution or reconstruction using versioned inputs, configuration, rules, and model metadata. |
| False-cause trap | A deliberately correlated but noncausal change included to test causal discipline. |

## 5. User roles and external actors

### 5.1 Human roles

| Role ID | Role | Phase 1 responsibilities | Explicit limitations |
|---|---|---|---|
| `CA-ROLE-001` | Incident investigator | Starts or inspects an investigation; reviews timelines, evidence, hypotheses, gaps, and replay differences. | Cannot authorize production action through Phase 1. |
| `CA-ROLE-002` | Evaluation engineer | Defines fixtures, ground truth, variants, and scoring configuration; runs the evaluation harness. | Cannot silently alter historical results or thresholds. |
| `CA-ROLE-003` | Requirements reviewer | Reviews requirement clarity, traceability, scope, and acceptance evidence. | Review does not equal approval unless also named as requirement authority. |
| `CA-ROLE-004` | Security reviewer | Reviews trust boundaries, permissions, data handling, threat treatments, and security-test evidence. | Risk acceptance requires separately recorded authority. |
| `CA-ROLE-005` | Repository maintainer | Maintains version control, pull-request workflow, issue links, and protected planning artifacts. | Merge access does not grant product or security approval authority. |
| `CA-ROLE-007` | Architecture lead | Owns evidence, time, reasoning and replay contracts; assembles architecture evidence. | Does not acquire architecture approval authority by owning requirements. |
| `CA-ROLE-006` | Requirement authority | Accepts, rejects, or returns proposed requirements for revision. | Unassigned in this draft. |

### 5.2 External system actors

- Demo Kubernetes API and event sources.
- Metrics, logs, and deployment-metadata sources declared by a scenario.
- Optional model provider behind a constrained synthesis boundary.
- Version-control and CI services used for planning artifacts and future verification.

## 6. Assumptions, dependencies, and constraints

### 6.1 Assumptions

- Phase 1 evidence is synthetic or explicitly authorized and sanitized.
- The initial scenario targets a single isolated Kubernetes environment.
- Source clocks may be skewed and evidence may be missing.
- Logs, annotations, commit/deployment metadata, model responses, and scenario content can be attacker-controlled.

### 6.2 Candidate dependencies requiring decisions

- PostgreSQL/JSONB is the candidate evidence store, not an approved choice.
- Python/FastAPI is the candidate orchestration stack, not an approved choice.
- kind, Prometheus, Grafana, and Loki are candidate demo components.
- MVP proposals for model policy, retention, incident windows and performance are recorded in [CA-DEC-001 through 008](architecture/adr/README.md); none is approved. External provider access requires separate data-egress and security approval.

### 6.3 Hard Phase 1 constraints

- No production application code is authorized by this baseline review.
- No production write access or remediation execution is in scope.
- No claim may be presented as supported without traceable evidence.
- Missing or failed evidence retrieval shall not be interpreted as evidence of absence.

## 7. Functional requirements

Every requirement in this section is `Draft`.

### CA-FR-001 — Acquire scoped evidence

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-001"></a>

- **Priority:** Must
- **Verification:** Test, Inspection
- **Trace:** `CA-002`, `CA-004`; `CA-SCENARIO-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-001)

The system shall acquire only the Kubernetes and observability evidence sources enabled for the declared scenario and incident window.

**Acceptance criteria**

1. A run manifest identifies each enabled connector, query scope, and incident window.
2. Evidence outside the declared scope is not required for a passing run.
3. Connector success, partial success, empty response, and failure are distinguishable.

### CA-FR-002 — Normalize evidence with immutable identity

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-002"></a>

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-002`, `CA-009`; `CA-RISK-001`, `CA-RISK-007`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-002)

The system shall normalize acquired observations into evidence nodes with stable identifiers while retaining a reference to the raw source representation or its explicit expiry/deletion tombstone under the [lifecycle contract](evidence-lifecycle.md).

**Acceptance criteria**

1. Each evidence node contains source type, source identifier, raw-reference integrity data, schema version, and ingestion metadata.
2. Raw and derived fields are distinguishable.
3. Re-ingesting the same fixture is idempotent or produces explicitly related duplicates.

### CA-FR-003 — Preserve timestamp provenance

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-003"></a>

- **Priority:** Must
- **Verification:** Test, Analysis
- **Trace:** `CA-003`, `CA-009`; `CA-RISK-003`, `CA-SCENARIO-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-003)

The system shall retain event, observation, ingestion, and source clock-domain information without silently converting uncertain timestamps into a single authoritative time.

**Acceptance criteria**

1. Every timeline entry identifies timestamp type and source.
2. Known clock offset, resolution, and uncertainty are retained when available.
3. Ambiguous ordering is represented explicitly.

### CA-FR-004 — Assemble a deterministic evidence bundle

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-004"></a>

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-003`, `CA-005`, `CA-009`; `CA-RISK-001`, `CA-SCENARIO-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-004)

Given identical versioned inputs and configuration, the deterministic engine shall produce the same ordered evidence identifiers, relationships, and gap identifiers.

**Acceptance criteria**

1. Two identical runs produce equivalent deterministic bundle manifests.
2. Every derived relationship identifies its rule/version and input evidence identifiers.
3. Any permitted nondeterministic metadata is excluded from equivalence scoring or normalized.

### CA-FR-005 — Represent evidence gaps

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-005"></a>

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-005`, `CA-006`, `CA-009`; `CA-RISK-004`, `CA-SCENARIO-001-B`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-005)

The system shall create explicit gap records for expected evidence that is missing, failed, out of scope, or unverifiable.

**Acceptance criteria**

1. A gap records its type, expected source, detection rule, and effect on affected hypotheses.
2. Connector failure is not reported as a clean negative observation.
3. The missing-ConfigMap variant cannot confirm the correlated Deployment as the root cause.

### CA-FR-006 — Maintain a hypothesis ledger

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-006"></a>

- **Priority:** Must
- **Verification:** Test, Demonstration
- **Trace:** `CA-006`, `CA-009`; `CA-RISK-001`, `CA-RISK-004`, `CA-SCENARIO-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-006)

The system shall represent each candidate hypothesis with supporting, contradicting, missing, and not-evaluated evidence, plus a status and rationale.

**Acceptance criteria**

1. Supported status requires at least one valid supporting evidence link.
2. Contradicting evidence remains visible and cannot be discarded by narrative synthesis.
3. Insufficient or conflicting evidence produces unresolved or abstained status.

### CA-FR-007 — Produce constrained narrative synthesis

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-007"></a>

- **Priority:** Should
- **Verification:** Test, Inspection
- **Trace:** `CA-007`, `CA-009`; `CA-RISK-001`, `CA-RISK-002`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-007)

When synthesis is enabled, the system shall provide the model only the structured evidence contract needed for the declared output and shall label telemetry as untrusted data.

**Acceptance criteria**

1. Synthesis can be disabled without preventing deterministic bundle evaluation.
2. Output conforms to a versioned schema.
3. Model instructions or tool requests originating in telemetry are not executed.

### CA-FR-008 — Validate claims and citations

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-008"></a>

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-007`, `CA-009`, `CA-010`; `CA-RISK-001`, `CA-SCENARIO-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-008)

The system shall validate factual claims against evidence identifiers before presenting them as supported.

**Acceptance criteria**

1. Nonexistent or out-of-bundle evidence identifiers are rejected.
2. Unsupported claims are counted and labeled; they are not silently accepted.
3. The evaluation output reports claim count, supported-claim count, unsupported-claim count, and citation-correctness score.

### CA-FR-009 — Support abstention

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-009"></a>

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-006`, `CA-009`; `CA-RISK-004`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-009)

The system shall support an explicit abstention outcome when evidence is insufficient, contradictory, or outside supported inference rules.

**Acceptance criteria**

1. Abstention includes a machine-readable reason and relevant evidence gaps.
2. Abstention does not generate a substitute root-cause claim.
3. Designated missing-evidence scenarios are scored for abstention correctness.

### CA-FR-010 — Replay an investigation

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-010"></a>

- **Priority:** Must
- **Verification:** Test, Demonstration
- **Trace:** `CA-002`, `CA-003`, `CA-005`, `CA-008`, `CA-009`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-010)

The system shall persist a versioned run manifest sufficient to reconstruct or compare an investigation from retained Phase 1 fixtures.

**Acceptance criteria**

1. The manifest identifies connector, schema, rule, scenario, scoring, prompt, and model versions where applicable.
2. Replay does not require Kubernetes write permissions.
3. Differences between two run manifests and outputs can be enumerated.
4. Under the [evidence lifecycle contract](evidence-lifecycle.md), expiry or authorized deletion yields a minimized tombstone and explicit incomplete replay, never silent source refetch or successful equivalence. Reconstructing from Git fixtures creates a linked new run and cannot rewrite the original result.

### CA-FR-011 — Execute and score evaluation scenarios

**Owner:** Evaluation engineer (CA-ROLE-002)

<a id="ca-fr-011"></a>

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-008`, `CA-009`; `CA-RISK-006`, `CA-RISK-007`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-011)

The evaluation harness shall execute versioned scenario variants against declared ground truth and produce machine-readable and human-readable results.

**Acceptance criteria**

1. Results include failures and cannot be manually overwritten in place.
2. Threshold, fixture, ground-truth, and scorer versions are recorded.
3. Results separately report citation correctness, unsupported claims, false-cause outcome, abstention outcome, repeatability, and security-policy outcome.

### CA-FR-012 — Inspect and export investigation evidence

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-012"></a>

- **Priority:** Should
- **Verification:** Demonstration, Inspection
- **Trace:** `CA-001`, `CA-006`, `CA-008`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-012)

The system shall provide a human-inspectable representation of the timeline, provenance, hypothesis ledger, gaps, and evaluation result without requiring access to internal storage.

**Acceptance criteria**

1. Evidence identifiers and source provenance are visible.
2. Supporting, contradicting, and missing evidence are structurally distinct.
3. Export content identifies its run manifest and document/schema version.

### CA-FR-013 — Preserve deterministic results on model failure

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-013"></a>

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-007`, `CA-009`; `CA-NFR-003`, `CA-RISK-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-013)

The system shall preserve the deterministic evidence bundle and report synthesis as unavailable when the model is disabled, times out, returns invalid output, or fails.

**Acceptance criteria**

1. Model failure does not delete or mutate the evidence bundle.
2. The run is marked partial rather than successful synthesis.
3. Retry does not duplicate deterministic evidence records.

### CA-FR-014 — Enforce the Phase 1 read-only boundary

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-fr-014"></a>

- **Priority:** Must
- **Verification:** Inspection, Test
- **Trace:** `CA-004`, `CA-009`, `CA-010`; `CA-RISK-002`, `CA-RISK-005`; [complete decision/threat/test mapping](requirement-matrix.md#ca-fr-014)

The Phase 1 system shall not expose or invoke cluster mutation, production remediation, or general-purpose command-execution capabilities.

**Acceptance criteria**

1. Proposed Kubernetes permissions contain no create, update, patch, delete, or escalation verbs.
2. Malicious evidence cannot cause a write operation or create an executable action request.
3. Any recovery text is clearly labeled unexecuted guidance and is outside scoring for causal correctness unless separately specified.

## 8. Non-functional requirements

Every requirement in this section is `Draft`.

### CA-NFR-001 — Reproducibility

**Owner:** Evaluation engineer (CA-ROLE-002)

<a id="ca-nfr-001"></a>

**Priority:** Must | **Verification:** Test | **Trace:** `CA-002`, `CA-005`, `CA-008`, `CA-009`, `CA-010`; `CA-SCENARIO-001-A/D`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-001)

Fixtures, ground truth, run configuration, scoring configuration, and result provenance shall be versioned so that a reported result can be reproduced or its unavailable dependency can be identified.

**Acceptance criteria:** An identical offline fixture run produces the same deterministic bundle manifest and identifies every version needed to interpret score differences.

### CA-NFR-002 — Explainability and auditability

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-nfr-002"></a>

**Priority:** Must | **Verification:** Inspection, Demonstration | **Trace:** `CA-003`, `CA-005`, `CA-006`, `CA-009`, `CA-010`; `CA-SCENARIO-001-A/B`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-002)

The system shall make inclusion, exclusion, derivation, relationship, hypothesis status, and gap rationale inspectable.

**Acceptance criteria:** A reviewer can trace each supported claim to source evidence and each derived edge to its rule/version.

### CA-NFR-003 — Reliability and explicit partial failure

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-nfr-003"></a>

**Priority:** Must | **Verification:** Test | **Trace:** `CA-004`, `CA-007`, `CA-008`, `CA-009`, `CA-010`; `CA-SCENARIO-001-B/E`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-003)

Connector, storage, rule, scorer, and model failures shall surface as explicit failed or partial states rather than silent success.

**Acceptance criteria:** Fault-injection tests produce component-specific failure state and do not report a complete investigation.

### CA-NFR-004 — Data minimization

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-nfr-004"></a>

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-004`, `CA-007`, `CA-010`; `CA-RISK-005`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-004)

The system shall collect and transmit only evidence fields required by the declared scenario and configured analysis boundary.

**Acceptance criteria:** A field-level data inventory exists for each connector and a seeded out-of-scope canary is excluded or redacted as declared.

### CA-NFR-005 — Maintainability and separation of concerns

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-nfr-005"></a>

**Priority:** Must | **Verification:** Inspection | **Trace:** `CA-002`, `CA-005`, `CA-007`, `CA-008`, `CA-010`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-005)

Connector acquisition, normalization, deterministic reasoning, synthesis, scoring, and presentation contracts shall be separated and versioned.

**Acceptance criteria:** Architectural review can identify each boundary and its input/output contract without relying on implementation-specific hidden behavior.

### CA-NFR-006 — Observability of the evaluator

**Owner:** Evaluation engineer (CA-ROLE-002)

<a id="ca-nfr-006"></a>

**Priority:** Should | **Verification:** Test, Demonstration | **Trace:** `CA-008`, `CA-010`; `CA-SEC-008`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-006)

The prototype shall emit structured run state sufficient to diagnose which phase, connector, rule, or scorer failed without recording prohibited secrets or raw sensitive payloads.

**Acceptance criteria:** A forced connector and scorer failure can be distinguished from the run record while secret canaries remain absent.

### CA-NFR-007 — Portability of the evaluation corpus

**Owner:** Evaluation engineer (CA-ROLE-002)

<a id="ca-nfr-007"></a>

**Priority:** Should | **Verification:** Demonstration | **Trace:** `CA-008`, `CA-009`, `CA-010`; `CA-SCENARIO-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-007)

Scenario fixtures and scoring contracts should be runnable in a documented local or CI environment without dependence on customer infrastructure.

**Acceptance criteria:** `CA-SCENARIO-001` can be instantiated from versioned instructions and synthetic fixtures in the selected Phase 1 environment.

### CA-NFR-008 — Performance budget

**Owner:** Evaluation engineer (CA-ROLE-002)

<a id="ca-nfr-008"></a>

**Priority:** Should | **Verification:** Test, Analysis | **Trace:** `CA-008`, `CA-010`; `CA-DEC-007`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-008)

The system shall measure evidence-ingestion, deterministic-assembly, synthesis, and total run duration separately.

**Acceptance criteria:** The run report contains these measurements. Numeric pass/fail budgets remain `TBD-APPROVAL` and shall not be invented by implementation.

### CA-NFR-009 — Capacity and bounds

**Owner:** Evaluation engineer (CA-ROLE-002)

<a id="ca-nfr-009"></a>

**Priority:** Must | **Verification:** Test | **Trace:** `CA-004`, `CA-008`, `CA-010`; `CA-SEC-009`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-009)

Every connector and investigation run shall have configured time-window, payload-size, record-count, and retry bounds.

**Acceptance criteria:** Oversized/high-cardinality fixture tests terminate within configured bounds and report truncation or rejection explicitly.

### CA-NFR-010 — Compatibility and schema evolution

**Owner:** Architecture lead (CA-ROLE-007)

<a id="ca-nfr-010"></a>

**Priority:** Should | **Verification:** Test, Inspection | **Trace:** `CA-002`, `CA-008`, `CA-010`; `CA-SEC-007`; [complete decision/threat/test mapping](requirement-matrix.md#ca-nfr-010)

Evidence, run-manifest, hypothesis, and result schemas shall declare versions and document backward-compatibility or migration behavior.

**Acceptance criteria:** Unsupported schema versions fail explicitly; supported migrations preserve source provenance.

## 9. Security requirements

Every requirement in this section is `Draft` and traces to the STRIDE model.

### CA-SEC-001 — Least-privilege read access

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-001"></a>

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-004`, `CA-009`, `CA-010`; `CA-RISK-005`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-001)

Connectors shall use the minimum read permissions required for declared evidence and shall not share a credential with a write-capable component.

**Acceptance criteria:** A reviewed permission manifest contains only declared read operations, and negative tests demonstrate that create, update, patch, delete, exec, and privilege-escalation operations are denied.

### CA-SEC-002 — No mutation or arbitrary execution surface

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-002"></a>

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-004`, `CA-009`, `CA-010`; `CA-RISK-002`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-002)

Phase 1 shall not expose cluster mutation tools, shell/command tools, or a general-purpose tool dispatcher to model output.

**Acceptance criteria:** Tool inventory inspection finds no mutation or arbitrary-execution capability, and malicious-input tests produce no executable action or write attempt.

### CA-SEC-003 — Treat evidence as untrusted data

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-003"></a>

**Priority:** Must | **Verification:** Test | **Trace:** `CA-007`, `CA-009`, `CA-010`; `CA-RISK-002`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-003)

Logs, annotations, object fields, commit/deployment metadata, and connector responses shall be serialized and labeled as untrusted data across the synthesis boundary.

**Acceptance criteria:** The synthesis input contract distinguishes instructions from evidence data, and the malicious-log variant remains inert without altering policy or control flow.

### CA-SEC-004 — Validate model output

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-004"></a>

**Priority:** Must | **Verification:** Test | **Trace:** `CA-007`, `CA-009`, `CA-010`; `CA-RISK-001/002`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-004)

Model output shall be schema-validated, citation-validated, size-bounded, and treated as untrusted until deterministic checks complete.

**Acceptance criteria:** Invalid schema, nonexistent citations, oversized output, and prohibited action fields are rejected and recorded as validation failures.

### CA-SEC-005 — Protect secrets

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-005"></a>

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-004`, `CA-010`; `CA-RISK-005`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-005)

Credentials and secret values shall not be committed, included in fixtures, copied into model input, or written into ordinary run output.

**Acceptance criteria:** Secret scanning and seeded-canary tests detect committed or propagated secret material, while accepted run artifacts contain no canary value.

### CA-SEC-006 — Minimize and control model egress

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-006"></a>

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-007`, `CA-010`; `CA-RISK-005`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-006)

If an external model is used, the transmitted field set, redaction rules, provider, retention assumptions, and egress path shall be declared before the integration is enabled.

**Acceptance criteria:** With provider integration disabled, no model egress occurs. Before enablement, an approved data-flow record identifies provider, fields, redaction, region/route, and retention assumptions. Provider and policy selection remain `TBD-APPROVAL`.

### CA-SEC-007 — Evidence and ground-truth integrity

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-007"></a>

**Priority:** Must | **Verification:** Test, Inspection | **Trace:** `CA-002`, `CA-008`, `CA-009`, `CA-010`; `CA-RISK-007`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-007)

Run manifests shall record integrity data for fixtures, ground truth, rules, and scoring configuration so post-run changes are detectable.

**Acceptance criteria:** Changing any protected fixture, ground-truth, rule, or scorer input after the manifest is created causes an integrity mismatch on verification. Authorized expiry/deletion is distinguished by a manifest-linked tombstone; it is not scored as tampering, successful replay or evidence of absence. Test both states under the [lifecycle contract](evidence-lifecycle.md).

### CA-SEC-008 — Audit security-relevant events

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-008"></a>

**Priority:** Should | **Verification:** Test, Inspection | **Trace:** `CA-008`, `CA-010`; `CA-THREAT-R-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-008)

The system shall record connector authorization failure, validation rejection, policy denial, ground-truth/version mismatch, and model-output rejection without logging secrets.

**Acceptance criteria:** Each declared security event produces a typed, timestamped audit record with run correlation, while a seeded secret is absent from audit output.

### CA-SEC-009 — Bound untrusted input

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-009"></a>

**Priority:** Must | **Verification:** Test | **Trace:** `CA-004`, `CA-009`, `CA-010`; `CA-THREAT-D-001`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-009)

The system shall enforce configured byte, record, cardinality, time-window, and retry limits before untrusted inputs can exhaust the evaluation environment.

**Acceptance criteria:** Boundary tests at and above each configured limit demonstrate accepted, truncated, or rejected behavior without unbounded processing or silent data loss.

### CA-SEC-010 — Fail securely

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-010"></a>

**Priority:** Must | **Verification:** Test | **Trace:** `CA-007`, `CA-009`, `CA-010`; `CA-RISK-001/002/004`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-010)

Validation, authorization, citation, and policy failures shall fail closed for the affected capability and shall not be converted into a confirmed causal result.

**Acceptance criteria:** Forced failures produce denied/partial status, preserve available deterministic evidence, and never yield a confirmed root-cause result from the failed capability.

### CA-SEC-011 — Dependency and artifact integrity

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-011"></a>

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-008`, `CA-010`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-011)

Future implementation dependencies and container artifacts shall be pinned or otherwise reproducibly resolved, scanned under the approved SSDLC policy, and associated with build provenance before a Phase 1 implementation result is accepted.

**Acceptance criteria:** A future implementation result is ineligible for the Phase 1 gate unless dependency resolution, scan output, and artifact provenance are version-linked and reviewable.

### CA-SEC-012 — Separate result evidence from approval

**Owner:** Security reviewer (CA-ROLE-004)

<a id="ca-sec-012"></a>

**Priority:** Must | **Verification:** Inspection | **Trace:** `CA-010`; `CA-RISK-010`; [complete decision/threat/test mapping](requirement-matrix.md#ca-sec-012)

The system and repository workflow shall not represent a passing test, merged pull request, or closed issue as security approval, risk acceptance, or product-release authorization.

**Acceptance criteria:** Generated reports and repository templates distinguish verification result from approval status and require a separately named authority and approval record.

## 10. Phase 1 acceptance model

### 10.1 Required evidence for a requirement

A requirement may be proposed for approval only when:

1. Its identifier, statement, owner, priority, verification method, and trace links are complete.
2. Its acceptance criteria are measurable or explicitly carry an approved `TBD` disposition.
3. Applicable STRIDE threats and risks have been reviewed.
4. Verification evidence is versioned and links to the requirement and scenario/run manifest.
5. Known failures, exclusions, and residual risks are visible.

### 10.2 Proposed engineering gate

The five initial variants qualify the investigation harness only. The full evaluation gate requires the planned 8–12-scenario corpus, held-out cases, frozen ground truth and independent scoring review in [the corpus plan](scenarios/corpus-plan.md).

The historical 70% citation target is an unbenchmarked hypothesis. [CA-DEC-006](architecture/adr/CA-DEC-006.md) proposes stricter quality targets and separates citation-ID validity from factual support. All numeric quality metrics, weights and performance/capacity budgets remain provisional until benchmarked and explicitly approved before gate use. No target has been achieved or approved. Security requirements cannot be waived by aggregate accuracy.

### 10.3 Prohibited acceptance shortcuts

- Manual deletion of failed results.
- Changing ground truth or thresholds after seeing a run without versioning the change.
- Treating missing evidence as confirmation of a preferred cause.
- Treating narrative plausibility as verification.

## 11. CA-SCENARIO-001 verification baseline

The authoritative scenario definition is [CA-SCENARIO-001](scenarios/CA-SCENARIO-001.md).

| Variant | Purpose | Expected result | Primary requirements |
|---|---|---|---|
| `CA-SCENARIO-001-A` | Normal causal-evidence path | ConfigMap hypothesis is best supported; Deployment correlation is rejected as causal | `CA-FR-003–008`, `CA-NFR-001/002` |
| `CA-SCENARIO-001-B` | Missing ConfigMap evidence | Cause remains unresolved or abstained; Deployment is not promoted | `CA-FR-005/006/009`, `CA-NFR-003` |
| `CA-SCENARIO-001-C` | Malicious instruction-like log | Text remains inert evidence; no tool/policy action occurs | `CA-FR-007/014`, `CA-SEC-002–004/009/010` |
| `CA-SCENARIO-001-D` | Clock-skew/ambiguous ordering | Timestamp uncertainty and ambiguous ordering remain visible | `CA-FR-003/004`, `CA-RISK-003` |
| `CA-SCENARIO-001-E` | Model unavailable/invalid | Deterministic bundle persists; synthesis is partial/unavailable | `CA-FR-013`, `CA-NFR-003` |

## 12. Requirements traceability summary

The [complete 36-row matrix](requirement-matrix.md) is authoritative for requirement-to-issue, accountable role, decision, threat and planned-test edges. The [backlog register](traceability.md) supplies the exact reverse issue-to-requirement edges. The [STRIDE register](security/threat-model.md) supplies threat-to-risk-to-requirement-to-test edges, and the [risk register](security/risk-register.md) links back to these records. CA-FR-011 and CA-SEC-007 are explicitly verified in the scenario matrix. No planned test is claimed executed.

## 13. Decisions requiring owner approval

| Decision | Topic | Status |
|---|---|---|
| [CA-DEC-001](architecture/adr/CA-DEC-001.md) | System boundary and allowed sources | Proposed; no approval recorded |
| [CA-DEC-002](architecture/adr/CA-DEC-002.md) | Evidence store and provenance | Proposed; no approval recorded |
| [CA-DEC-003](architecture/adr/CA-DEC-003.md) | Timestamp provenance and skew | Proposed; no approval recorded |
| [CA-DEC-004](architecture/adr/CA-DEC-004.md) | Model boundary, provider and data egress | Proposed; no approval recorded |
| [CA-DEC-005](architecture/adr/CA-DEC-005.md) | Evidence lifecycle and replay after expiry | Proposed; no approval recorded |
| [CA-DEC-006](architecture/adr/CA-DEC-006.md) | Evaluation and security gates | Proposed; no approval recorded |
| [CA-DEC-007](architecture/adr/CA-DEC-007.md) | Performance and capacity budgets | Proposed; no approval recorded |
| [CA-DEC-008](architecture/adr/CA-DEC-008.md) | Accountability and approval authorities | Proposed; no approval recorded |

Product-owner approval is required for all eight proposals, with separate architecture, security and gate review as applicable. Named approval authorities remain unassigned. Proposed ownership is not approval.

## 14. Phase 1C proposed architecture

The [architecture package](architecture/phase1c/README.md) and [36-row design traceability](architecture/phase1c/traceability.md) refine the same stable requirements using the historical 0.2.0 draft and current 0.3.0 remediation. This reference does not alter requirement meaning or approve either baseline. All architecture decisions remain Proposed.
