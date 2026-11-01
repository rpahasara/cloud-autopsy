# Cloud Autopsy

> **Status:** Phase 1 planning draft. No requirements, architecture decisions, risks, or security controls are approved or signed off.

Cloud Autopsy is an AU4 Labs commercial product concept for deterministic, evidence-first incident reconstruction, initially evaluated against Kubernetes incidents. The product direction is read-only by default: assemble and time-align provenance-linked evidence first, then use constrained AI only to explain supported, contradicted, and unresolved hypotheses.

This repository is currently owned by the personal GitHub account `rpahasara` and is intended to transfer to the AU4 Labs organization later. It contains planning and SSDLC artifacts only—no production application code.

## Phase 1 objective

Demonstrate, with a reproducible evaluation corpus, that a deterministic evidence engine can reconstruct incident timelines, detect false-cause traps, expose telemetry gaps, and support calibrated abstention. Phase 1 targets a portfolio prototype and evidence for a later product-validation decision; it is not a production release.

All quality metrics and performance/capacity budgets are provisional until benchmarked and explicitly approved. The historical 70% target is a hypothesis; stricter review proposals are in CA-DEC-006. Five CA-SCENARIO-001 variants qualify the initial harness; the full gate needs 8–12 scenarios.

## Proposed Phase 1 gates

- Evidence-citation accuracy target: at least 70% on the versioned evaluation corpus.
- Correct abstention on designated missing-telemetry scenarios.
- No unsupported destructive action path; collection remains read-only.
- Prompt-injection and approval-bypass scenarios are explicitly tested.
- Gate results are measured and reviewed; this document does not claim they have been achieved.

## Planning index

- [Draft product charter](docs/product-charter.md)
- [Proposed Phase 1 SRS baseline (`0.3.0-draft`)](docs/srs.md)
- [Traceability and Phase 1 backlog](docs/traceability.md)
- [CA-SCENARIO-001](docs/scenarios/CA-SCENARIO-001.md)
- [Independent-review remediation](docs/reviews/phase1-remediation.md)
- [Requirement ownership and reverse mappings](docs/requirement-matrix.md)
- [Full evaluation corpus plan](docs/scenarios/corpus-plan.md)
- [Evidence lifecycle and replay](docs/evidence-lifecycle.md)
- [Phase 1 setup audit](docs/reviews/phase1-setup-audit.md)
- [Architecture context](docs/architecture/context.md)
- [ADR register and template](docs/architecture/adr/README.md)
- [STRIDE threat model](docs/security/threat-model.md)
- [Risk register](docs/security/risk-register.md)
- [Security practices](SECURITY.md)

## Governance

All artifacts are drafts until a named authorized reviewer records approval. Issue closure, pull-request merge, or repository transfer does not constitute product, security, legal, or architecture signoff.

## Phase 1C architecture proposal

[System architecture and security design](docs/architecture/phase1c/README.md) adds reviewable diagrams, data models, collector/RBAC, deterministic engine, AI boundary, API contracts, threat coverage and a proposed sign-off checklist. It is a separate draft stacked on PR #11, not an approved baseline or implementation.
