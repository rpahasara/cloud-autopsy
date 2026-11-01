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
