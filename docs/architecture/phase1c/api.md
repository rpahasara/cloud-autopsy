# Initial API and component integration contracts (Proposed)

Owner: Architecture lead. Issues #2/#4/#5/#6/#7/#8/#10. Trace CA-FR-001/002/004/005/006/007/008/010/011/012/013/014; CA-NFR-003/005/006/009/010; CA-SEC-001/002/004/006/007/008/009/010/012. This is a contract proposal, not implemented endpoints, generated stubs or a final OpenAPI specification.

## Exposure, authorization and versioning

Propose `/v1` over authenticated loopback HTTP or a protected local socket. Bind to loopback only, reject unexpected Host/Origin, disable permissive CORS and never expose bearer tokens to a webpage or store them in Git. A random per-session credential is provisioned outside source control to the trusted investigator client; exact secure storage/rotation is an open approval question. No anonymous health response exposes configuration. Remote access requires a new reviewed identity/TLS boundary and is out of scope.

Scopes are investigator.read, investigator.run, evaluator.score and lifecycle.delete; they map to provisioned identities, never a body field. Every object read/write checks scope and run ownership even in this single-operator prototype. Tokens cannot grant product/security approval. Inputs name registered scenarios, source plans and policy versions, not arbitrary hosts, commands, SQL, queries or prompts. Strict JSON schemas reject unknown fields and duplicate keys. API paths and envelopes carry schema versions; unsupported versions return explicit incompatibility rather than coercion. No cluster write or general execution endpoint exists.

## Proposed public control contracts

| Operation | Request / scope | Success | Error and integration behavior |
|---|---|---|---|
| POST /v1/investigations | investigator.run; scenario ID/version, UTC start/end, source_plan_id, synthesis_mode disabled/local, Idempotency-Key | 202: investigation_id, run_id, state queued, Location | 400 malformed; 401 unauthenticated; 403 scope/plan/egress denial; 409 key reused with different body; 422 unsupported scenario/window/version; 429 capacity bound |
| GET /v1/investigations/{id} | investigator.read and authorized ownership | 200: scope, run references and explicit states | 404 absent or unauthorized object without disclosing existence; never return raw credentials |
| GET /v1/runs/{id} | investigator.read | 200: stage, acquisition status, partial reasons, synthesis status, timings, manifest digest if sealed | Pending stages are states, not fabricated empty results |
| GET /v1/runs/{id}/bundle | investigator.read; bounded cursor and page size | 200: sealed membership, evidence summaries, gaps, hypothesis ledger, schema and manifest versions | 409 not sealed; unavailable payloads represented explicitly; pagination tied to manifest digest, never live offset |
| GET /v1/runs/{id}/claims | investigator.read | 200: validated and explicitly unsupported/rejected counts, safe claims and limitations | Rejected raw model content omitted by default; inaccessible payload availability is explicit |
| GET /v1/runs/{id}/export | investigator.read; format json or inert text | 200: filtered versioned report with lifecycle/approval limitations | No remote assets/active HTML; expired artifacts remain explicit references; exports join deletion inventory |
| POST /v1/runs/{id}/replays | investigator.run; expected manifest digest, replay mode retained_only, Idempotency-Key | 202 new linked attempt | 409 version/integrity conflict; 410 required inputs expired/deleted with typed replay status; never silent source refetch |
| POST /v1/runs/{id}/cancel | investigator.run; expected state_version | 202 cancellation requested or 200 already stopped | 409 incompatible terminal state; cancellation does not purge or overwrite sealed results |
| POST /v1/runs/{id}/scores | evaluator.score; registered scorer/truth digests, expected sealed result digest, Idempotency-Key | 202 evaluator job then immutable score_report | 403 truth access denied; 409 digest conflict; 422 unsupported scorer/truth; no overwrite of prior reports |
| POST /v1/lifecycle/deletions | lifecycle.delete; registered authorization reference, scoped artifact/run IDs, reason, Idempotency-Key | 202 deletion_request_id and deadline | Deny unverifiable/stale authority; no endpoint can create approval. Do not reveal payload in receipt; completion is audited separately |

External synthesis mode is intentionally absent from the initial public enum. A separately approved contract/version amendment, broker policy and credentials would be required to expose it. DELETE is not used as a synonym for cluster mutation; lifecycle deletion is local data handling under separate identity and policy.

Example synthetic request and accepted response (illustrative IDs only):

```json
{
  "scenario_id": "CA-SCENARIO-001",
  "scenario_version": "0.3.0-draft",
  "window": {"start": "2026-11-01T08:00:00Z", "end": "2026-11-01T08:45:00Z"},
  "source_plan_id": "ca-synthetic-plan-v1",
  "synthesis_mode": "disabled"
}
```

```json
{
  "contract_version": "ca-control/1",
  "investigation_id": "opaque-investigation-id",
  "run_id": "opaque-run-id",
  "state": "queued",
  "approval_status": "not_approved"
}
```

## Shared errors and replay outcomes

Error envelope: contract_version, request_id, error.code, safe message, retryable boolean, run_id if authorized, details with non-sensitive field errors and current state_version. Propose stable codes AUTH_REQUIRED, POLICY_DENIED, INPUT_INVALID, LIMIT_EXCEEDED, VERSION_UNSUPPORTED, IDEMPOTENCY_CONFLICT, STATE_CONFLICT, INTEGRITY_MISMATCH, SOURCE_PARTIAL, SYNTHESIS_UNAVAILABLE, INPUT_EXPIRED and INPUT_DELETED. Never return raw source/model responses, endpoint credentials or stack traces.

Run-level 200 responses can describe partial results; status fields are mandatory. A replay that cannot start due to expired inputs returns 410 with `incomplete_expired` or `incomplete_deleted`, linking the authorized minimal manifest/tombstone. Unexpected absence uses `missing_unexplained`; mismatched bytes use `integrity_mismatch`, distinct from policy denial. After metadata expiry use `replay_unavailable_metadata_expired` only when a retained authorized lifecycle receipt establishes that state; otherwise return not-found with no claim of known expiry. The [lifecycle contract](../../evidence-lifecycle.md) remains authoritative.

## Internal typed interfaces

| Contract ID / flow | Required envelope | Invariants |
|---|---|---|
| CA-CON-001 / F1–F2 RunPlan v1 | run ID, scope, source/query registry versions, window, finite limit policy, expected sources, schema/rule digests, synthesis mode | Coordinator signs off plan by authenticated policy context; collector does not accept raw investigator URL/query strings |
| CA-CON-002 / F3–F5 AcquisitionBatch v1 | run/source/acquisition ID, batch key, schema version, query ID, observations, cursor, coverage, source outcome, truncation and safe error code | Sender authenticated as collector; validate source against plan; bounded atomic ingest/cursor commit; conflicting duplicates rejected |
| CA-CON-003 / F6–F7 FrozenInput v1 | manifest digest/bytes, exact evidence IDs/digests, availability generation, gap-policy and rule versions | Verify integrity/current availability; no late additions; engine cannot fetch sources or truth |
| CA-CON-004 / F8–F10 SynthesisInput/Output v1 | bundle digest, minimized assertions, ledger/gaps; candidate claims and evidence/assertion keys | No tool/action/approval fields; broker route policy checked; validator binds result to original bundle, rejects replayed response for another digest |
| CA-CON-005 / F11 DeterministicResult v1 | input digest, ordered relationships, gaps, hypotheses, deterministic content digest, partial/failed reasons | Engine-only write; idempotent immutable publication; no model override of statuses |
| CA-CON-006 / F12–F14 ScoreInput/Report v1 | sealed result digest, scenario/truth/scorer versions, complete outcome/count/denominator fields, exclusions and errors | Evaluator-only truth access; append results including failures; no post-result threshold substitution |
| CA-CON-007 / F15 LifecycleCommand/Event v1 | authorized artifact scope, policy/reference, expiry/reason, expected lifecycle generation, purge state | Lifecycle-only authority; idempotent unavailable/tombstone transition before deletion; failures trigger retry/audit |
| CA-CON-008 / F16 ResultView v1 | manifest/result versions, safe evidence/provenance references, gaps, claim labels, payload availability and approval_status | Role-filtered read model; inert text; no secrets or implicit approval; bounded pages bound to immutable manifest |

All messages carry contract_version, request/run correlation, sender identity established outside the body, payload digest and safe failure code. Component identity comes from authenticated channel/process credentials, not an untrusted sender_name string. Local in-process calls preserve the same validation contracts; future network splits require authenticated encrypted channels and renewed review.

Delivery is at-least-once with receiver-enforced idempotency, not a promise of exactly-once transport. Idempotency scope is principal + operation + key; store body digest and outcome atomically with operation acceptance. Same key/same request returns original identity; changed request yields 409. Key retention must cover the maximum configured retry horizon and lifecycle policy; exact horizon remains an open design question. Bounded stage deadlines and retry ceilings come from approved policy; no automatic unlimited retry after integrity/auth failures. Backpressure stops intake and exposes partial coverage. After crash, recover only declared leases/states and verify sealed manifests before reuse.

## Required integration verification

CA-TEST-NFR-005 checks independent component contracts; CA-TEST-NFR-010 checks supported/unsupported schemas and migrations; CA-TEST-NFR-003 covers collector/database/scorer/model failure; CA-TEST-SEC-007 covers conflicting duplicates and mismatched digest; CA-TEST-SEC-009 covers limit/backpressure behavior; CA-TEST-SEC-012 verifies no API can fabricate approval. Examples are review data only. No endpoints or integration tests have been implemented.
