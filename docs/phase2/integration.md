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
