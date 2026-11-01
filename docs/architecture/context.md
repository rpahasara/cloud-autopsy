# Architecture Context (Draft)

No architecture decision in this document is approved. The components below define boundaries for Phase 1 discussion.

## System context

**Actors:** on-call/platform engineer; scenario/evaluation author; authorized reviewer.  
**External systems:** demo Kubernetes cluster, metrics/log sources, deployment metadata source, optional model provider.  
**System of interest:** Cloud Autopsy Phase 1 prototype.

## Candidate logical flow

1. Read-only connectors collect scoped evidence and timestamp provenance.
2. Normalization produces immutable evidence nodes while retaining raw references.
3. A deterministic assembler selects and relates evidence for an incident window.
4. A hypothesis ledger records support, contradiction, gaps, and abstention.
5. A constrained synthesis boundary receives structured evidence, not tool authority.
6. A replay/evaluation layer compares results with versioned scenario ground truth.

## Candidate component boundaries

- **Connector boundary:** retrieval only; external payloads are untrusted.
- **Evidence store:** raw/normalized evidence, provenance, versions, investigation state.
- **Deterministic engine:** time alignment, graph/rule evaluation, gap production.
- **Synthesis boundary:** narrative generation and citations; no cluster write tools.
- **Evaluation harness:** scenario execution, ground truth, security tests, scoring.
- **Presentation boundary:** replay and evidence inspection; UI technology undecided.

## Trust boundaries

- Demo cluster and telemetry → connector: attacker-controlled content possible.
- Connector → evidence store: validate types, sizes, identifiers, and provenance.
- Evidence engine → model provider: minimize/redact data and serialize as data.
- Model output → product: validate schema/citations; never treat as authority.
- Human reviewer → any future action: outside Phase 1 execution scope.

## Candidate deployment assumptions

- Self-hosted/local evaluation environment.
- PostgreSQL/JSONB as initial storage hypothesis.
- Python/FastAPI as initial service hypothesis.
- Prometheus/Grafana/Loki and kind as demo-stack hypotheses.

Each assumption requires evaluation and, if adopted as consequential, an ADR.


## Proposed decision records

[CA-DEC-001 through CA-DEC-008](adr/README.md) now capture these hypotheses, their alternatives and review triggers. The [lifecycle contract](../evidence-lifecycle.md) defines expiry and replay. All remain proposed; external AI-provider access requires separate data-egress and security approval.

## Phase 1C detailed design

The [architecture package](phase1c/README.md) refines this context with [diagrams and responsibilities](phase1c/diagrams.md), data models, security boundaries and integration contracts. All components and decisions remain Proposed.
