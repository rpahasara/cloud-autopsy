# Cloud Autopsy Software Requirements Specification — Phase 1

| Field | Value |
|---|---|
| Document ID | `CA-SRS-P1` |
| Version | `0.2.0-draft` |
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
- `CA-SCENARIO-001` and its normal, missing-evidence, clock-skew, malicious-input, and model-failure variants.
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
- The model provider, model-data policy, retention period, incident-window defaults, and performance targets are unresolved.

### 6.3 Hard Phase 1 constraints

- No production application code is authorized by this baseline review.
- No production write access or remediation execution is in scope.
- No claim may be presented as supported without traceable evidence.
- Missing or failed evidence retrieval shall not be interpreted as evidence of absence.

## 7. Functional requirements

Every requirement in this section is `Draft`.

### CA-FR-001 — Acquire scoped evidence

- **Priority:** Must
- **Verification:** Test, Inspection
- **Trace:** `CA-002`, `CA-004`, `CA-SCENARIO-001`

The system shall acquire only the Kubernetes and observability evidence sources enabled for the declared scenario and incident window.

**Acceptance criteria**

1. A run manifest identifies each enabled connector, query scope, and incident window.
2. Evidence outside the declared scope is not required for a passing run.
3. Connector success, partial success, empty response, and failure are distinguishable.

### CA-FR-002 — Normalize evidence with immutable identity

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-002`, `CA-RISK-001`, `CA-RISK-007`

The system shall normalize acquired observations into evidence nodes with stable identifiers while retaining a reference to the raw source representation.

**Acceptance criteria**

1. Each evidence node contains source type, source identifier, raw-reference integrity data, schema version, and ingestion metadata.
2. Raw and derived fields are distinguishable.
3. Re-ingesting the same fixture is idempotent or produces explicitly related duplicates.

### CA-FR-003 — Preserve timestamp provenance

- **Priority:** Must
- **Verification:** Test, Analysis
- **Trace:** `CA-003`, `CA-RISK-003`, `CA-SCENARIO-001`

The system shall retain event, observation, ingestion, and source clock-domain information without silently converting uncertain timestamps into a single authoritative time.

**Acceptance criteria**

1. Every timeline entry identifies timestamp type and source.
2. Known clock offset, resolution, and uncertainty are retained when available.
3. Ambiguous ordering is represented explicitly.

### CA-FR-004 — Assemble a deterministic evidence bundle

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-005`, `CA-RISK-001`, `CA-SCENARIO-001`

Given identical versioned inputs and configuration, the deterministic engine shall produce the same ordered evidence identifiers, relationships, and gap identifiers.

**Acceptance criteria**

1. Two identical runs produce equivalent deterministic bundle manifests.
2. Every derived relationship identifies its rule/version and input evidence identifiers.
3. Any permitted nondeterministic metadata is excluded from equivalence scoring or normalized.

### CA-FR-005 — Represent evidence gaps

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-005`, `CA-006`, `CA-RISK-004`, `CA-SCENARIO-001-B`

The system shall create explicit gap records for expected evidence that is missing, failed, out of scope, or unverifiable.

**Acceptance criteria**

1. A gap records its type, expected source, detection rule, and effect on affected hypotheses.
2. Connector failure is not reported as a clean negative observation.
3. The missing-ConfigMap variant cannot confirm the correlated Deployment as the root cause.

### CA-FR-006 — Maintain a hypothesis ledger

- **Priority:** Must
- **Verification:** Test, Demonstration
- **Trace:** `CA-006`, `CA-RISK-001`, `CA-RISK-004`, `CA-SCENARIO-001`

The system shall represent each candidate hypothesis with supporting, contradicting, missing, and not-evaluated evidence, plus a status and rationale.

**Acceptance criteria**

1. Supported status requires at least one valid supporting evidence link.
2. Contradicting evidence remains visible and cannot be discarded by narrative synthesis.
3. Insufficient or conflicting evidence produces unresolved or abstained status.

### CA-FR-007 — Produce constrained narrative synthesis

- **Priority:** Should
- **Verification:** Test, Inspection
- **Trace:** `CA-007`, `CA-RISK-001`, `CA-RISK-002`

When synthesis is enabled, the system shall provide the model only the structured evidence contract needed for the declared output and shall label telemetry as untrusted data.

**Acceptance criteria**

1. Synthesis can be disabled without preventing deterministic bundle evaluation.
2. Output conforms to a versioned schema.
3. Model instructions or tool requests originating in telemetry are not executed.

### CA-FR-008 — Validate claims and citations

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-007`, `CA-RISK-001`, `CA-SCENARIO-001`

The system shall validate factual claims against evidence identifiers before presenting them as supported.

**Acceptance criteria**

1. Nonexistent or out-of-bundle evidence identifiers are rejected.
2. Unsupported claims are counted and labeled; they are not silently accepted.
3. The evaluation output reports claim count, supported-claim count, unsupported-claim count, and citation-correctness score.

### CA-FR-009 — Support abstention

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-006`, `CA-009`, `CA-RISK-004`

The system shall support an explicit abstention outcome when evidence is insufficient, contradictory, or outside supported inference rules.

**Acceptance criteria**

1. Abstention includes a machine-readable reason and relevant evidence gaps.
2. Abstention does not generate a substitute root-cause claim.
3. Designated missing-evidence scenarios are scored for abstention correctness.

### CA-FR-010 — Replay an investigation

- **Priority:** Must
- **Verification:** Test, Demonstration
- **Trace:** `CA-002`, `CA-003`, `CA-005`, `CA-008`

The system shall persist a versioned run manifest sufficient to reconstruct or compare an investigation from retained Phase 1 fixtures.

**Acceptance criteria**

1. The manifest identifies connector, schema, rule, scenario, scoring, prompt, and model versions where applicable.
2. Replay does not require Kubernetes write permissions.
3. Differences between two run manifests and outputs can be enumerated.

### CA-FR-011 — Execute and score evaluation scenarios

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-008`, `CA-009`, `CA-RISK-006`, `CA-RISK-007`

The evaluation harness shall execute versioned scenario variants against declared ground truth and produce machine-readable and human-readable results.

**Acceptance criteria**

1. Results include failures and cannot be manually overwritten in place.
2. Threshold, fixture, ground-truth, and scorer versions are recorded.
3. Results separately report citation correctness, unsupported claims, false-cause outcome, abstention outcome, repeatability, and security-policy outcome.

### CA-FR-012 — Inspect and export investigation evidence

- **Priority:** Should
- **Verification:** Demonstration, Inspection
- **Trace:** `CA-001`, `CA-006`, `CA-008`

The system shall provide a human-inspectable representation of the timeline, provenance, hypothesis ledger, gaps, and evaluation result without requiring access to internal storage.

**Acceptance criteria**

1. Evidence identifiers and source provenance are visible.
2. Supporting, contradicting, and missing evidence are structurally distinct.
3. Export content identifies its run manifest and document/schema version.

### CA-FR-013 — Preserve deterministic results on model failure

- **Priority:** Must
- **Verification:** Test
- **Trace:** `CA-007`, `CA-NFR-003`, `CA-RISK-001`

The system shall preserve the deterministic evidence bundle and report synthesis as unavailable when the model is disabled, times out, returns invalid output, or fails.

**Acceptance criteria**

1. Model failure does not delete or mutate the evidence bundle.
2. The run is marked partial rather than successful synthesis.
3. Retry does not duplicate deterministic evidence records.

### CA-FR-014 — Enforce the Phase 1 read-only boundary

- **Priority:** Must
- **Verification:** Inspection, Test
- **Trace:** `CA-004`, `CA-010`, `CA-RISK-002`, `CA-RISK-005`

The Phase 1 system shall not expose or invoke cluster mutation, production remediation, or general-purpose command-execution capabilities.

**Acceptance criteria**

1. Proposed Kubernetes permissions contain no create, update, patch, delete, or escalation verbs.
2. Malicious evidence cannot cause a write operation or create an executable action request.
3. Any recovery text is clearly labeled unexecuted guidance and is outside scoring for causal correctness unless separately specified.

## 8. Non-functional requirements

Every requirement in this section is `Draft`.

### CA-NFR-001 — Reproducibility

**Priority:** Must | **Verification:** Test | **Trace:** `CA-002`, `CA-005`, `CA-008`, `CA-SCENARIO-001-A/D`

Fixtures, ground truth, run configuration, scoring configuration, and result provenance shall be versioned so that a reported result can be reproduced or its unavailable dependency can be identified.

**Acceptance criteria:** An identical offline fixture run produces the same deterministic bundle manifest and identifies every version needed to interpret score differences.

### CA-NFR-002 — Explainability and auditability

**Priority:** Must | **Verification:** Inspection, Demonstration | **Trace:** `CA-005`, `CA-006`, `CA-SCENARIO-001-A/B`

The system shall make inclusion, exclusion, derivation, relationship, hypothesis status, and gap rationale inspectable.

**Acceptance criteria:** A reviewer can trace each supported claim to source evidence and each derived edge to its rule/version.

### CA-NFR-003 — Reliability and explicit partial failure

**Priority:** Must | **Verification:** Test | **Trace:** `CA-004`, `CA-007`, `CA-008`, `CA-SCENARIO-001-B/E`

Connector, storage, rule, scorer, and model failures shall surface as explicit failed or partial states rather than silent success.

**Acceptance criteria:** Fault-injection tests produce component-specific failure state and do not report a complete investigation.

### CA-NFR-004 — Data minimization

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-004`, `CA-007`, `CA-010`, `CA-RISK-005`

The system shall collect and transmit only evidence fields required by the declared scenario and configured analysis boundary.

**Acceptance criteria:** A field-level data inventory exists for each connector and a seeded out-of-scope canary is excluded or redacted as declared.

### CA-NFR-005 — Maintainability and separation of concerns

**Priority:** Must | **Verification:** Inspection | **Trace:** `CA-002`, `CA-005`, `CA-007`, `CA-008`

Connector acquisition, normalization, deterministic reasoning, synthesis, scoring, and presentation contracts shall be separated and versioned.

**Acceptance criteria:** Architectural review can identify each boundary and its input/output contract without relying on implementation-specific hidden behavior.

### CA-NFR-006 — Observability of the evaluator

**Priority:** Should | **Verification:** Test, Demonstration | **Trace:** `CA-008`, `CA-010`, `CA-SEC-008`

The prototype shall emit structured run state sufficient to diagnose which phase, connector, rule, or scorer failed without recording prohibited secrets or raw sensitive payloads.

**Acceptance criteria:** A forced connector and scorer failure can be distinguished from the run record while secret canaries remain absent.

### CA-NFR-007 — Portability of the evaluation corpus

**Priority:** Should | **Verification:** Demonstration | **Trace:** `CA-008`, `CA-009`, `CA-SCENARIO-001`

Scenario fixtures and scoring contracts should be runnable in a documented local or CI environment without dependence on customer infrastructure.

**Acceptance criteria:** `CA-SCENARIO-001` can be instantiated from versioned instructions and synthetic fixtures in the selected Phase 1 environment.

### CA-NFR-008 — Performance budget

**Priority:** Should | **Verification:** Test, Analysis | **Trace:** `CA-008`, `CA-DEC-007`

The system shall measure evidence-ingestion, deterministic-assembly, synthesis, and total run duration separately.

**Acceptance criteria:** The run report contains these measurements. Numeric pass/fail budgets remain `TBD-APPROVAL` and shall not be invented by implementation.

### CA-NFR-009 — Capacity and bounds

**Priority:** Must | **Verification:** Test | **Trace:** `CA-004`, `CA-008`, `CA-010`, `CA-SEC-009`

Every connector and investigation run shall have configured time-window, payload-size, record-count, and retry bounds.

**Acceptance criteria:** Oversized/high-cardinality fixture tests terminate within configured bounds and report truncation or rejection explicitly.

### CA-NFR-010 — Compatibility and schema evolution

**Priority:** Should | **Verification:** Test, Inspection | **Trace:** `CA-002`, `CA-008`, `CA-SEC-007`

Evidence, run-manifest, hypothesis, and result schemas shall declare versions and document backward-compatibility or migration behavior.

**Acceptance criteria:** Unsupported schema versions fail explicitly; supported migrations preserve source provenance.

## 9. Security requirements

Every requirement in this section is `Draft` and traces to the STRIDE model.

### CA-SEC-001 — Least-privilege read access

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-004`, `CA-RISK-005`

Connectors shall use the minimum read permissions required for declared evidence and shall not share a credential with a write-capable component.

**Acceptance criteria:** A reviewed permission manifest contains only declared read operations, and negative tests demonstrate that create, update, patch, delete, exec, and privilege-escalation operations are denied.

### CA-SEC-002 — No mutation or arbitrary execution surface

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-004`, `CA-RISK-002`

Phase 1 shall not expose cluster mutation tools, shell/command tools, or a general-purpose tool dispatcher to model output.

**Acceptance criteria:** Tool inventory inspection finds no mutation or arbitrary-execution capability, and malicious-input tests produce no executable action or write attempt.

### CA-SEC-003 — Treat evidence as untrusted data

**Priority:** Must | **Verification:** Test | **Trace:** `CA-007`, `CA-RISK-002`

Logs, annotations, object fields, commit/deployment metadata, and connector responses shall be serialized and labeled as untrusted data across the synthesis boundary.

**Acceptance criteria:** The synthesis input contract distinguishes instructions from evidence data, and the malicious-log variant remains inert without altering policy or control flow.

### CA-SEC-004 — Validate model output

**Priority:** Must | **Verification:** Test | **Trace:** `CA-007`, `CA-RISK-001/002`

Model output shall be schema-validated, citation-validated, size-bounded, and treated as untrusted until deterministic checks complete.

**Acceptance criteria:** Invalid schema, nonexistent citations, oversized output, and prohibited action fields are rejected and recorded as validation failures.

### CA-SEC-005 — Protect secrets

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-RISK-005`

Credentials and secret values shall not be committed, included in fixtures, copied into model input, or written into ordinary run output.

**Acceptance criteria:** Secret scanning and seeded-canary tests detect committed or propagated secret material, while accepted run artifacts contain no canary value.

### CA-SEC-006 — Minimize and control model egress

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-RISK-005`

If an external model is used, the transmitted field set, redaction rules, provider, retention assumptions, and egress path shall be declared before the integration is enabled.

**Acceptance criteria:** With provider integration disabled, no model egress occurs. Before enablement, an approved data-flow record identifies provider, fields, redaction, region/route, and retention assumptions. Provider and policy selection remain `TBD-APPROVAL`.

### CA-SEC-007 — Evidence and ground-truth integrity

**Priority:** Must | **Verification:** Test, Inspection | **Trace:** `CA-RISK-007`

Run manifests shall record integrity data for fixtures, ground truth, rules, and scoring configuration so post-run changes are detectable.

**Acceptance criteria:** Changing any protected fixture, ground-truth, rule, or scorer input after the manifest is created causes an integrity mismatch on verification.

### CA-SEC-008 — Audit security-relevant events

**Priority:** Should | **Verification:** Test, Inspection | **Trace:** STRIDE repudiation

The system shall record connector authorization failure, validation rejection, policy denial, ground-truth/version mismatch, and model-output rejection without logging secrets.

**Acceptance criteria:** Each declared security event produces a typed, timestamped audit record with run correlation, while a seeded secret is absent from audit output.

### CA-SEC-009 — Bound untrusted input

**Priority:** Must | **Verification:** Test | **Trace:** STRIDE denial of service

The system shall enforce configured byte, record, cardinality, time-window, and retry limits before untrusted inputs can exhaust the evaluation environment.

**Acceptance criteria:** Boundary tests at and above each configured limit demonstrate accepted, truncated, or rejected behavior without unbounded processing or silent data loss.

### CA-SEC-010 — Fail securely

**Priority:** Must | **Verification:** Test | **Trace:** `CA-RISK-001/002/004`

Validation, authorization, citation, and policy failures shall fail closed for the affected capability and shall not be converted into a confirmed causal result.

**Acceptance criteria:** Forced failures produce denied/partial status, preserve available deterministic evidence, and never yield a confirmed root-cause result from the failed capability.

### CA-SEC-011 — Dependency and artifact integrity

**Priority:** Must | **Verification:** Inspection, Test | **Trace:** `CA-010`

Future implementation dependencies and container artifacts shall be pinned or otherwise reproducibly resolved, scanned under the approved SSDLC policy, and associated with build provenance before a Phase 1 implementation result is accepted.

**Acceptance criteria:** A future implementation result is ineligible for the Phase 1 gate unless dependency resolution, scan output, and artifact provenance are version-linked and reviewable.

### CA-SEC-012 — Separate result evidence from approval

**Priority:** Must | **Verification:** Inspection | **Trace:** `CA-RISK-010`

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

The charter currently proposes at least 70% evidence-citation accuracy and correct abstention on designated missing-evidence cases. The following remain approval decisions and are not silently added as pass criteria:

- Whether citation accuracy is micro-, macro-, claim-, or scenario-weighted.
- Required false-cause rejection rate and whether any false-cause selection is gate-blocking.
- Required abstention rate for designated gap scenarios.
- Maximum unsupported-claim count.
- Performance and capacity budgets.

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

| Backlog | Requirements | Scenario / evidence |
|---|---|---|
| `CA-001` / issue #1 | Document control, roles, all requirement classes | Baseline review and approval record |
| `CA-002` / issue #2 | `CA-FR-002/010`, `CA-NFR-001/010`, `CA-SEC-007` | Evidence schema and replay fixtures |
| `CA-003` / issue #3 | `CA-FR-003/004`, `CA-RISK-003` | `CA-SCENARIO-001-D` |
| `CA-004` / issue #4 | `CA-FR-001/014`, `CA-SEC-001/002/005/009` | RBAC and connector-boundary tests |
| `CA-005` / issue #5 | `CA-FR-004/005`, `CA-NFR-002/005` | Repeatability and gap fixtures |
| `CA-006` / issue #6 | `CA-FR-006/009/012` | Hypothesis and abstention fixtures |
| `CA-007` / issue #7 | `CA-FR-007/008/013`, `CA-SEC-003/004/006/010` | Citation, injection, and model-failure tests |
| `CA-008` / issue #8 | `CA-FR-010/011`, `CA-NFR-001/006–010`, `CA-SEC-007/008/011` | Versioned evaluation report |
| `CA-009` / issue #9 | Scenario-mapped requirements in section 11 | `CA-SCENARIO-001-A–E` |
| `CA-010` / issue #10 | `CA-FR-014`, all `CA-SEC-*`, gate controls | STRIDE, risk, and security-gate review |

Detailed backlog links are maintained in [traceability.md](traceability.md).

## 13. Decisions requiring owner approval

| Decision ID | Decision | Proposed/default position | Why approval is required |
|---|---|---|---|
| `CA-DEC-001` | Phase 1 system boundary and evidence sources | Single kind cluster; Kubernetes events/changes, Prometheus, Loki, deployment metadata | Determines connector scope and acceptance fixtures. |
| `CA-DEC-002` | Evidence store | PostgreSQL with JSONB and relational provenance edges | Consequential architecture and operational commitment. |
| `CA-DEC-003` | Timestamp and skew policy | Preserve source clocks; no hidden ordering; numeric tolerance TBD | Affects causal ordering and scenario scores. |
| `CA-DEC-004` | Model provider and data-egress policy | One provider behind a disabled-by-default constrained boundary; exact provider/redaction TBD | Determines privacy, retention, cost, and security controls. |
| `CA-DEC-005` | Evidence retention | Synthetic Phase 1 fixtures retained in Git; generated runs retained for a defined TBD period | Determines data lifecycle and storage requirements. |
| `CA-DEC-006` | Engineering gate metrics | Retain 70% citation target; define false-cause, abstention, unsupported-claim, and weighting rules | Prevents post-result threshold selection. |
| `CA-DEC-007` | Performance and capacity budgets | Measure first; numeric budgets TBD | Avoids fabricated targets while preserving measurability. |
| `CA-DEC-008` | Requirement and risk approval authority | Name product, security, and architecture approvers before baseline approval | Required for valid signoff and change control. |

No decision above is approved by this draft.
