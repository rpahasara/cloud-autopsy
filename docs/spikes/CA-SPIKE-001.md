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

The PR #13 counterexample truths (`cx-deploy-cause`, `cx-benign`) were written and pinned after the review but before the engine changes that evaluate them; the pre-change engine abstained on the Deployment cause. They are developer-authored regression cases, not independent or held-out evaluation.

## PR #13 review remediation (engine `0.2`)

| Finding | Change |
|---|---|
| P0 demo `rmtree` | Output must be a strict subdirectory of `prototype/out`, contain no symlink/junction, and carry a demo-written sentinel before deletion |
| P1 replay derived fields | Replay compares whole persisted evidence records, the baseline and the synthesis input digest with a fresh recomputation from authenticated retained inputs |
| P1 synthesis truth | Status renamed `structurally_validated`; non-empty citations must equal the cited assertions' evidence; factual kinds need satisfied assertions; prose stays `text_untrusted`, only a ledger-rendered `supported_fact` is exposed, and the scorer counts model prose as unsupported |
| P1 Deployment cause | Catalog maps typed rollout `field_changes`; new `cx-deploy-cause` and `cx-benign` counterexamples |
| P1 fail-open gaps/time | `partial` coverage and duplicate query outcomes create gaps; consumption requires a strictly later log, otherwise a recorded chronology rejection |
| P2 joins | One hypothesis per specific change; joins scoped by namespace and pod UID; same-name identities with different UIDs are reported and excluded |

### Re-review follow-up (scorer `0.2`, baseline `0.2`, synthesis validator `0.3`)

| Finding | Change |
|---|---|
| Scorer credited entity, not change | Attribution resolves `change_evidence_id` to the sealed change's `source_ref` and requires the exact truth `source_ref`; false-cause selection and rejection are judged per `source_ref`. A missing, unknown or kind/entity-inconsistent change ID is reported as `identity_unverifiable`: never credited, never cleared of the false cause, and tallied separately |
| Baseline lacked change identity | `ca-baseline-naive/0.2` reports the evidence ID of the change it already selected; selection logic is unchanged |
| Synthesis validator could crash | An iterative strict-JSON shape check (types, string keys, depth ≤ 16, ≤ 20,000 nodes) runs before field logic; mistyped fields, duplicate claim IDs/citations and non-string `limitations` are rejected with deterministic reason codes; a validator exception rejects the attempt instead of failing the run |

No pinned fixture or truth changed, and no threshold exists to change. Headline counts are unchanged because each pinned fixture has one change per entity; the scorer fix closes a latent gap exercised only by the new regression tests.

## Known limitations

- One scenario family plus two counterexamples, all self-authored fixtures/truth/rules: results show the designed cases behave as intended, not general causal accuracy. The catalog maps only `pool.maxConnections` → `POOL_EXHAUSTED`, from a ConfigMap key or a typed Deployment field change; image-only defects have no template and cannot be supported.
- Engine citation-ID validity is trivially complete because the engine only cites sealed evidence; semantic support is checked only through rule predicates. Model prose is never semantically verified.
- Replay integrity uses hashes stored beside the artifacts; anyone able to rewrite the inputs, manifest and outputs together can forge a consistent run. Synthesis responses are not retained, so only their input digest is re-verified.
- No live connectors, RBAC, network policy, PostgreSQL roles, lifecycle expiry/deletion states or local model are exercised.
- Pairwise ordering excludes metric samples to stay bounded; it is quadratic in non-metric evidence.
- Timing is one run on the author's workstation; no warmups, repetitions or p95.

## Reproduce

```
make demo            # or: python prototype/cli.py demo
make test            # or: python -m unittest discover -s prototype/tests -t prototype
```
