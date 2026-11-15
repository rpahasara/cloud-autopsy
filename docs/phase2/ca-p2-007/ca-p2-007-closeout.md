# CA-P2-007a/b: evaluation closeout and evidence durability

**Status:** the product owner accepted the recorded outcomes as **development-set evidence** on 2026-11-15, including the three pre-registered unnecessary abstentions (TP08). No further timing experiments or scenario tuning will be done unless a new defect warrants it.

These evaluations were authored by the developer of the engine. They are **not independent** and certify no accuracy. The [independent evaluation plan](ca-p2-007c-independent-plan.md) describes what independence requires.

## What is preserved, unchanged

| Run | Baseline commit | Tag | Scenario file | GitHub Actions run |
|---|---|---|---|---|
| v0.1 (untuned) | `45bcebd` | `ca/eval-007a-run1-baseline-45bcebd` | `scenarios.json`, `sha256:970f12fc…` | 43585433667 |
| v0.2 (+10 s window) | `3499bbb` | `ca/eval-007b-v02-run1-baseline-3499bbb` | `scenarios-0.2.json`, `sha256:fecb7c20…` | 43609551810 |
| Timing matrix 0.1 | `3499bbb` | `ca/eval-007b-matrix-run1-baseline-3499bbb` | `timing-matrix-0.1.json`, `sha256:27e43de2…` | 43609551789 |

The evaluation branches `eval/ca-p2-007a-run-1`, `eval/ca-p2-007b-v02-run-1` and `eval/ca-p2-007b-matrix-run-1` point at those commits. All three baselines are ancestors of the 007b head `f5ec00a`.

## Durability: the finding

**The evidence lives only in the Actions logs.** The sanitized run records, the append-only attempt logs and the scored reports exist only inside those logs; the job uploads no artifact. The repository's log retention is **90 days**, the maximum GitHub allows, so these logs begin to expire around **2027-02-12**. The commits, tags and scenario files are durable; the per-run evidence is not.

**It is still fully recoverable.** On 2026-11-15 all three runs were extracted from their logs and checked:

| Run | Records | `attempts.log` | Integrity gate (scorer 0.2) | Leak scan | SHA-256 of the saved log |
|---|---|---|---|---|---|
| 43585433667 (v0.1) | 41 | none (the run predates the hardening) | not applicable | clean | `14b7b2b5df6ebde3…` |
| 43609551810 (v0.2) | 41 | 41 lines | passes: exactly the pre-registered set | clean | `70cb75f211096366…` |
| 43609551789 (matrix) | 45 | 45 lines | passes: exactly the pre-registered set | clean | `f2ae7549dcfe0f11…` |

## Proposed: the smallest durable evidence archive (needs approval; not committed)

**One docs-only pull request** adds `docs/phase2/ca-p2-007/evidence/<run-id>/` for each of the three runs, containing:
- the run records, exactly as printed by the job (`<scenario>-<nn>.json`);
- `attempts.log`, for the 007b runs;
- `report.md`, the scored report exactly as the job printed it;
- `baseline.txt`: the commit, scenario digest and pinned versions from the job summary;
- `provenance.json`: the run ID, the baseline commit and tag, the SHA-256 of the saved raw log, and the extraction script's SHA-256;
- `SHA256SUMS` over every file in the directory.

**A test checks the archive:**
- every checksum;
- the integrity gate for the 007b runs;
- a leak scan for planted values, tokens and log text.

**Re-scoring is done offline and must reproduce each run's committed report.** v0.1 is re-scored with its own scorer, `ca-eval-scorer/0.1` at `45bcebd`. The 007b runs are re-scored with `0.2` at `3499bbb`.

**Nothing changes in the original results.** The archive copies them; it does not reinterpret them.

**Why this is enough.** The records hold only sanitized facts: outcomes, reasons, counts, identifiers of synthetic objects, timing margins and configuration. Every one of them passed the planted-data and token scan. No raw response, token or credential is included.

**Timing.** It should land before 2027-02-12. If it does not, the evidence must be re-extracted before the logs expire.

## Addendum (2026-11-15): the archive is committed and on `main`

The proposal above was approved and carried out. The text above is kept as written on 2026-11-15, before the archive existed.

**Where it is:**
- PR #49 added `docs/phase2/ca-p2-007/evidence/`: 142 files, all inside that folder ([archive README](evidence/README.md)).
- Branch `docs/ca-p2-007-evidence-archive`, commit `199d5e1203a3e0fac9141fda2640415aeda78679`.
- Tag `ca/eval-evidence-archive-ca-p2-007-199d5e1` (annotated object `e9eb805`). It is immutable by procedure: never moved or deleted.
- PR #49's CI, run 43730719204, passed all six jobs.
- `main` was moved from `f5ec00a` to `199d5e1` with a plain, non-force fast-forward. GitHub records PR #49 as merged, and the archive tag is reachable from `main`.
- The push run on `main`, 43736812476, passed `offline-checks` and `db-integration`.

**Verified twice:** when the archive was built, and again on `199d5e1` immediately before integration.

| Run | Records | `SHA256SUMS` SHA-256 |
|---|---|---|
| 43585433667 (v0.1) | 41 | `346a2ade73e14b6b95c1aaa16f393c648bf65b61144db97d5967ec67118e1ad4` |
| 43609551810 (v0.2) | 41 | `9e6767b8849242b3f8e4835de20533387b8433db92660ec18bc96e2e21871f73` |
| 43609551789 (timing matrix) | 45 | `e54979ec6e1fbdde8df5108e8e819a670810f3901c133e31dacbc66511804a11` |

**What both verifications established:**
- every checksum verifies;
- the provenance hashes match the raw logs and the extraction script in the restricted backup;
- the v0.2 and matrix records pass the integrity gate;
- each run, re-scored with its original scorer (0.1 at `45bcebd`; 0.2 at `3499bbb`), reproduces its report exactly;
- the leak scan of all 141 files had zero hits.

The v0.1 attempt log does not exist and was not reconstructed. The raw logs and the extraction script stay in a restricted backup outside the repository, readable only by the product owner's account.
