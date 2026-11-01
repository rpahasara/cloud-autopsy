# CA-DEC-001 — System boundary and allowed sources

- **Status:** Proposed
- **Date:** 2026-11-01
- **Decision owner:** Architecture lead (role accountable for proposal; named incumbent pending CA-DEC-008)
- **Approval status:** No approval recorded; not accepted.
- **Required approval:** Product / requirements authority; architecture approver; security reviewer for security implications; evaluation/gate reviewer for benchmark and scoring implications. External access additionally requires the separate CA-DEC-004 data-egress and security approval.

## Proposed MVP position

One isolated kind cluster, one allowlisted namespace, synthetic fixtures only. Allow Kubernetes Events, Deployments, ReplicaSets, Pods and selected ConfigMap metadata/fixture values; allowlisted Prometheus and Loki queries; sanitized deployment/commit metadata. Exclude Secrets, node access, exec, cloud-provider APIs, admission control, production telemetry and arbitrary queries.

## Rationale

A small declared boundary makes completeness and permissions testable.

## Alternatives

Broader cluster collection increases disclosure and evaluation scope; fixture-only offline ingestion is a useful fallback but cannot qualify live connectors.

## Security implications

Read-only RBAC and field/query allowlists are mandatory; fixture setup is outside the collector identity.

## Review triggers

A new source, namespace, data classification, permission or production proposal.

## Traceability and validation

Requirements: [CA-FR-001](../../srs.md#ca-fr-001), [CA-FR-014](../../srs.md#ca-fr-014), [CA-SEC-001](../../srs.md#ca-sec-001), [CA-SEC-002](../../srs.md#ca-sec-002).

Backlog: [CA-002 / #2](https://github.com/rpahasara/cloud-autopsy/issues/2), [CA-004 / #4](https://github.com/rpahasara/cloud-autopsy/issues/4), [CA-009 / #9](https://github.com/rpahasara/cloud-autopsy/issues/9), [CA-010 / #10](https://github.com/rpahasara/cloud-autopsy/issues/10).

Planned verification and reverse links: [requirement matrix](../../requirement-matrix.md). No implementation, benchmark or security test has been run. Review rationale and alternatives, then collect the linked evidence under a separately authorized implementation plan.

## Approval record

No named approver, approval date or acceptance record exists. This proposal does not authorize implementation, external provider access, risk acceptance or release.

## Phase 1C design refinement — 2026-11-01

Specify namespace-only Role permissions, named ConfigMap checkpoint reads, separate fixture-setup identity and explicit list/watch continuity gaps. The collector never receives generalized write or query authority.

Detailed proposal: [Phase 1C collection](../phase1c/collection.md); [architecture package](../phase1c/README.md). These refinements are Proposed and add no approval or implementation authority. Review them when the existing triggers fire and before any future baseline sign-off.

## Phase 1D approval request — 2026-11-01

- **Product-owner disposition requested:** Confirm the single synthetic namespace/source allowlist, named ConfigMap checkpoint reads and read-only exclusions.
- **Provisional assumptions excluded from acceptance:** Exact source/API/image versions, query fields and workload consumption checkpoints need reviewed specification before collection work. Python/FastAPI remains a candidate orchestration stack; choose and review it explicitly before dependent application code.
- **Specialist reviewers required:** Architecture and Kubernetes/security reviewers.
- **Accepted terms:** None; no approval recorded.
- **Current disposition:** Proposed; awaiting named product and specialist review.
- **Approval record fields:** reviewed commit/digest, scoped accept/revise/defer/reject disposition, excluded assumptions, named authorities/reviewers and dates, independence/conflicts, evidence links, residual-risk disposition and review triggers. All fields remain unrecorded.

See the [complete approval matrix](../../reviews/phase1d/approvals.md), [consistency review](../../reviews/phase1d/consistency-review.md) and [formal completion checklist](../../reviews/phase1d/completion-checklist.md). A partial or deferred disposition is recorded separately and does not mark this entire ADR Accepted. No implementation or external access is authorized.
