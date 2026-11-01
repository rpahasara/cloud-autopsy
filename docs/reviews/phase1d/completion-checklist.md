# Formal Phase 1 completion and Phase 2 readiness checklist

Owner: Product / requirements authority. Status: Proposed; no sign-off or implementation authorization. All approval/gate boxes remain unchecked. The design deliverables exist for review, but their existence is not acceptance. See [review findings](consistency-review.md), [approval requests](approvals.md) and [open risks](outstanding-risks.md).

## Gate D — Phase 1 design completion

- [ ] Product explicitly selects the reviewed SRS baseline, including the proposed 0.4.0 design/conformance amendment; retains stable IDs and historical drafts.
- [ ] Named product, architecture, Kubernetes/security, DB/privacy-lifecycle, independent evaluation and licensing reviewers acknowledge responsibilities and conflicts.
- [ ] CA-DEC-001 through CA-DEC-008 receive explicit scoped dispositions with reviewed commit, rationale, dates, evidence and excluded provisional assumptions; no silent acceptance.
- [ ] All 36 requirements, F1–F16 flows, TB0–TB5 boundaries, eight contracts, logical schema and six STRIDE threats are independently reviewed for consistency.
- [ ] Clock uncertainty, full-corpus scope and no-unresolved-Critical/High wording are reconciled and approved; CA-REV-P1D-001 through 003 receive dispositions.
- [ ] Dependency research, commercial/licensing obligations and differentiation hypotheses are reviewed without claiming market proof or security certification.
- [ ] Benchmark design, corpus/splits, ground-truth independence and measurement limitations are approved as plans, not results.
- [ ] Each open risk has a named accountable incumbent, blocked gate and required evidence; none is silently accepted.
- [ ] Both PRs remain draft/unmerged unless a separate later workflow authorization says otherwise; all Phase 1 issues retain their own evidence-based completion rules.

Gate D can be considered only after the above design approvals. It does not require already-written application code and does not pass Gate E. A scoped deferral needs authority, rationale, owner, dependency boundary and review date; a blanket “TBD” is not approval to invent values.

## Gate I — Separate authorization for bounded Phase 2 work

- [ ] Product explicitly authorizes named Phase 2 backlog items and exclusions after Gate D disposition; no authorization is inferred from this package or documentation merge.
- [ ] Required specialist conditions for those items are met; unresolved numeric values are either approved finite evaluation settings or block dependent execution.
- [ ] CA-P2-001 dependency pins, license/SBOM/NOTICE, security/CI policy and upgrade ownership are specified before application results are accepted.
- [ ] Exact source/checkpoint, canonicalization/identity, credential/retention and interface specifications have signed-off exit criteria before dependent code.
- [ ] External-provider work, if requested later, receives separate data-egress/security approval before credentials, route enablement or requests; deterministic/local-only work does not depend on it.

## Gate E — Empirical engineering qualification, deferred to authorized implementation

- [ ] Scenario 001 A–E harness qualification executes with immutable input/output, failure and security evidence; variants count as one family.
- [ ] The full selected 8–12-family corpus and held-out cases are implemented, independently frozen and run under approved bounded conditions.
- [ ] Development benchmarks inform quality/performance/capacity settings; final gate thresholds and denominator rules are approved and frozen before held-out gate scoring.
- [ ] Required-evidence recall, fact support, citation validity, causal mechanism accuracy, false-cause selection, appropriate/over-abstention and failures are reported separately.
- [ ] CA-TEST-SEC-001 through CA-TEST-SEC-012, component contracts, same-run constraints, expiry/deletion and replay-race tests have reviewable runtime artifacts.
- [ ] The current proposed no-unresolved-Critical/High condition is met; no aggregate accuracy or risk acceptance silently overrides it.
- [ ] Independent reviewers adjudicate truth/scorer and comparative results, including incompatible capabilities, missing outputs and family-level uncertainty.
- [ ] Named product, architecture, security and gate authorities record separate dispositions; any risk acceptance is explicitly authorized and cannot itself alter a gate.
- [ ] Original Phase 1 issues close only when their actual acceptance evidence exists; no issue closure is treated as approval or production release.

Neither Gate D, I nor E is passed today. Design/Phase 2 planning can be completed without pretending the empirical Phase 1 engineering gate has already run. Commercial readiness, production/customer access and release remain separate future gates under the charter.
