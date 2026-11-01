# AI synthesis, provider isolation and data egress (Proposed)

Owner: Security reviewer with Architecture lead. Decision CA-DEC-004; related CA-DEC-005/006/007/008. Issues #7/#10. Trace CA-FR-007/008/013/014; CA-NFR-003/004/009; CA-SEC-002/003/004/005/006/009/010/012. See TB4/TB5 and F8–F10 in [diagrams](diagrams.md).

## Default and optional paths

Synthesis is disabled in the baseline; the deterministic bundle, ledger and evaluation remain usable. An optional local model is a separate untrusted process, not part of the deterministic engine's trust. No external provider is selected. A configuration flag or product-owner approval alone cannot authorize external access. Provider credentials are unavailable unless a separate data-egress and security approval is recorded and verified by the egress broker.

| Boundary | Proposed control | Failure behavior |
|---|---|---|
| Engine → minimizer | Versioned field allowlist; bundle membership and classification; entity aliases; byte/token ceiling | Deny payload and keep deterministic output |
| Minimizer → prompt assembler | Fixed instruction template; separate data field; JSON serialization; literal escaped hostile strings; no telemetry in system instructions | Contract validation rejection, not prompt concatenation fallback |
| Prompt assembler → model sandbox | No tools, shell, URL fetch, filesystem mount of evidence store, cluster credential, DB access or truth access | Sandbox failure/timeouts mark synthesis unavailable |
| Sandbox → external route | Absent by default; broker validates approval/policy digest, approved provider/region/TLS identity and exact outbound route | Fail closed on missing, changed, expired or revoked approval |
| Model → validator | Strict versioned response schema, finite arrays/strings, declared IDs only; no action/approval/tool fields | Reject entire attempt on structural/policy failure; record typed reason |
| Validator → result | Check same-bundle evidence, fact predicates, hypothesis status and immutable gaps; escaped display text | Unsupported statements labelled/rejected; never set confirmed cause from prose |

## Input and output contract

Input includes run input digest, contract version, allowed evidence IDs, prevalidated fact assertions, uncertainty/gaps, ledger status and a fixed task: explain the supplied ledger with citations and limitations. Do not include ground truth, hidden scorer labels, raw secrets, source credentials, unrelated logs, raw headers, free-form deployment notes or user-supplied policy text. Entity aliases are stable within a run only; the alias mapping stays local with payload retention.

Output candidate contains `contract_version`, `bundle_digest`, `claims[]` with `claim_id`, `kind`, `text`, `evidence_ids[]`, `assertion_keys[]`, and `limitations[]`. `kind` is observed/derived/unresolved; it is not a proposed action. Require additional-properties rejection and hard limits from approved configuration. The response cannot supply new hypotheses, URLs to retrieve, policy changes or approval metadata. Provider-native structured output is an aid, not a substitute for local validation.

Citation ID validity only proves membership. Semantic support needs a deterministic assertion key/rule matching the cited observation and ledger relation; arbitrary free-form entailment cannot be certified with an ID check. Supported text should be rendered from validated structured fact templates. Extra model commentary remains explicitly unverified or rejected and counts as unsupported in evaluation. No retry loop may repeatedly change the prompt until a preferred causal answer appears; use bounded attempts with all rejections retained as minimized events.

## Injection and disclosure defenses

Malicious logs, annotations, deployment messages and model responses remain untrusted even when quoted or delimiter-separated. Defenses combine field minimization, fixed instruction/data separation, serialization, privilege removal, sandbox/route restrictions, schema validation and deterministic fact validation. “Ignore previous instructions” detection is not a security boundary. Test encoded/multilingual instructions, delimiter breakout, impersonated approval, plausible-looking fake citations, executable Markdown/HTML and requested URL exfiltration. Export/render text inertly, disable active HTML and automatic remote image loading, and avoid formula interpretation in any future spreadsheet export.

Egress approval record must name authorizer, scope/version, validity/review trigger, provider/model, destination/region, contractual no-training and zero-retention terms, precise fields, redaction tests and revocation procedure. Recheck it before each request; in-flight data cannot be recalled after revocation, which must be documented as residual exposure. Pin route configuration; reject redirects, model-supplied URLs and cloud metadata/private-address detours. Plain Kubernetes NetworkPolicy is insufficient for provider domain/TLS restrictions; an approved outbound broker and effective network test are required. No approval record exists today.

Provider logs, traces and failed-request bodies can retain data. Disable payload logging and credentials in ordinary audits; store only safe request digest, policy/model/prompt versions, timings and typed outcome under the lifecycle policy. Keep any local prompt/response payload under short retention; no training cache or vector store is proposed. A local model also needs pinned artifacts, dependency review and resource ceilings; local execution does not establish safety.

Residual risks: semantic overstatement, redaction misses, provider/host compromise, network-policy misconfiguration, digest leakage and denial of service. None is accepted. CA-TEST-SEC-002/003/004/005/006/009/010 and CA-TEST-FR-008/013 define required adversarial, canary, egress-denial and failure-preservation evidence; [security requirements](security.md) specify pass artifacts. No provider call or model/security test was performed.
