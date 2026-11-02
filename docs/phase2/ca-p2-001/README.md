# CA-P2-001 — Dependency, licensing and SSDLC foundation (preparatory, Proposed)

Date: 2026-11-02. Backlog item: [CA-P2-001](../../reviews/phase1d/phase2-backlog.md). Owner role: Repository maintainer, with security and licensing reviewers. Status: Proposed preparatory work requested by the product owner. Gate D, Gate I and every CA-DEC decision remain unapproved. Nothing here is an approved dependency set, license clearance, security approval or Phase 2 authorization. See the [completion checklist](../../reviews/phase1d/completion-checklist.md) and [approval requests](../../reviews/phase1d/approvals.md).

## Scope and boundaries

This change prepares the foundation that the backlog lists as CA-P2-001 completion evidence: version/dependency inventory, license and NOTICE review records, SBOM approach, SSDLC/CI checks and an upgrade/advisory policy. It also audits the prototype and proposes the package layout and test strategy for CA-P2-002.

The work is local and synthetic-only. It adds no third-party dependency, no network-using tool, no cloud or cluster access, no model call, no product code and no change to the frozen prototype engine at `c21b50d`. Fixtures and truth pins are unchanged. PRs #11–#14 are untouched.

## Documents

| Document | Contents |
|---|---|
| [Prototype audit](prototype-audit.md) | Reusable reference components versus experimental-only code, with findings that affect CA-P2-002 |
| [Stack proposal](stack-proposal.md) | Minimum Python application stack; which choices are provisional |
| [Dependency and SSDLC policy](dependency-policy.md) | Pinning, inventory, license/NOTICE review, SBOM, advisory/upgrade policy and CI checks |
| [CA-P2-002 plan](ca-p2-002-plan.md) | Proposed package layout, test strategy and the next implementation slice |
| [Decisions required](decisions-required.md) | Product-owner, architecture, security and licensing decisions blocking dependent work |
| [Dependency inventory](../../../supply-chain/dependency-inventory.json) | Machine-readable inventory (`ca-dep-inventory/0.1`) |
| [License and NOTICE review record](../../../supply-chain/license-notice-review.md) | Per-component license status; all reviews pending |
| [SBOM](../../../supply-chain/sbom.cdx.json) | Deterministic CycloneDX 1.6 document generated from the inventory |

## Implemented tooling

`tools/supply_chain/supply_chain.py` (standard library only, offline) runs six check sections and generates the SBOM. `make supply-chain` runs its tests and the repository check, and CI runs the same step. Its output says what it is: repository conformance evidence, not license clearance, vulnerability scanning or security approval.

## Completion status against the backlog evidence

| Required CA-P2-001 evidence | State after this change |
|---|---|
| Approved scope-specific version/image inventory | Inventory exists and is enforced; approval not recorded |
| License review | Record exists; every row pending specialist review |
| Secret/dependency checks | Offline secret-pattern, manifest and import checks enforced in CI; advisory scanning not implemented (needs an approved service) |
| Build provenance policy | Proposed only; no shipped artifact exists yet |
| No unreviewed AGPL/model artifact bundled | Enforced by the license policy check; nothing is bundled |

CA-P2-001 cannot be marked done until the named reviewers record their dispositions. See [decisions required](decisions-required.md).
