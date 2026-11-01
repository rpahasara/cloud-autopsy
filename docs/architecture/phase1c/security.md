# Phase 1C STRIDE coverage and security test requirements (Proposed)

Owner: Security reviewer. Decisions CA-DEC-001 through CA-DEC-008; primary issue #10, supporting #2–#9. Baseline [threat register](../../security/threat-model.md) and [risk register](../../security/risk-register.md) remain authoritative; this file refines subcases across the architecture without renumbering six stable threat IDs. None of the controls is demonstrated or approved by writing this design.

## Assets, attackers and assumptions

Protect evidence identity/provenance, ground truth/scores, read credentials, telemetry, lifecycle/audit integrity and human trust in results. Assume hostile source text, malformed telemetry, compromised workload identities, forged source claims, malicious model responses, accidental reviewer/configuration errors and component failures. A synthetic local environment lowers exposure but does not justify giving the collector write authority. Host/DB administrator compromise can defeat local hashes and permissions; stronger attestation/independent storage remains an unresolved design trigger.

## Flow-by-flow coverage

Threat key: S = CA-THREAT-S-001, T = CA-THREAT-T-001, R = CA-THREAT-R-001, I = CA-THREAT-I-001, D = CA-THREAT-D-001, E = CA-THREAT-E-001. IDs retain exact requirement/risk/test edges in the baseline matrix; this table identifies applicable subcases and controls. TB and flow IDs are defined in [diagrams](diagrams.md).

| Flow | Boundaries | Threats / abuse | Proposed mitigation | Residual risk / required evidence |
|---|---|---|---|---|
| F1 | TB0 → TB3 | S/R/E: forged investigator/approval; I/D: unsafe query or export | Authenticate scope/ownership, finite scenario registry, no approval/action endpoint, audit | Local token theft; CA-TEST-SEC-008/009/012 negative API tests |
| F2 | TB0 → TB3/TB2 | T/E: changed plan or malicious source URL | Pin reviewed config digests; fixed endpoint/query registry; reject redirects | Authorized bad config; CA-TEST-SEC-007/010 policy-digest tests |
| F3 | TB1 → TB2 | S/I/D/E: impersonated API, credential leakage, oversized source, unsafe subresource | TLS identity, namespace Role, short-lived credential, source bounds | Read access still exposes response fields; CA-TEST-SEC-001/005/009 real-identity tests |
| F4 | TB2 ingress | S/T/D/E: fabricated batch, conflicting identity, parser/instruction attack | Authenticated sender, strict version/schema, duplicate-key rejection, size checks | Normalizer bugs; CA-TEST-FR-002 and CA-TEST-SEC-003/007/009 adversarial fixtures |
| F5 | TB2 → TB3 | T/I: overwrite or secret persisted | Insert-only evidence role, atomic batch/cursor, minimize and canary scan | Redaction misses and privileged DB writes; CA-TEST-SEC-005/007 |
| F6 | TB3 coordinator/store | T/R: racing seal or mutable inputs | Enumerated frozen set, snapshot and expected-state transition, immutable manifest | DB admin can rewrite history; CA-TEST-FR-004/010 and CA-TEST-SEC-007 |
| F7 | TB3 store/engine | T/D: expired, missing or inconsistent dependency | Verify digests/versions/availability; explicit incomplete replay; bounded engine | Lifecycle race/process compromise; CA-TEST-FR-010 and CA-TEST-SEC-007/010 |
| F8 | TB3 → TB4 | I/E: secret transfer or hostile prompt text | Minimized data-only contract, no tools/credentials, sandbox and output validation | Delimiters cannot guarantee obedience; CA-TEST-SEC-002/003/005 |
| F9 | TB4 → TB5 | I/S/E: unapproved provider/route or exfiltration | Default deny, separate approval, broker/TLS/region allowlist, no redirect/URL tools | Provider terms/network enforcement failure; CA-TEST-SEC-006 denies all unapproved routes |
| F10 | TB4 → TB3 | S/T/E/D: invented citations, causal promotion, forged approval, oversized response | Bundle digest binding, finite schema, fact-template checks, no execution surface | Semantic overstatement; CA-TEST-FR-008 and CA-TEST-SEC-004/009/010 |
| F11 | TB3 engine/store | T/R: result overwritten or partial labelled complete | Engine-only immutable publication, explicit component states, provenance/version references | Trusted process bug; CA-TEST-NFR-003 and CA-TEST-SEC-007/008 |
| F12 | TB0 → scorer | T/I/E: truth edited after result, truth leaks to engine | Independent frozen truth, separate evaluator identity/views, no truth in engine input | Author bias/collusion; CA-TEST-FR-011 and CA-TEST-SEC-007 |
| F13 | TB3 store/scorer | T/D: wrong result version or lost failures | Sealed digest binding; all failed/partial outcomes retained; scorer bounds | Scorer defects; CA-TEST-FR-011 and CA-TEST-NFR-003 |
| F14 | TB3 scorer/store | T/R/E: rewritten score or pass treated as approval | Append report versions, fixed denominators/threshold versions, explicit approval separation | Biased metrics and governance misuse; CA-TEST-SEC-007/012 |
| F15 | TB3 lifecycle/store | T/R/I/D: unauthorized purge, leaked tombstone, purge failure or race | Separate role, verified authorization, atomic unavailable/tombstone, retries and minimized provenance | Backups/exports and privileged deletion; CA-TEST-FR-010 and CA-TEST-SEC-005/007/008/010 |
| F16 | TB3 → TB0 | I/E/R/D: unsafe HTML, secret export, fabricated confidence, oversized response | Filtered views, inert text/no remote assets, pagination, visible limitations/approval label | Authorized recipient copies data; CA-TEST-FR-012 and CA-TEST-SEC-005/009/012 |

## Required security test specifications

Every row is planned, not executed. Record fixture and component versions, actual identity/permissions, input digest, policy digest, expected/observed outcome and safe audit artifacts. A narrative assertion or static manifest inspection alone cannot prove runtime denial. Reuse the stable CA-TEST IDs from the [requirement matrix](../../requirement-matrix.md); new subcases do not create untraceable duplicate test names.

| Test | Required negative/positive cases | Required pass evidence |
|---|---|---|
| CA-TEST-SEC-001 | Allowed reads; denied writes, Secrets, exec/attach/proxy/token, cross-namespace, RBAC escalation; expiry/rotation of actual credential | Permission matrix plus runtime denied operations with no source mutation; secret canary absent |
| CA-TEST-SEC-002 | Model/log/annotation requests shell, cluster writes or fabricated tool/approval actions | Tool inventory empty of such capabilities; blocked route/operation trace; no action object created |
| CA-TEST-SEC-003 | Plain, encoded, multilingual and delimiter-breakout instructions in every source field | Serialized data contract; unchanged policy/run plan; inert text rendering and rejection where required |
| CA-TEST-SEC-004 | Invalid JSON/schema, extra fields, fake/out-of-run citations, wrong bundle digest, semantic overstatement, excessive response | Typed rejection/counts; no unsupported statement shown as supported; original ledger unchanged |
| CA-TEST-SEC-005 | Seed secrets/identifiers in source, error, prompt, audit, export and tombstone paths | No canary in accepted durable/output/egress artifacts; failed-run logs equally covered |
| CA-TEST-SEC-006 | Synthesis disabled; unapproved, stale/revoked or wrong-destination policy; redirect/URL/metadata detour; approved synthetic-only route if later authorized | Effective network deny and broker decision evidence; no request bytes leave denied route; separate approval reference for any allowed external test |
| CA-TEST-SEC-007 | Change fixture/truth/rule/scorer/manifest; conflicting duplicate; cross-run citation/FK; concurrent seal; authorized expiry versus tamper | Integrity conflict/constraint evidence; frozen result unchanged; expiry explicitly incomplete rather than false corruption/success |
| CA-TEST-SEC-008 | Authorization, schema, policy, output, truth/version and lifecycle failures; purge retry | Typed correlated audit records, safe actor aliases and timestamps; no sensitive payload/token |
| CA-TEST-SEC-009 | At/above byte/record/cardinality/window/retry/model-output limits; pagination/backpressure and API capacity | Bounded termination; explicit reject/truncate gap; measured counts/timings; no silent dropped evidence |
| CA-TEST-SEC-010 | Denied/invalid/expired inputs, provider timeout, database/scorer failure, lifecycle race | Affected capability fails closed; deterministic evidence retained when permitted; no false confirmed cause or unlimited retry |
| CA-TEST-SEC-011 | Dependency/artifact drift, missing build provenance, scanner finding, unpinned local model artifact | Future build is ineligible without approved pin/scan/provenance evidence; no implementation artifacts exist yet |
| CA-TEST-SEC-012 | Model/user forges approval; passing score/merged docs labelled as release authorization | No approval mutation endpoint; report labels separate conformance and approval; named authority/reference required outside model |

## Significant residual risks

- CA-RISK-001/002: semantic causal overstatement and prompt injection remain possible; the design constrains supported output to deterministic assertions but cannot certify arbitrary prose.
- CA-RISK-003/004: uncertain clocks, lost watch history and missing ConfigMap checkpoints can prevent causal attribution. Abstention is a required outcome, not a defect to hide.
- CA-RISK-005: read-only telemetry can contain secrets; field filtering occurs after source access. External provider control and retention cannot be assumed from API configuration.
- CA-RISK-006/007: corpus overfitting, compromised ground truth, scorer bias and privileged manifest rewriting remain possible. Held-out independent review and role separation are still unproven.
- CA-RISK-010: no named approval authorities or executed security evidence exists; documentation merge cannot accept these risks.
- CA-RISK-011: unbenchmarked limits, a non-enforcing kind network configuration or expensive parser/model inputs can exhaust the environment. Effective controls must be demonstrated before gate use.

No risk is accepted or downgraded by Phase 1C. Security review must confirm likelihood/impact, evidence and authorized disposition before future sign-off. A High/Critical finding, new source/privilege, remote deployment, external provider, backup destination or changed data classification triggers architecture and threat review.
