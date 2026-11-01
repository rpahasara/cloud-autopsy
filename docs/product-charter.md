# Product Charter — Phase 1 (Draft)

**Document status:** Draft / not approved  
**Product:** Cloud Autopsy  
**Intended future owner:** AU4 Labs  
**Current repository owner:** `rpahasara`

## Problem statement

On-call engineers often spend the first 45–90 minutes of an incident collecting and aligning fragmented Kubernetes events, deployment history, metrics, and logs before they can test a causal hypothesis. Existing AI-first approaches can produce plausible narratives without calibrated causal support.

## Product hypothesis

A read-only, deterministic evidence engine that produces a replayable, provenance-linked incident timeline—and constrains any AI synthesis to that evidence—can reduce evidence-collection effort while improving auditability and trust.

## Phase 1 users and stakeholders

- Primary user hypothesis: platform engineers and de facto SREs in small Kubernetes teams.
- Economic buyer hypothesis: CTO, VP Engineering, or Head of Platform.
- Internal stakeholders: product, engineering, security, and future AU4 Labs governance.
- These are hypotheses to validate, not confirmed market facts.

## In scope

- One local/demo Kubernetes environment (for example, kind).
- Kubernetes changes/events, Prometheus metrics, Loki logs, and deployment metadata as candidate evidence sources.
- Versioned evidence schema and timestamp provenance.
- Deterministic evidence assembly and hypothesis support/contradiction/gap accounting.
- Constrained narrative synthesis with evidence citations and abstention.
- Evaluation corpus with 8–12 scenarios; Phase 1 starts with `CA-SCENARIO-001`.
- Security tests for prompt injection and approval bypass.

## Out of scope

- Production deployment, customer telemetry, or a production control plane.
- Autonomous remediation or write access to a cluster.
- Multi-tenancy, billing, SOC 2 claims, or production SLAs.
- Multi-cloud breadth, generalized AIOps, or a polished commercial UI.
- Model routing, graph database adoption, or durable workflow infrastructure unless justified by an approved ADR.

## Proposed success measures

- At least 70% evidence-citation accuracy across the agreed corpus.
- Correct abstention on missing-evidence cases.
- Measured false-cause rejection on deliberately correlated-but-noncausal changes.
- Reproducible scenario execution and machine-readable ground truth.
- Demonstrated containment of malicious telemetry text with no tool-policy bypass.

## Decision gates

1. **Engineering gate:** corpus results meet documented thresholds without hiding failure cases.
2. **Product-validation gate:** at least 3 of 15 discovery participants request a pilot proposal and at least 1 signs a paid pilot.
3. **Commercial-readiness gate:** security, data-handling, access, escalation, and contract artifacts exist before customer access.

No gate is currently passed or approved.

## Constraints and principles

- Evidence first, AI second.
- Read-only by default and least privilege.
- Absence of evidence is represented explicitly.
- Every factual claim must link to evidence or be labeled unsupported/unresolved.
- Reproducibility takes priority over demo polish.

