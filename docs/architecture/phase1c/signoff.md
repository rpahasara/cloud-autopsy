# Outstanding questions and proposed Phase 1 sign-off checklist

Owner: Product / requirements authority, with Architecture lead, Security reviewer and Evaluation/gate reviewer. Status: Proposed; every checkbox remains unchecked. Completing a document does not satisfy runtime verification or approve implementation.

## Outstanding design questions

| Decision | Question and proposed position | Required authority / review trigger |
|---|---|---|
| CA-DEC-001 | Confirm exact synthetic namespace, source/API versions, named ConfigMaps and before/after/consumption checkpoints. Are metrics/log templates sufficient to establish the declared mechanism? | Product + architecture + security; any source/permission or data-classification change |
| CA-DEC-002 | Choose supported PostgreSQL version, canonicalization/hash format and byte retention; confirm DB-role/process separation and whether stronger tamper evidence is needed | Architecture + security; first schema prototype or privileged-integrity threat |
| CA-DEC-003 | Benchmark skew/precision fixtures. Accept interval comparison and decide measured versus fixture-declared offset policy; provisional thresholds cannot bound unknown clocks | Architecture + evaluation; false-ordering result/new clock domain |
| CA-DEC-004 | Keep synthesis disabled/local. Is any external provider needed? If so, separate approval must resolve provider, region, terms, routes, redaction, credentials and revocation | Product + separate data-egress/security authority; no external enablement from this PR |
| CA-DEC-005 | Approve or revise proposed 30/180-day and seven-day periods; define controlled-export inventory, deletion authorization, backups and privacy-safe digests | Product + security; deletion obligation, new destination or retained sensitive metadata |
| CA-DEC-006 | Freeze 8–12 independent families/splits, denominators, missing/zero-case scoring and benchmarked quality thresholds; appoint independent truth/scorer reviewer | Product + evaluation + security; corpus/scorer change or first benchmark |
| CA-DEC-007 | Validate reference hardware, sample count/p95 method, finite input/concurrency/retry limits and provisional budgets | Product + architecture + evaluation; first benchmark or bound exhaustion |
| CA-DEC-008 | Name requirements, architecture, security, gate and risk authorities; resolve conflicts of interest; choose local API credential storage/rotation and idempotency horizon | Product + security; staffing, remote exposure or authority change |

## A. Requirements and architecture baseline review

- [ ] Name accountable incumbents and explicit approval authorities; record independence of truth/scorer review and High-risk acceptance.
- [ ] Review SRS 0.2.0 history and 0.3.0 remediation relationship; explicitly choose the future baseline without silently approving either draft.
- [ ] Resolve CA-DEC-001 through CA-DEC-008 by named authority, with rationale and review triggers; no Proposed record is treated as accepted prematurely.
- [ ] Review all component identities, F1–F16 flows, TB0–TB5 boundaries, logical schema constraints, API contracts and 36-row traceability.
- [ ] Confirm exclusions: production data/control plane, cluster mutation, autonomous actions, multi-tenancy and remote API exposure.
- [ ] Record unresolved risks and scope constraints separately from approval; document any authorized disposition.
- [ ] Keep PR #11 and the architecture PR draft until their own review prerequisites are met; merge is not sign-off.

## B. Prerequisites for separately authorized implementation planning

- [ ] Approve a bounded implementation plan after architecture/requirements disposition; do not infer implementation authority from these documents.
- [ ] Specify pinned dependencies/artifacts, schema/migration review, SSDLC scans and CI checks before application code is accepted.
- [ ] Define test fixtures, contract schemas, canonicalization/version rules, query registry and reference environment without inventing missing budgets.
- [ ] Plan actual identity/RBAC/network-denial, canary, lifecycle/race and integration verification evidence.
- [ ] If external AI is proposed, obtain separate data-egress and security approval before credentials, route enablement or request transmission.

## C. Future harness qualification and full Phase 1 gate

- [ ] Produce versioned A–E initial harness results including failures, false-cause rejection, gaps, skew, injection and model failure; do not call five variants the corpus gate.
- [ ] Freeze and run the full planned 8–12-scenario corpus with held-out families and independently reviewed truth/scorer.
- [ ] Benchmark provisional quality metrics and performance/capacity targets; explicitly approve final thresholds before using results for a gate.
- [ ] Demonstrate deterministic equivalence and unsupported-claim/citation checks without ground-truth leakage.
- [ ] Execute all CA-TEST-SEC-001 through CA-TEST-SEC-012 requirements and integration/contract tests with immutable artifact links.
- [ ] Verify expiry/deletion, safe tombstones, controlled export/cache purge, incomplete replay and integrity-mismatch distinction under concurrent access.
- [ ] Review every residual security finding; no unresolved Critical/High finding qualifies under the proposed gate without a separately reviewed policy disposition.
- [ ] Record named product, architecture, security and gate decisions as separate dated records; keep risk acceptance separate and explicit.
- [ ] Leave issues open until their own acceptance evidence is complete; do not equate issue closure with approval or release authorization.

No checklist item is asserted completed by this package. No benchmark, live RBAC check, network test, database migration or model invocation has occurred.
