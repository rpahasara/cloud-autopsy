# Integration preflight: PRs #42–#47 into `main` (read-only)

**Status:** a read-only preflight, run on 2026-11-15. Nothing was merged, pushed to `main`, retargeted, tagged or changed. Integration needs separate approval.

## What was checked

**The chain is linear** (each head is an ancestor of the next):

| PR | Branch | Head | Base today |
|---|---|---|---|
| — | `main` | `402531d` | — |
| #42 | `phase2/incident-milestone-plan` | `2448cdd` | `main` |
| #43 | `phase2/ca-p2-002e-kinds-v4` | `ce16124` | #42 |
| #44 | `phase2/ca-p2-005c-engine-v4` | `9bb7ce0` | #43 |
| #45 | `phase2/ca-p2-004g-pod-logs` | `735bc04` | #44 |
| #46 | `phase2/ca-p2-007a-eval` | `2b6fc40` | #45 |
| #47 | `phase2/ca-p2-007b-timing` | `f5ec00a` | #46 |

`402531d` → `2448cdd` → `ce16124` → `9bb7ce0` → `735bc04` → `2b6fc40` → `f5ec00a`. So `f5ec00a` contains every PR, and `main` can be **fast-forwarded** to it with no new merge commit.

**CI on each head** (`spike-ci`, pull-request runs) passed:

| Head | Run |
|---|---|
| `2448cdd` | 43505755655 |
| `ce16124` | 43574166213 |
| `9bb7ce0` | 43578348437 |
| `735bc04` | 43578350530 |
| `2b6fc40` | 43599833084 |
| `f5ec00a` | 43626982663: all six jobs, including `offline-checks` and `db-integration` (the ruleset's required checks) and the harness smoke |

**Local checks on the exact commit `f5ec00a`** (a clean worktree) all passed:
- the contract, engine, app, API, collector and eval suites;
- the three truth pins;
- the three documentation validators;
- the supply-chain check.

**Migrations.** `0001`–`0008` are byte-identical to `main`. `0009_pod_log_kinds.sql` is the only migration added (SHA-256 `9965bab5…`). It is additive: it adds batch 0.3 and kinds 0.4 to the supported versions and widens the batch-version check. Real-PostgreSQL tests apply it on its own and show that no historical row changes.

**Contract compatibility.**
- **Unchanged:** contract profiles 1–3, batches 0.1 and 0.2, kinds 0.1–0.3, rule profiles 1 and 2, and recordings 0.3–0.6 (each converts exactly as before).
- **New and additive:** profile 4, batch 0.3, kinds 0.4, rule profile 3 and recordings 0.5–0.7.

**Pinned and frozen material.** All of the following are unchanged from `main`:
- `tests/engine/test_cross_scope.py`, the six result digests;
- `prototype/`, which equals `c21b50d`;
- `examples/`;
- `src/cloud_autopsy/contracts/vectors`;
- `docs/reviews`, `docs/architecture` and `docs/scenarios`.

**Evaluation records.** All three evaluation baselines (`45bcebd`, `3499bbb`) are ancestors of `f5ec00a`. Their tags and `eval/` branches are on the remote, and their scenario digests reproduce. The per-run evidence exists only in the Actions logs, kept for 90 days; see the [closeout](ca-p2-007/ca-p2-007-closeout.md).

**Ruleset.** `main protection` (27133931) is `active`, has no bypass actors, and enforces `deletion`, `non_fast_forward` and `required_status_checks`.

## Blockers and conditions

**There are no technical blockers.** Four conditions:
1. **Evidence durability** (not a merge blocker, but time-bound). Archive the evaluation evidence before **2027-02-12**, as proposed in the closeout, in a separate docs-only PR.
2. **Stacked bases.** #43–#47 target the previous PR's branch. Retarget each to `main` just before `main` moves, so that GitHub records them as merged. #42 already targets `main`.
3. **New workflows land on `main`.** These are `incident-eval.yml` (it triggers only on pushes to `eval/ca-p2-007a-run-*` and `eval/ca-p2-007b-{v02,matrix}-run-*`) and the `collector-logs-kind` and `incident-eval-smoke` jobs (pull requests and manual dispatch only). Neither the new workflow nor the new jobs run on a push to `main`, and none uses a secret.
4. **PR #14 is unaffected but its conflict grows.** Its `spike-ci.yml` conflict with `main` becomes larger once these jobs land on `main`; it is still additive. PR #14 stays separate and unchanged.

## Smallest safe integration sequence (needs approval)

1. **Recheck that nothing has moved:** `main` = `402531d`, and the six heads match the table above. Stop if any differs.
2. **Preserve references.**
   - Create annotated tags `ca/pr-42-2448cdd` … `ca/pr-47-f5ec00a` and `ca/main-before-integration-402531d`, never overwriting an existing tag.
   - Make a verified `git bundle` of all refs, stored outside the repository.
3. **No integration branch.** The chain is already linear and `f5ec00a` has passed CI on that exact commit, so there is nothing to build or re-test.
4. **Retarget #43–#47 to `main`.**
5. **Move `main` with a plain, non-force fast-forward,** `git push origin f5ec00a:refs/heads/main`, under ruleset 27133931. Every original SHA is preserved and no branch is deleted.
6. **After the push:**
   - verify that #42–#47 are recorded as merged and every `ca/*` and evaluation tag is still reachable;
   - verify that CI on the push to `main` passes;
   - manually dispatch `spike-ci` on `main` to run the collector jobs;
   - confirm the ruleset is unchanged.
7. **Follow-ups, each docs-only:**
   - the fourth-integration record in `docs/phase2/integration.md`;
   - the evaluation evidence archive.

## Current-status addendum (2026-11-15, after integration)

The preflight above is kept as written. It was read-only and was run before any change. The approved sequence was then carried out.

**Before `main` moved:**
1. **The evidence was archived first:** PR #49, tag `ca/eval-evidence-archive-ca-p2-007-199d5e1`.
2. **Every head was rechecked:** all were unchanged, and `f5ec00a`'s required checks had passed.
3. **References were preserved.** Seven annotated tags were created: `ca/pr-42-2448cdd`, `ca/pr-43-ce16124`, `ca/pr-44-9bb7ce0`, `ca/pr-45-735bc04`, `ca/pr-46-2b6fc40`, `ca/pr-47-f5ec00a` and `ca/main-before-integration-402531d`. A verified backup bundle of 129 refs, `cloud-autopsy-before-fourth-integration-20261115-211321.bundle` (SHA-256 `9b71d091cf2bdc6da2d14afdbe2f1515bfb1ac59d1235e6609845ca7afc8906c`), is kept outside the repository.
4. **#43–#47 were retargeted to `main`.**

**The move.** `main` was moved from `402531d` to `f5ec00a` with a plain, non-force fast-forward. GitHub records #42–#47 as merged.

**After the move:**
- The push run, 43731564216, passed `offline-checks` and `db-integration`.
- The manual dispatch on `main`, 43732220091, passed all six jobs, including the three collector jobs and the harness smoke.
- Ruleset 27133931 is unchanged.

**Later.** PR #49 was integrated the same way, `f5ec00a` → `199d5e1`. See the [fourth-integration record](integration.md#fourth).
