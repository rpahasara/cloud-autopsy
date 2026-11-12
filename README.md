# Cloud Autopsy

> **Status (2026-11-11):** synthetic-only development foundation. The repository has a frozen offline prototype and pre-gate implementations of the evidence contracts, a PostgreSQL store, a deterministic investigation engine, verify-on-read results, a loopback read-only API and a local dashboard. Everything runs on synthetic fixtures only. No requirement, architecture decision (CA-DEC-001…008), risk, security control or gate (D, I or E) is approved or signed off. Nothing here is production-ready.

Cloud Autopsy is an AU4 Labs commercial product concept for deterministic, evidence-first incident reconstruction. It is initially evaluated against Kubernetes incidents.

The product direction is read-only by default. Cloud Autopsy first assembles and time-aligns evidence that is linked to its provenance. Constrained AI may then be used only to explain which hypotheses the evidence supports, contradicts or leaves unresolved. No AI component is implemented.

This repository is currently owned by the personal GitHub account `rpahasara` and is intended to transfer to the AU4 Labs organization later. It contains planning and SSDLC artifacts, plus the synthetic-only implementation described below.

## What is implemented (synthetic only, pre-gate)

The implementation was built under the product owner's [pre-gate development authorization](docs/phase2/ca-p2-003/ca-p2-003b-1.md), which is synthetic-only. It is not a gate approval.

| Area | Where | Record |
|---|---|---|
| Frozen offline prototype (CA-SPIKE-001, commit `c21b50d`) | `prototype/` | [CA-SPIKE-001](docs/spikes/CA-SPIKE-001.md) |
| Dependency, licensing and SSDLC foundation; offline supply-chain checks | `supply-chain/`, `tools/supply_chain/` | [CA-P2-001](docs/phase2/ca-p2-001/README.md) |
| Provisional contracts: canonical JSON, time intervals, evidence identity, run plan, batches, frozen input | `src/cloud_autopsy/contracts/` | [CA-P2-002a](docs/phase2/ca-p2-002/ca-p2-002a.md) to [002d](docs/phase2/ca-p2-002/ca-p2-002d.md) |
| PostgreSQL schema, roles, ingest and atomic seal (disposable, loopback-only container) | `src/cloud_autopsy/db/` | [CA-P2-003](docs/phase2/ca-p2-003/README.md), [003b-1](docs/phase2/ca-p2-003/ca-p2-003b-1.md) |
| Deterministic investigation engine (one mechanism catalog) | `src/cloud_autopsy/engine/` | [CA-P2-005a](docs/phase2/ca-p2-005/ca-p2-005a.md) |
| Immutable results with verify-on-read replay | `src/cloud_autopsy/db/results.py` | [CA-P2-006a](docs/phase2/ca-p2-006/ca-p2-006a.md) |
| Loopback read-only API with per-run grants | `src/cloud_autopsy/api/` | [CA-P2-006b](docs/phase2/ca-p2-006/ca-p2-006b.md) |
| Local dashboard and Home overview, including a labelled synthetic preview | `src/cloud_autopsy/api/ui/`, `tools/dashboard_preview.py` | [CA-P2-006c](docs/phase2/ca-p2-006/ca-p2-006c.md), [006d](docs/phase2/ca-p2-006/ca-p2-006d.md) |
| Creating investigations from evidence bundles (offline, or database-verified on a disposable database) | `src/cloud_autopsy/app/bundle.py`, `create.py`, `tools/create_investigation.py`, `examples/bundles/` | [CA-P2-004a](docs/phase2/ca-p2-004/ca-p2-004a.md) |
| Run lifecycle: failed seals end `failed`, bounded recovery after lease expiry, fenced stale workers, run-scoped status in the API and dashboard | `src/cloud_autopsy/db/seal.py`, `status.py`, migration `0005`, `api/grants.py`, `api/service.py` | [CA-P2-004b](docs/phase2/ca-p2-004/ca-p2-004b.md) |
| Offline adapter for recorded Kubernetes responses (Pods, ReplicaSets, Deployment rollouts; Events and ConfigMaps counted as `unsupported_conversion`) | `src/cloud_autopsy/app/k8s_recording.py`, `tools/convert_k8s_recording.py`, `examples/k8s-recordings/` | [CA-P2-004c](docs/phase2/ca-p2-004/ca-p2-004c.md) |
| Observation kinds 0.2 (`k8s_event`, `configmap_metadata`) beside 0.1; migration `0006`; snapshot-only coverage for recordings | `src/cloud_autopsy/contracts/evidence.py`, `db/migrations/0006_kind_registry_versions.sql`, `app/k8s_recording.py` | [CA-P2-004d](docs/phase2/ca-p2-004/ca-p2-004d.md) |
| Read-only Kubernetes collector (stdlib HTTPS, allowlisted GET lists, sanitizing projection, recording 0.3, fail-closed `partial` batches); disposable `kind` CI job with negative RBAC tests | `src/cloud_autopsy/collector/`, `tools/collect_k8s.py`, `deploy/kind/` | [CA-P2-004e](docs/phase2/ca-p2-004/ca-p2-004e.md) |
| List + watch collection with consistent-read progress probes: coverage verified only between a list and a proven probe, every other period a gap; recording 0.4 (facts only, replay-checked); batch 0.2, observation kinds 0.3, contract profile 3, migration `0008`; optional `collector-watch-kind` CI job | `src/cloud_autopsy/collector/watch.py`, `app/k8s_watch_recording.py`, `contracts/resourceversion.py`, `db/migrations/0008_watch_contract_versions.sql`, `deploy/kind/rbac-watch.yaml` | [CA-P2-004f](docs/phase2/ca-p2-004/ca-p2-004f.md) |

**Not implemented:**
- collectors for any real, shared or existing cluster (CA-P2-004e and 004f collect only from disposable `kind` clusters inside CI);
- live evidence acquisition: investigations can be created only from synthetic evidence bundles and synthetic recorded Kubernetes responses;
- export, retention, purge or audit logging;
- AI synthesis;
- an independent evaluation scorer or held-out truth (CA-P2-007, and the separate [held-out kit](https://github.com/rpahasara/cloud-autopsy/pull/14), PR #14);
- production authentication, TLS and deployment.

Backlog status: [Phase 2 backlog](docs/reviews/phase1d/phase2-backlog.md#status).

**Try it locally:**
- **Synthetic preview** (no database; results labelled "not verified"): `python -I tools/dashboard_preview.py`
- **Create from bundles:** `python -I tools/create_investigation.py --offline examples/bundles/*`. Add `--serve` with the hash-locked interpreter to create database-verified runs and open them in the dashboard ([CA-P2-004a](docs/phase2/ca-p2-004/ca-p2-004a.md)).
- **Database-verified demos** (Docker, disposable database): `tools/investigation_demo.py` and `tools/api_demo.py`, run with the hash-locked interpreter described in [db/README.md](db/README.md).

## Phase 1 objective

Demonstrate, with a reproducible evaluation corpus, that a deterministic evidence engine can:
- reconstruct incident timelines;
- detect false-cause traps;
- expose telemetry gaps;
- support calibrated abstention.

Phase 1 targets a portfolio prototype and evidence for a later product-validation decision. It is not a production release.

All quality metrics and performance or capacity budgets are provisional until benchmarked and explicitly approved. The historical 70% target is a hypothesis; stricter review proposals are in CA-DEC-006. Five CA-SCENARIO-001 variants qualify the initial harness; the full gate needs 8–12 scenarios.

## Proposed Phase 1 gates

- Historical, unbenchmarked hypothesis: at least 70% evidence-citation accuracy. The final metric and threshold disposition remains Proposed under CA-DEC-006.
- Correct abstention on designated missing-telemetry scenarios.
- No unsupported destructive action path; collection remains read-only.
- Prompt-injection and approval-bypass scenarios are explicitly tested.
- Gate results are measured and reviewed. This document does not claim they have been achieved.

## Planning index

- [Draft product charter](docs/product-charter.md)
- [Proposed Phase 1 SRS baseline (`0.4.0-draft`)](docs/srs.md)
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

All artifacts are drafts until a named authorized reviewer records approval. Issue closure, pull-request merge, integration into `main` or repository transfer does not constitute product, security, legal or architecture sign-off.

The [integration record](docs/phase2/integration.md) describes how the draft PR chain is consolidated into `main`. It is a solo product-owner decision, not a specialist approval or a gate.

## Phase 1C architecture proposal

[System architecture and security design](docs/architecture/phase1c/README.md) adds:
- reviewable diagrams and data models;
- collector and RBAC design;
- the deterministic engine and the AI boundary;
- API contracts and threat coverage;
- a proposed sign-off checklist.

It is a draft design, not an approved baseline.

## Phase 1D final design review

[Approval and implementation-readiness package](docs/reviews/phase1d/README.md) provides blockers, eight scoped ADR requests, independent reviewers, source-backed technology research, differentiation, benchmark plans, formal completion gates and a proposed Phase 2 backlog. Readiness for Gate D, I or E remains blocked pending approval. Synthetic-only implementation proceeded under the pre-gate authorization above.

## Phase 2 (pre-gate, synthetic only)

Records, in order:
- [CA-P2-001 dependency, licensing and SSDLC foundation](docs/phase2/ca-p2-001/README.md)
- CA-P2-002a–d contracts:
  - [002a](docs/phase2/ca-p2-002/ca-p2-002a.md)
  - [002b](docs/phase2/ca-p2-002/ca-p2-002b.md)
  - [002c](docs/phase2/ca-p2-002/ca-p2-002c.md)
  - [002d](docs/phase2/ca-p2-002/ca-p2-002d.md)
- [CA-P2-003 PostgreSQL design](docs/phase2/ca-p2-003/README.md) and [003b-1 implementation](docs/phase2/ca-p2-003/ca-p2-003b-1.md)
- [CA-P2-005a end-to-end investigation](docs/phase2/ca-p2-005/ca-p2-005a.md)
- CA-P2-006a–d:
  - [006a results](docs/phase2/ca-p2-006/ca-p2-006a.md)
  - [006b API](docs/phase2/ca-p2-006/ca-p2-006b.md)
  - [006c dashboard](docs/phase2/ca-p2-006/ca-p2-006c.md)
  - [006d Home](docs/phase2/ca-p2-006/ca-p2-006d.md)

Nothing in these records is approved. Gate D, Gate I, Gate E and all CA-DEC decisions remain open.
