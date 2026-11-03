# CA-P2-003a — PostgreSQL persistence architecture and implementation plan (provisional)

Date: 2026-11-03. Backlog item: [CA-P2-003](../../reviews/phase1d/phase2-backlog.md). Baseline: PR #19 at `981b6cd`. Status: **bounded preparatory planning only**, authorized by the product owner on 2026-11-03. This is not approval of Gate I, CA-DEC-002, CA-DEC-005, CA-DEC-008 or any security decision. Every database decision here is provisional. Nothing was installed, no container was started, no database was connected to, no dependency was added and no credential was created.

## Documents

| Document | Contents |
|---|---|
| [Proposed schema](schema.md) | Tables, keys, same-run isolation, indexes and immutability |
| [Transaction model](transactions.md) | Idempotent ingestion, derived quarantine, two-phase atomic sealing, concurrency, retries, crash recovery and rollback |
| [Security design](security.md) | Least-privilege runtime roles, credentials and STRIDE coverage |
| [Dependency evaluation](dependencies.md) | PostgreSQL 18 image pinning, driver options and licenses, lock files, SBOM, vulnerability checks and supply-chain tool changes |
| [Migrations and integration tests](migrations-and-tests.md) | Versioned forward-only migrations, rollback limits, and 20 planned synthetic integration tests |
| [Inconsistencies and decisions](inconsistencies.md) | Twelve contract and data-model inconsistencies, and eight decisions |

## Summary of the proposal

- **Storage model:** canonical bytes are authoritative, and decoded columns serve constraints and queries. Evidence identities and versions are global and append-only. Every run-scoped table is keyed by `run_id`, and composite foreign keys make cross-run membership impossible.
- **Quarantine:** derived from append-only rows (views), never a mutable flag, so concurrent writers can't lose or race it.
- **Sealing:** two-phase. A compare-and-swap freezes intake, the pure contract seal runs outside any transaction, and one transaction publishes the root, all pages and the decoded membership. One manifest per run is enforced by the primary key, and deterministic output makes crash recovery safe.
- **Roles:** separate roles for planning, ingestion, sealing, reading, evaluation, lifecycle and migration. No runtime superuser. Truth is readable only by the evaluator.
- **Dependencies:** a digest-pinned PostgreSQL 18 test image. pg8000 (permissive) is the recommended driver because psycopg 3 is LGPL and needs specialist review under our policy. No ORM or migration framework. The supply-chain tool needs version 0.2 to allow inventoried third-party imports and digest-pinned images.

## <a id="authorization-checklist-ca-p2-003b"></a>Authorization checklist for CA-P2-003b

CA-P2-003b (migrations, adapter, integration tests) must not start until each item is recorded:

- [ ] Product authorizes CA-P2-003b as bounded preparatory implementation, or Gate I authorizes CA-P2-003, with exclusions stated.
- [ ] CA-P2-002a–d contracts and vectors are reviewed, or building on provisional versions is explicitly accepted (I12).
- [ ] Inconsistencies I1–I12 resolved or deferred with owners; at minimum I1, I3, I4, I5 and I7.
- [ ] D-DB1: PostgreSQL 18 minor and image digest approved for test use.
- [ ] D-DB2: driver chosen; licensing reviewer has recorded the license outcome for it and every transitive dependency (D7).
- [ ] D-DB3 and D5: packaging, lock-file tool and one-time package-index access approved.
- [ ] D-DB8 and D6: advisory checking approved, or the manual-review substitute explicitly accepted.
- [ ] D-DB7: local disposable container and CI service container approved for synthetic data only.
- [ ] Security reviewer has reviewed the role and grant matrix and the credential handling.
- [ ] Supply-chain tool 0.2 changes approved (third-party import allowlist, image pins, workflow `services:` checks).
- [ ] Named owners for database upgrades and advisories recorded (D7 and CA-DEC-008).

## <a id="pr-chain-integration-plan"></a>Plan to review and integrate the draft PR chain

**Current chain (all drafts, none approved):**
- `main`
- #11 Phase 1 SRS baseline
- #12 Phase 1C/1D architecture
- #13 CA-SPIKE-001 prototype; its frozen candidate is `c21b50d`
- #14 held-out kit, a side branch on #13
- #15 CA-P2-001
- #16 CA-P2-002a
- #17 CA-P2-002b
- #18 CA-P2-002c
- #19 CA-P2-002d
- this PR, CA-P2-003a

**Proposed integration without bypassing the SSDLC:**

1. **Set up governance first.** Name the approvers (CA-DEC-008). Enable branch protection on `main`:
   - required review by a named approver other than the author;
   - the required `spike-ci` status check;
   - no force pushes;
   - no administrator bypass.

   These are repository settings that need owner approval.
2. **Review from the bottom up.** Each PR is reviewed and dispositioned on its own:
   - #11 and #12 need Gate D design dispositions (product plus specialists);
   - #13 needs an architecture and evaluation review of the prototype as a frozen reference, not as product code;
   - #15 to #19 need architecture, security and licensing reviews of their contracts and tooling.

   A later PR can't be approved before the PR it builds on.
3. **Merge in order, without rewriting history.** Use merge commits rather than squash or rebase, so `c21b50d`, which the evaluation kit and the held-out plan reference as the frozen candidate, stays reachable with the same SHA.
4. **Re-run CI at each step.** After each merge, retarget the next PR to `main`, re-run CI on the merged base, and resolve conflicts in the PR branch with review. Approval applies to the reviewed commit; any new commit needs re-review.
5. **#14 (held-out kit)** stays separate. It merges only after the independent-evaluation owner approves it, and never before a held-out evaluation is arranged under its custody rules.
6. **Keep the records.** Each approval gets the [approval record](../../reviews/phase1d/approvals.md) fields (reviewed commit, scope, excluded assumptions, reviewers, dates). A merge isn't an approval, and a CI pass isn't a gate.

## What this PR changes

Documentation only, under `docs/phase2/ca-p2-003/`. No code, schema files, dependencies, workflows, fixtures, truth pins, prototype or evaluation kit changes.
