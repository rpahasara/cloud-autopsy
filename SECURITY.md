# Security Practices (Phase 1 Draft)

Cloud Autopsy is pre-production planning work. It has no claimed certification, production security approval, SLA, or customer-data authorization.

## Phase 1 security principles

- Read-only and least-privilege access.
- No autonomous remediation or production write tools.
- External evidence and model output are untrusted.
- Evidence provenance and raw/derived separation.
- Data minimization; synthetic fixtures by default.
- Explicit gaps and abstention over fabricated certainty.
- Security requirements and tests are traceable to issues and scenarios.

## SSDLC expectations

- Requirements and threat-model review before implementation.
- ADRs for consequential security/architecture choices.
- Peer review for changes to trust boundaries, scoring, ground truth, or access.
- Dependency pinning/review and secret scanning before implementation artifacts land.
- Tests for prompt injection, citation forgery, approval bypass, oversized input, and connector partial failure.
- Measured gate results retained with versions; failures are reported.

## Secrets and data

Do not commit credentials, customer telemetry, personal data, or production exports. Phase 1 should use synthetic or explicitly authorized sanitized fixtures. A formal disclosure channel will be established before public release or external testing; do not claim one exists yet.

## Vulnerability reporting

Until a formal process is approved, use a private GitHub security advisory if enabled for this private repository or contact the repository owner privately. Do not place sensitive exploit details in public issues.

## No signoff by merge

Merging this file or closing related issues does not constitute security approval or risk acceptance.
