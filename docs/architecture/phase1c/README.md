# Phase 1C — System architecture and security design (Proposed)

Document ID: CA-ARCH-P1C. Version: 0.1.0-draft. Date: 2026-11-01. Owner: Architecture lead. Approval status: no approval recorded. This package specifies a future evaluation prototype; it contains no application implementation, database migration or deployable infrastructure.

## Baseline and review boundary

This architecture is a separate draft change stacked on [draft PR #11](https://github.com/rpahasara/cloud-autopsy/pull/11), pinned at `238cc2afbdb3443ff7ae7de655077b73212cfa40`. The requested SRS `0.2.0-draft` is preserved in Git at `380c787`; PR #11 now contains the remediated [SRS 0.3.0-draft](../../srs.md), with the same 36 stable requirement IDs. Phase 1C uses those IDs and the ownership, lifecycle, traceability and corpus clarifications from remediation. It does not revert to the known gaps in 0.2.0 or approve either version. Any future baseline change requires impact review of this package.

The draft architecture PR targets PR #11's `docs/phase1-srs-baseline` branch, so its diff contains architecture work only. After PR #11 is explicitly resolved, the architecture PR can be retargeted to main and revalidated; neither PR is authorized to merge here.

## Architecture package

| Artifact | Purpose |
|---|---|
| [Diagrams and responsibility specification](diagrams.md) | System context, components, detailed collection/model/deletion flows and trust boundaries |
| [PostgreSQL logical model](data-model.md) | Evidence, provenance, investigations, manifests, hypotheses, claims and lifecycle constraints |
| [Read-only collection design](collection.md) | Source contracts, namespace RBAC, continuity gaps, credentials and network isolation |
| [Deterministic engine](engine.md) | Canonicalization, uncertainty, gap semantics, causal constraints and replay |
| [AI synthesis boundary](ai.md) | Prompt isolation, claim validation, provider isolation and separately approved egress |
| [API and integration contracts](api.md) | Initial endpoints, typed envelopes, authorization, idempotency and failure semantics |
| [Security coverage and verification requirements](security.md) | STRIDE across flows, mitigations, residual risks and planned security tests |
| [Architecture traceability](traceability.md) | Exact coverage of all 36 requirements and relevant Phase 1 issues |
| [Questions and proposed sign-off checklist](signoff.md) | Explicit unresolved decisions, review evidence and authority prerequisites |
| [Documentation verification](verification.md) | Structural checks, diagram rendering and the limits of this verification |

## Deployment proposal

One isolated synthetic kind environment; namespace-scoped collectors; a local control API and deterministic worker; one PostgreSQL instance; separate optional local synthesis process. Logical modules may share a service process where they share trust, but the credentialed collector and untrusted model adapter are separate security identities. No message broker, graph database, workflow service, object store or production control plane is proposed. Python/FastAPI remains a candidate, not a newly accepted stack decision. Component contracts do not depend on that framework.

The API proposes authenticated local access through loopback or a protected local socket. No unauthenticated listener, remote ingress, customer data or multi-tenancy is permitted. Host-admin compromise remains outside the protection offered by the prototype. A networked deployment would require a new authentication, encryption and threat-boundary review.

All CA-DEC-001 through CA-DEC-008 remain Proposed. Quality metrics, clock heuristics and performance/capacity budgets remain provisional until benchmarked and approved. Five initial scenario variants qualify the harness; the full gate needs the planned 8–12-scenario corpus. External AI-provider access remains disabled pending a separate data-egress and security approval.
