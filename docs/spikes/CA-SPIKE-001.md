# CA-SPIKE-001 — Offline deterministic investigation spike (CA-SCENARIO-001)

| Field | Value |
|---|---|
| Status | Authorized exploratory spike — **not** production implementation, Phase 1 approval or gate evidence |
| Authorized by | Product owner (repository owner), in session instruction dated 2026-11-01 |
| Branch | Local `spike/ca-scenario-001`, based on PR #12 head `554d32b` |
| ADRs | CA-DEC-001 through CA-DEC-008 remain **Proposed** |
| Gate eligibility | None. Results cannot be used for Gate D, I or E (CA-SEC-011/012) |

## Scope

In scope: local, offline, synthetic-only engineering experiment under `prototype/` (entry point [`prototype/cli.py`](../../prototype/cli.py)) — versioned fixtures, canonicalization, evidence/time model, deterministic assembler, hypothesis ledger, naive temporal-correlation baseline, synthesis-boundary validator (stub responses only), independent scorer, replay/integrity tests and CLI.

Excluded: Kubernetes or any cluster access, production or customer data, network egress of incident data, external or local model calls, PostgreSQL deployment, API server, GitHub pushes/merges, changes to PR #11/#12 branches, Git commits without separate owner authorization.

## Spike-provisional decisions (not ADR acceptance)

- Python 3.13 standard library only; `unittest` for tests. No third-party dependencies to inventory.
- File-based storage adapter. The evidence model is storage-independent and mirrors the [logical relations](../architecture/phase1c/data-model.md) to keep a PostgreSQL migration path.
- Canonicalization `ca-canon/0.1-spike`: UTF-8 JSON, code-point-sorted keys, no insignificant whitespace, floats/NaN/duplicate keys rejected (decimals carried as strings), no Unicode normalization (raw strings preserved).
- Clock rule `ca-time/0.1-spike`: only fixture-declared bounds produce intervals; unknown bounds are unordered; A precedes B only when A's upper bound is strictly below B's lower bound.
- ConfigMap hot-reload mechanism, event ordering and ground truth are defined in the [spike fixture specification](../../prototype/fixtures/ca-scenario-001/README.md). That correction supersedes the open "configuration-consumption mechanism" question in CA-SCENARIO-001 §11 **for this spike only**; the scenario document is unchanged and still needs review.
- Exploratory performance objective: the full demo completes within five minutes on the declared local workload. This is not a product SLA or CA-DEC-007 budget.
- Scores are raw counts and denominators. No pass/fail threshold is set (CA-DEC-006, CA-NFR-008).

## Ground-truth custody

Ground truth was written and its SHA-256 digest pinned in [`prototype/ca_eval/truth-pins.json`](../../prototype/ca_eval/truth-pins.json) **before** any engine code existed. Without a Git commit, ordering is evidenced only by this record and file-system history; it is not independently verifiable. The same author wrote fixtures, truth, engine and scorer, so independence required by CA-DEC-006/008 is **not** met; results are self-evaluated.

Pinned truth digest (`prototype/truth/ca-scenario-001/ground-truth.json`, raw bytes): `d84051c6bfbc619d46efd4819ec1c31b13ce71e8883b69f656a0b600deffebe6`

## Known limitations

- One scenario family, five variants, self-authored fixtures/truth/rules: the engine-versus-baseline comparison shows the designed trap works, not general causal accuracy. The mechanism catalog maps only `pool.maxConnections` → `POOL_EXHAUSTED`.
- Engine citation-ID validity is trivially complete because the engine only cites sealed evidence; semantic support is checked only through rule predicates.
- No live connectors, RBAC, network policy, PostgreSQL roles, lifecycle expiry/deletion states or local model are exercised.
- Pairwise ordering excludes metric samples to stay bounded; it is quadratic in non-metric evidence.
- Timing is one run on the author's workstation; no warmups, repetitions or p95.

## Reproduce

```
make demo            # or: python prototype/cli.py demo
make test            # or: python -m unittest discover -s prototype/tests -t prototype
```
