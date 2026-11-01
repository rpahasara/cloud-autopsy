# STRIDE Threat Model — Phase 1 (Draft)

**Status:** Initial placeholder analysis; not a security approval.

## Assets

- Evidence integrity and provenance.
- Evaluation ground truth and score integrity.
- Cluster/observability credentials, even when read-only.
- Investigation records and potentially sensitive telemetry.
- Tool-policy boundary and human trust in conclusions.

## Trust boundaries

See [architecture context](../architecture/context.md). External telemetry, Kubernetes objects, logs, annotations, commit/deployment metadata, model responses, and scenario content are untrusted inputs.

## STRIDE register

| Category | Example threat | Proposed Phase 1 treatment | Validation idea |
|---|---|---|---|
| Spoofing | Forged source identity or reused evidence identifier | Authenticated connectors; source-qualified immutable IDs | Inject conflicting IDs/sources |
| Tampering | Evidence or ground truth altered to improve scores | Version control; hashes/version metadata; raw-vs-derived separation | Modify fixture after run and detect mismatch |
| Repudiation | Cannot reconstruct which rule/model produced a claim | Versioned run manifest and provenance edges | Replay from manifest |
| Information disclosure | Secrets/PII copied from logs to storage/model | Data minimization, redaction boundary, fixture-only Phase 1 | Seed canary secret and assert exclusion |
| Denial of service | Oversized/high-cardinality telemetry exhausts collector/store | Scope, quotas, size limits, bounded windows | Oversize and cardinality tests |
| Elevation of privilege | Prompt injection induces cluster write or policy bypass | No write tools; read-only RBAC; treat telemetry as data; output validation | Malicious-log and crafted-tool-response tests |

## Abuse cases requiring explicit tests

- Log text says to ignore policy and execute a destructive command.
- Kubernetes annotation impersonates trusted product metadata.
- Model returns citations to nonexistent evidence IDs.
- Connector omits an expected source but reports success.
- Correlated Deployment is promoted as root cause after causal evidence is removed.
- Scenario author changes ground truth after observing results.

## Open questions

- Credential storage and rotation mechanism.
- Exact redaction and retention rules.
- Network egress policy for any model provider.
- Evidence signing/tamper-evidence requirements beyond Phase 1.
- Dependency and container supply-chain baseline.

