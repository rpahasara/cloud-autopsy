# Integration of the draft PR chain into `main` (record)

**Decision (2026-11-11):** consolidate the linear draft chain (PRs #11–#13, #15–#26 and the corrections PR #27) into `main` with a single non-force fast-forward. This is "Method A" of the integration-readiness audit.

**Who decided:** the product owner, who is the solo founder. This is a **solo product-owner decision about repository history**. It is **not**:
- an independent specialist approval (security, privacy, licensing, database or evaluation);
- a Gate D, Gate I or Gate E disposition;
- acceptance of any CA-DEC decision;
- a production-readiness claim.

AI-assisted reviews in the PR conversations are engineering input, not sign-off.

**Scope:** the synthetic-only development foundation (see the [README](../../README.md)). Integrating it into `main` changes where the code lives, not its approval state. Everything recorded as open in the [approval records](../reviews/phase1d/approvals.md), the [completion checklist](../reviews/phase1d/completion-checklist.md) and the [Phase 2 backlog status](../reviews/phase1d/phase2-backlog.md#status) stays open.

## Why a fast-forward

- **The chain is already linear.** Each PR branch contains its base exactly, there are no merge commits, and `main` (`8a45136`) is an ancestor of every branch. A fast-forward therefore adds no new commit and rewrites none.
- **The frozen candidate keeps its identity.** Every original SHA reaches `main` unchanged, including the frozen prototype candidate `c21b50d` that the evaluation plan and the held-out kit reference.
- **The push cannot rewrite history.** `git push origin <sha>:main` without `--force` is refused by Git unless it is a fast-forward.
- **CI checks the result.** Each PR head already has green CI. The corrections commit adds `main` to the workflow's push trigger, so the integrated `main` is itself tested by the offline, browser and real-PostgreSQL jobs.

Squash and rebase merges must not be used for this chain: they would replace `c21b50d` and every later SHA.

## Preserved references

Before `main` moves:
- **Annotated tags** mark every PR head (`ca/pr-<n>-<sha7>`) and the frozen candidate (`ca/prototype-frozen-c21b50d`).
- **A `git bundle`** of all branches and tags is kept outside the repository as a recoverable backup.

The branch `spike/ca-scenario-001` is kept permanently. No branch is deleted as part of the integration.

## Checks before and after

**Before** (on the final corrections commit):
- `main` is an ancestor;
- `c21b50d` is an ancestor;
- `git diff c21b50d <final> -- prototype` is empty;
- `prototype/cli.py verify-fixtures` passes, with the truth pin unchanged;
- CI on PR #27 is green.

**After:**
- `origin/main` equals the final commit;
- the same ancestry and prototype checks pass on `main`;
- CI on the push to `main` is green;
- every `ca/pr-*` tag is reachable from `main`.

## Pull request statuses afterwards

When `main` contains a PR's head commit, GitHub marks a PR whose base is `main` as merged. For the stacked PRs, whose bases are other branches, the plan is:
1. **Before the push:** retarget each of #12, #13 and #15–#27 to `main`. They are then all recorded as merged by the push.
2. **Alternatively:** leave the bases unchanged and close each PR with a comment that names the integration commit and its tag.

Either way, no branch is deleted.

**PR #14** (the held-out evaluation kit) is **not** part of this integration. It stays a separate draft. Its two conflicts with `main` (`.github/workflows/spike-ci.yml` and `.gitignore`) are to be resolved later on its own branch with a merge commit, not a rebase, and only when a held-out evaluation with its custody rules is arranged.

## Second integration: PRs #28–#33 (2026-11-12)

**Decision (2026-11-12):** the product owner (solo founder) approved fast-forwarding `main` from `594fc78` to `d19893d`, the head of PR #33. The same limits apply as above: this is a solo product-owner decision about repository history, not a specialist approval, gate disposition, CA-DEC acceptance or production-readiness claim.

**What was integrated:**
- **PRs #28–#33:** CA-P2-004a (evidence bundles), 004b (lifecycle), 004c (recorded Kubernetes), 004d (observation kinds 0.2), and the 004e plan and collector. That is 28 commits.
- **The browser-harness fix from PR #34** (`8ca3ec0`). It had been merged up the stack with one merge commit per branch: `4e812e1`, `d19a3d6`, `164525d`, `26f0704`, `ac0bb89` and `d19893d`. Each has the previous head as its first parent.
- **The one conflict**, in `.github/workflows/spike-ci.yml`, came from two steps added at the same place. It was resolved in `164525d` by keeping both steps.

**History preserved:**
- No commit was squashed, rebased or rewritten.
- `main` was updated with `git push origin d19893d…:refs/heads/main`, without `--force`.
- No branch was deleted.

**Before the push:**
- **Heads:** every head matched the approved values. `main` was an ancestor of `d19893d` (0 behind, 28 ahead), and every commit listed on PRs #28–#34 was reachable.
- **CI:** green on every head, with `collector-kind` green on `d19893d`.
- **Prototype:** `prototype/` was unchanged since `c21b50d`, and the three truth pins verified.
- **Digests:** the six pinned result digests were byte-identical to `main`.
- **Migrations:** `0001`–`0004` were unchanged, and `0005`–`0007` were added in order.
- **Workflow:** the diff only added lines.
- **Annotated tags:** `ca/main-before-integration-594fc78`, `ca/pr-28-4e812e1`, `ca/pr-29-d19a3d6`, `ca/pr-30-164525d`, `ca/pr-31-26f0704`, `ca/pr-32-ac0bb89`, `ca/pr-33-d19893d` and `ca/pr-34-8ca3ec0`.
- **Backup bundle:** `cloud-autopsy-pre-integration-2026-11-12.bundle`, SHA-256 `ca868a324ccf7521c440b1c56452566f9e1cd7296883d627c81366cef60a3799`, 78 refs. It was kept outside the repository and test-restored with `git fsck --full`.

**Pull request statuses:**
- PRs #29–#33 were retargeted to `main` before the push.
- GitHub recorded all of #28–#33 as merged by the push. GitHub fills in the "merge commit" field itself for merges done outside the merge button; the integration commit is `d19893d`.
- PR #34 was already recorded as merged into `phase2/ca-p2-004a-bundles`.

**After the push:**
- **Heads and tags:** `origin/main` is `d19893d`. Every `ca/pr-*` tag except `ca/pr-14-890a03d` is reachable from `main`.
- **Prototype, pins and digests:** the prototype is unchanged, and the truth pins and the six result digests pass on `main`.
- **CI:** 
  - The push run [43249444188](https://github.com/rpahasara/cloud-autopsy/actions/runs/43249444188) passed `offline-checks` and `db-integration` (83 tests). Its `collector-kind` job is skipped on pushes by design.
  - The manual run [43250465682](https://github.com/rpahasara/cloud-autopsy/actions/runs/43250465682) passed all three jobs. In `collector-kind`, the disposable cluster refused 22 forbidden requests with 403; all four lists were consistent, with Events over 9 pages; the investigation abstained offline and database-verified; and the four fault runs became gaps.

**Final SHA of `main`:** `d19893d6327c3b9907d6b48fb60600019e97a2e5`.

**PR #14** is still not part of either integration. It stays a separate, unmerged draft on `spike/ca-scenario-001`.

## Protection of `main` (2026-11-12)

After the second integration, the product owner approved a repository ruleset for `main`, and it is now active:
- **Ruleset:** ID `27133931`, named "main protection". It is a branch ruleset defined at repository level, with enforcement `active`.
- **Target:** `refs/heads/main` only. It names the branch rather than "the default branch", so other branches are not affected.
- **Bypass actors:** none. GitHub reports that bypass is "never" possible.
- **Rules:**
  - **`deletion`:** `main` cannot be deleted.
  - **`non_fast_forward`:** force pushes and other non-fast-forward updates are refused.
  - **`required_status_checks`:**
    - `offline-checks` and `db-integration`, both from GitHub Actions (integration ID `15368`);
    - "require branches to be up to date" is off;
    - enforced on branch creation as well.
- **Not required:**
  - **Pull-request reviews:** a solo founder cannot approve their own PRs, and GitHub's merge button cannot do the plain fast-forward that keeps every SHA.
  - **`collector-kind`:** it does not run on pushes to `main`. It is still run on pull requests and by manual dispatch.

**Effect on integration:** a plain, non-force fast-forward of `main` stays possible, once both required checks have passed on the commit being integrated, as they do on its PR branch. History on `main` cannot be rewritten or deleted.

**Scope:** this is repository governance chosen by the product owner. It is not a production authorization, a security approval, a gate disposition or a production-readiness claim.

## Third integration: PRs #35–#39 (2026-11-13)

**Decision (2026-11-13):** the product owner authorized integrating CA-P2-004f (continuous watch collection), CA-P2-005b (observed-ordering rules) and their plans and records into `main`. As before, this is a solo product-owner decision about repository history, not a gate disposition, specialist approval or production-readiness claim.

**Included:**

| PR | Branch | Head |
|---|---|---|
| #35 | `docs/second-integration-record` | `0d85ffe` |
| #36 | `phase2/ca-p2-004f-plan` | `083d186` |
| #37 | `phase2/ca-p2-004f-watch` | `ceeff9a` |
| #38 | `phase2/ca-p2-005b-plan` | `f0cc1ed` |
| #39 | `phase2/ca-p2-005b-ordering` | `7ea6022` |

**Method:**
- `integration/004f-005b` started at #39's head (which already contained #37's head) and merged #38, #36 and #35 with `--no-ff` merge commits, all clean. No rebase, squash or force-push; every original SHA is preserved.
- Draft PR #40 ran CI on the exact integration commit; after it passed, #38 and #39 were retargeted to `main`, and `main` was moved with a plain, non-force fast-forward (`d19893d..9351762`) under ruleset `27133931`. GitHub records #35–#40 as merged.

**Preserved references:** annotated tags `ca/pr-35-0d85ffe`, `ca/pr-36-083d186`, `ca/pr-37-ceeff9a`, `ca/pr-38-f0cc1ed`, `ca/pr-39-7ea6022` and `ca/main-before-integration-d19893d` (no existing tag was overwritten), and a verified `git bundle` of all refs kept outside the repository. No branch was deleted.

**Checks before the push** (on `9351762`):
- all five PR heads, the previous `main` and the frozen candidate `c21b50d` are ancestors;
- `git diff c21b50d 9351762 -- prototype` is empty, and `verify-fixtures` passes with all three truth pins;
- the six pinned result digests in `tests/engine/test_cross_scope.py` are unchanged, and the engine suite that asserts them passes;
- migrations `0001`–`0007` are unchanged; `0008` is the authorized CA-P2-004f addition;
- locally: documentation validators, contract (216), engine (57), app (66) and collector (75) suites pass;
- CI run `43387651633` (pull request #40): `offline-checks`, `db-integration`, `collector-kind` and `collector-watch-kind` all passed, including the rule-profile-2 session on the disposable kind cluster.

**Checks after the push:**
- `origin/main` is `9351762`, and every `ca/*` tag except `ca/pr-14-890a03d` is reachable from it;
- ruleset `27133931` is still active, with no bypass actors and the same three rules;
- CI run `43388920581` (push to `main`): `offline-checks` and `db-integration` passed; the collector jobs do not run on pushes by design;
- CI run `43389662036` (manual dispatch on `main`): all four jobs passed. The watch job recorded five sessions, each with its own clock, one of them under rule profile 2; every investigation abstained, and the database runs verified on read.

**Final SHA of `main`:** `9351762436df5417a5b46aa03cbdd913be04c204`.

**PR #14** is still not part of any integration. It stays a separate, unmerged draft on `spike/ca-scenario-001`.

## <a id="fourth"></a>Fourth integration: PRs #42–#47, then the evidence archive PR #49 (2026-11-15)

**Decision (2026-11-15):** the product owner approved two steps, in this order:
1. archive the CA-P2-007 evaluation evidence;
2. integrate the incident milestone, PRs #42–#47.

As before, this is a solo product-owner decision about repository history. It is not a gate disposition, a specialist approval, independent accuracy evidence or a production-readiness claim.

**Included:**

| PR | Branch | Head | Content |
|---|---|---|---|
| #42 | `phase2/incident-milestone-plan` | `2448cdd` | The incident milestone plan (revisions 1–3.2) |
| #43 | `phase2/ca-p2-002e-kinds-v4` | `ce16124` | Observation kinds 0.4, acquisition batch 0.3 (`log_sequence_continuity`, sub-interval coverage), contract profile 4, migration `0009` |
| #44 | `phase2/ca-p2-005c-engine-v4` | `9bb7ce0` | Engine on profile 4; rule profile 3 (the causal-scope guard) |
| #45 | `phase2/ca-p2-004g-pod-logs` | `735bc04` | Pod-log collection and recordings 0.5–0.7 (M12a–d; Events explicitly not collected) |
| #46 | `phase2/ca-p2-007a-eval` | `2b6fc40` | The development-set evaluation harness |
| #47 | `phase2/ca-p2-007b-timing` | `f5ec00a` | Scorer integrity hardening, scenario 0.2, the timing matrix |
| #49 | `docs/ca-p2-007-evidence-archive` | `199d5e1` | The evidence archive of the three evaluations (docs only) |

**Method:**
- **The chain was already linear,** `402531d` → `2448cdd` → … → `f5ec00a`. So no integration branch was needed: `f5ec00a` had passed CI on that exact commit (run 43626982663, all six jobs).
- **The read-only [preflight](integration-preflight-42-47.md)** found no technical blockers.
- **#42–#47:** #43–#47 were retargeted to `main`, then `main` was moved `402531d..f5ec00a` with a plain, non-force fast-forward under ruleset 27133931.
- **#49:** after verification, `main` was moved `f5ec00a..199d5e1` the same way.
- **History:** there was no squash, rebase or merge commit on `main`, and every original SHA is preserved.

**Preserved references:**
- the tags `ca/pr-42-2448cdd` … `ca/pr-47-f5ec00a`, `ca/main-before-integration-402531d` and `ca/eval-evidence-archive-ca-p2-007-199d5e1`;
- the evaluation baseline tags `ca/eval-007a-run1-baseline-45bcebd`, `ca/eval-007b-v02-run1-baseline-3499bbb` and `ca/eval-007b-matrix-run1-baseline-3499bbb`;
- a verified bundle of 129 refs, kept outside the repository.

No tag was overwritten and no branch was deleted.

**Checks:**
- **Before `f5ec00a`:**
  - the chain is linear;
  - CI passed on every head;
  - migrations `0001`–`0008`, the six pinned digests, `prototype/` (equal to `c21b50d`), `examples/` and the contract vectors are byte-identical to `main`;
  - `0009` is additive;
  - every offline suite, the three truth pins and the documentation validators pass on the exact commit.
- **After `f5ec00a`:**
  - the push run 43731564216 passed `offline-checks` and `db-integration`;
  - the manual dispatch 43732220091 passed all six jobs;
  - GitHub records #42–#47 as merged.
- **Before `199d5e1`:**
  - the archive's checksums, counts and provenance were reverified;
  - each run was re-scored with its original scorer and reproduced its report exactly;
  - all 142 changed files are inside `docs/phase2/ca-p2-007/evidence/`.
- **After `199d5e1`:**
  - the push run 43736812476 passed `offline-checks` and `db-integration`;
  - GitHub records #49 as merged;
  - the archive tag is reachable from `main`.
- **Ruleset 27133931** stayed active throughout, with no bypass actors, the same three rules and the same two required checks.

**Final SHA of `main`:** `199d5e1203a3e0fac9141fda2640415aeda78679`.

**Not part of this integration:**
- **PR #48** (the closeout, the independent-evaluation plan and the preflight) stays a separate draft.
- **PR #14** stays a separate, unmerged draft on `spike/ca-scenario-001`.

The CA-P2-007 evaluations are developer-authored development-set evidence, not independent accuracy certification.

## <a id="fifth"></a>Fifth integration: PR #48 (2026-11-15)

**Decision (2026-11-15):** the product owner approved integrating PR #48 into protected `main` with the history-preserving fast-forward used before. As before, this is a solo product-owner decision about repository history. It is not a gate disposition, independent accuracy evidence or a production-readiness claim.

**Included:**

| PR | Branch | Head | Content |
|---|---|---|---|
| #48 | `phase2/ca-p2-007c-closeout` | `09b0979` | The CA-P2-007 closeout, the [CA-P2-007c independent-evaluation plan](ca-p2-007/ca-p2-007c-independent-plan.md), the [preflight for #42–#47](integration-preflight-42-47.md), and the [fourth-integration record](#fourth) (documentation only) |

**Method:**
- PR #48's branch already contained `main`. Merge commit `87e4cd7` had brought `origin/main` (`199d5e1`) into the branch before the documentation addenda (`09b0979`) were added, so the merge commit is part of PR #48's own ancestry. It is not a merge commit created on `main`.
- PR #48 was marked ready for review, then `main` was moved `199d5e1..09b0979` with a normal, non-force fast-forward (`git push origin 09b097966f58e4d9dad1eb8ab7c643cb50718bc3:refs/heads/main`) under ruleset 27133931.
- There was no squash, rebase or force push, and every original SHA is preserved.

**Checks before the move:**
- `main` was `199d5e1`, the PR #48 branch head was `09b0979`, and `199d5e1` is an ancestor of `09b0979`.
- The diff against `main` was four documentation files, additions only. No evidence file was changed or duplicated.
- All six jobs passed on `09b0979` (PR run 43738649330).

**Preserved references:**

| Tag (annotated) | Tag object | Target |
|---|---|---|
| `ca/pr-48-09b0979` | `e58424d8f8a5d080dfa523a576ec935beb168028` | `09b097966f58e4d9dad1eb8ab7c643cb50718bc3` |
| `ca/main-before-integration-199d5e1` | `4ac58abc4a924af5015dc8301f593aa8d60d7371` | `199d5e1203a3e0fac9141fda2640415aeda78679` |

- Before the move, neither tag name existed locally or on `origin`.
- After the move, both remote tags point to the same objects.
- **Backup bundle:**
  - file: `cloud-autopsy-before-fifth-integration-20261115-224958.bundle`, kept outside the repository;
  - 131 refs, and `git bundle verify` passes;
  - SHA-256 `ce60f2f0a41bcaf234d65f167768cb68b05ad37cde614fb5675850d23c2a0f75`;
  - it holds `origin/main` at `199d5e1`, PR #48's branch, and PR #14's head `890a03d`.

No tag was overwritten and no branch was deleted.

**Checks after the move:**
- `main` is `09b097966f58e4d9dad1eb8ab7c643cb50718bc3`.
- GitHub records PR #48 as merged at 2026-11-15T17:20:45Z, with `09b0979`.
- The push run 43740581161 on `09b0979` passed `offline-checks` and `db-integration`. The kind and harness-smoke jobs are skipped on push, as on earlier integrations; they passed on the PR run.
- Ruleset 27133931 is unchanged: active, no bypass actors, the same three rules (`deletion`, `non_fast_forward`, `required_status_checks`), the same two required checks, and last updated 2026-11-12.
- **Evaluation baselines and evidence:**
  - the tags `ca/eval-007a-run1-baseline-45bcebd`, `ca/eval-007b-v02-run1-baseline-3499bbb`, `ca/eval-007b-matrix-run1-baseline-3499bbb` and `ca/eval-evidence-archive-ca-p2-007-199d5e1` are unchanged and reachable from `main`;
  - all 142 files in `docs/phase2/ca-p2-007/evidence/` are byte-identical to `199d5e1`, and all three `SHA256SUMS` files verify.

**Final SHA of `main`:** `09b097966f58e4d9dad1eb8ab7c643cb50718bc3`.

**PR #14: clarified references.** Earlier records describe PR #14 as a draft "on `spike/ca-scenario-001`". That is its **base** branch. Its **head** branch is `eval/heldout-authoring-kit` at `890a03d86ed540401679f3266d895b62c5f56f10`. PR #14 is still open, a draft and unmerged. It was not part of this or any earlier integration, and it was not changed.

**Independent evaluation.** CA-P2-007c has not started. The CA-P2-007 evaluations remain developer-authored development-set evidence, not independent accuracy certification.
