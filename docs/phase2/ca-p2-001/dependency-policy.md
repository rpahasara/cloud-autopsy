# Dependency, licensing and SSDLC policy (Proposed)

Status: proposed policy for CA-P2-001. Not approved. Required reviewers: repository maintainer, security reviewer and licensing/commercial reviewer ([approvals](../../reviews/phase1d/approvals.md)). The policy is enforced mechanically where an offline check is possible. Everything else is a review obligation.

## Version pinning

| Artifact | Rule | Enforced today |
|---|---|---|
| GitHub Actions | Full 40-hex commit SHA, matching the inventory; tag in a trailing comment | Yes |
| Python packages | Exact `name==version` with `--hash=sha256:` for every artifact, in a manifest listed in the inventory | Yes; any undeclared manifest fails |
| Interpreter | Exact patch for shipped artifacts; the version line is allowed for build-and-test only | Partly; the CI patch currently floats within 3.13 (D3) |
| Container images (future) | Digest pin (`@sha256:`) plus a recorded tag | Not applicable yet |
| Hosted runner | Mutable label; recorded as an accepted CI-only exception pending D10 | Recorded |
| Model weights (future) | Digest plus license and source record; never fetched at run time | Not applicable; none exist |

## Dependency inventory

[`supply-chain/dependency-inventory.json`](../../../supply-chain/dependency-inventory.json) (`ca-dep-inventory/0.1`) records each component's:

- type, name and version;
- pin kind and value;
- usage scope: `build-and-test`, `ci-only` or `runtime-shipped`;
- purpose;
- SPDX license, its source and the review state;
- upgrade owner.

A component must be in the inventory before it is used. The check fails if:

- a workflow uses an action that isn't in the inventory, or one whose SHA differs from it;
- the inventory lists an action that no workflow uses;
- Python code imports a module that is neither standard library nor first-party;
- a dependency manifest exists without an inventory declaration.

## License and NOTICE review

[`supply-chain/license-notice-review.md`](../../../supply-chain/license-notice-review.md) holds one row per component.

Rules enforced by the check:

| Situation | Requirement |
|---|---|
| License is MIT, Apache-2.0, BSD-2/3-Clause, ISC, PSF-2.0 or 0BSD | Inventory entry with review `pending` is enough while the component is not shipped |
| Any other license, including GPL, AGPL, LGPL, MPL, EUPL, SSPL, BUSL and custom terms | Needs `review: approved` plus an `approval_record` reference before it can appear at all |
| `NOASSERTION`, unknown or no license | Rejected |
| Component with `runtime-shipped` scope | Needs an exact or commit pin and an approved license review |
| A license review marked `approved` | Must name its approval record |

The check classifies licenses; it does not clear them. Only the licensing reviewer can approve a license, and AGPL/MPL obligations depend on the distribution and service model (D2).

**NOTICE:** no third-party code, binary or model is redistributed today, so no NOTICE file is required yet. A NOTICE file is created when the first `runtime-shipped` component is approved. It collects the attribution texts that component's license requires; for example, Apache-2.0 requires carrying the upstream `NOTICE` file.

## SBOM approach

[`supply-chain/sbom.cdx.json`](../../../supply-chain/sbom.cdx.json) is a CycloneDX 1.6 JSON document generated from the inventory by `supply_chain.py sbom`.

- **Reproducible:** it has no timestamp, and the serial number is derived from the inventory digest.
- **Kept in sync:** the check fails if the committed SBOM differs from a fresh generation.
- **Today's coverage:** components that are not shipped are marked `scope: excluded`. Once a deployable artifact exists, an SBOM must be generated from that built artifact as well. The proposed generator for that is CycloneDX or Syft tooling, subject to D5. An inventory-derived SBOM cannot prove what a built image actually contains.

## Advisories and upgrades

**Advisory checks (proposed, not implemented):**
- Before a dependency is added or upgraded, check it against public advisory data: the OSV database through `pip-audit`, and GitHub Security Advisories.
- Repeat the check weekly while dependencies exist.
- These tools contact external services, so they need approval first (D6). Nothing in CI calls them.

**Upgrades (proposed):**
- Every component has a named upgrade owner (D7).
- Security fixes are triaged within a review period that the security reviewer sets; no period is invented here.
- Version-line changes, such as a new Python minor, a new action major or a new PostgreSQL major, need an inventory change, a regenerated SBOM, a passing CI run and reviewer sign-off.
- An upgrade never changes the frozen evaluation candidate. It produces a new candidate version.

## SSDLC checks

| Check | Mechanism | State |
|---|---|---|
| Unit and contract tests | `unittest` in CI | Implemented (prototype, kit and supply-chain tests) |
| Fixture and truth-pin integrity | `prototype/cli.py verify-fixtures` | Implemented |
| Documentation traceability | `tools/validate_*.py` | Implemented |
| Action SHA pins, least-privilege permissions, no `pull_request_target`, no secrets, non-persisted checkout credentials | `supply_chain.py check` (workflows) | Implemented |
| Dependency inventory and license policy | `supply_chain.py check` (inventory, manifests) | Implemented |
| Standard-library-only imports in `prototype/`, `tools/`, `src/` | `supply_chain.py check` (imports) | Implemented |
| High-confidence secret patterns in tracked files | `supply_chain.py check` (secrets); reports location only | Implemented; not a replacement for push protection |
| SBOM drift | `supply_chain.py check` (sbom) | Implemented |
| Vulnerability advisories | `pip-audit` (OSV) or GitHub Dependabot alerts | Proposed; needs D6 |
| Static analysis | Candidate: Bandit, or CodeQL code scanning | Proposed; needs D5/D6 |
| Push-protection secret scanning | GitHub secret scanning (repository setting) | Proposed; needs D6 |
| Build provenance and signing | Candidate: GitHub artifact attestations or Sigstore for shipped artifacts | Deferred (D9); no shipped artifact |

## Limits of the offline checks

- **Workflow parsing:** workflows are read with line-based patterns, not a YAML parser, so unusual YAML layouts could evade a rule. Workflow changes still need review.
- **Secret scanning:** it detects only high-confidence token shapes. It doesn't detect low-entropy secrets and doesn't scan Git history.
- **Import scanning:** it inspects static imports only. Dynamic imports and subprocess calls are a review matter.
- **License classification:** it trusts the SPDX value recorded in the inventory. The licensing reviewer must verify that value against the pinned source.
