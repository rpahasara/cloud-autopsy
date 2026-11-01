# Final requirements, architecture and security consistency review

Review ID CA-REVIEW-P1D. Date 2026-11-01. Scope: PR #11 `238cc2a` plus PR #12 `0859010`; author review, not an independent approval. [Current proposed SRS](../../srs.md), [architecture](../../architecture/phase1c/README.md), [threats](../../security/threat-model.md), all eight ADRs and their requirement matrices were reviewed.

## Findings and disposition

| Finding | Severity / gate | Evidence and consequence | Proposed resolution / remaining evidence |
|---|---|---|---|
| CA-REV-P1D-001 | High; design approval blocker | SRS section 10.1 requires verification evidence before requirement approval, while implementation needs a prior approved baseline. This can create a circular gate. | Proposed SRS 0.4.0 separates a complete verification plan for design approval from executed evidence for conformance. Product + architecture + security/evaluation must approve the distinction. No full gate is passed. |
| CA-REV-P1D-002 | High; design approval blocker | CA-DEC-003 allowed ±2 seconds when precision is unknown; the engine correctly refuses to bound unknown clocks without justification. | Reconcile the ADR: unknown clock uncertainty remains unordered. ±2/2/30-second values are provisional synthetic fixture/diagnostic settings only. Requires architecture/evaluation review and later clock-fixture tests. |
| CA-REV-P1D-003 | High; engineering gate blocker | Phase 1C checklist could imply a policy disposition waives the ADR's no-unresolved-Critical/High criterion. | Align wording: under the current proposed gate, any unresolved Critical/High blocks passage. Risk acceptance alone cannot override it; a changed gate needs a separately approved, versioned decision. No exception is granted here. |
| CA-REV-P1D-004 | High; implementation readiness blocker | All requirement owners are roles; named product/security/architecture/evaluation/risk authorities and independent sign-off records are absent. | CA-DEC-008 approval request names required roles/independence; product owner must nominate people. This agent's checks are not independent human review. |
| CA-REV-P1D-005 | High; implementation scope blocker | Canonicalization version, exact source/checkpoint plan, supported artifact pins, local API credential lifecycle, retries/idempotency horizon and purge/export inventory remain unspecified. | Resolve in the approval matrix or explicitly approve bounded Phase 2 specification tasks with exit criteria before dependent code. No developer invents an unlimited or unsafe fallback. |
| CA-REV-P1D-006 | High; empirical gate blocker | Only scenario 001 is specified; five variants are not 8–12 independent families. No tested corpus, benchmarks, runtime denial or lifecycle evidence exists. | Proposed benchmark plan freezes ten families and held-out splits; later run versioned tests under separately authorized Phase 2 work. Design completion and empirical gate completion stay distinct. |
| CA-REV-P1D-007 | Medium; commercial distribution blocker | Candidate Loki and optional Grafana carry AGPL obligations; dependencies/model weights/toolsets may differ from top-level project licenses. | Pin complete artifact inventory and get licensing/security review before copying, modifying, bundling or shipping. Keep agents comparator-only and use external telemetry APIs by default. No legal clearance is claimed. |
| CA-REV-P1D-008 | Medium; benchmark validity blocker | Agent comparators may have live-tool access and model differences while Cloud Autopsy uses frozen evidence. An uncontrolled comparison would confound evidence access with reasoning quality. | Separate matched-evidence and end-to-end tracks; document adapters, permissions, exclusions, model/config versions and unsupported cases. No superiority claim before results. |

“Proposed resolution” means the documentation has been clarified for review, not that a finding is approved, risk accepted or runtime control verified. Findings 001–003 have proposed text corrections in this change; their approval remains pending. Findings 004–008 remain open with owners and gates in the [outstanding-risk register](outstanding-risks.md).

## Consistency conclusions

- All 36 stable requirements have accountable owning roles, acceptance criteria, planned tests and reverse issue/decision/risk/threat mappings. Phase 1C maps the same IDs to components and contracts.
- Collector read-only permissions, no model execution tools, same-run citation constraints, explicit gaps, immutable input membership and separate truth/scoring are consistent design principles. Their runtime enforcement is untested.
- Timestamp text and uncertainty remain distinct from display ordering; loss of watch history or ConfigMap checkpoints prevents causal confirmation. An existing evidence ID alone does not prove semantic claim support.
- Lifecycle overlays preserve original integrity/availability history while authorized deletion removes payloads and prohibited digests. Historical replay may legitimately become incomplete/unavailable; retained hashes do not defend against a privileged administrator.
- External synthesis remains disabled and needs separate data-egress/security approval. Local/comparator models and toolsets still need pinned licenses and containment review.
- Numeric quality and performance targets remain provisional. The old 70% citation hypothesis and stricter proposed thresholds are alternatives pending measurement and explicit disposition, not simultaneous approved gates.

## Verification limits

Run both existing documentation validators and whitespace checks after these changes. Static traceability, parsed examples and rendered diagrams do not verify RBAC, network denial, semantic accuracy, database isolation, supply-chain safety or deletion races. PRs had no review submissions or CI checks at review start. Product, security, architecture and evaluation sign-off are still required; no implementation authorization is inferred.
