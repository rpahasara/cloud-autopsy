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
