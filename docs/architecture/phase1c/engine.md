# Deterministic investigation-engine design (Proposed)

Owner: Architecture lead. Decisions: CA-DEC-002/003/005/006/007. Issues #2/#3/#5/#6/#8/#9. Trace: CA-FR-002 through CA-FR-006, CA-FR-008 through CA-FR-013; CA-NFR-001/002/003/005/006/008/009/010; CA-SEC-007/009/010. [Data model](data-model.md) defines persisted state; [API contracts](api.md) define boundaries.

## Versioned pipeline and determinism boundary

1. Validate the scenario, source/query allowlist and finite bounds before acquisition. Preserve typed acquisition outcomes.
2. Reject malformed/oversized or duplicate-key input. Normalize source-qualified observation identity and immutable evidence records. Canonicalization version defines Unicode treatment, UTC representation, object-key order, explicit nulls, array semantics and decimal representation; reject NaN/infinity. Never derive identity by locale-dependent text sorting or floating-point display.
3. Freeze the exact evidence membership, expected-source inventory, rules, schema, fixture and configuration digests into an immutable manifest. Late observations produce a linked new attempt. No background live query is permitted during deterministic replay.
4. Build time intervals, entity/ownership/config-consumption relationships and explicit source-coverage gaps. Every derived record names input evidence and rule version.
5. Enumerate only scenario-declared candidate mechanisms; evaluate support, contradiction and missing prerequisites. Persist the entire ledger, including unresolved and rejected candidates.
6. Publish a deterministic bundle with stable IDs, ordered presentation, typed limitations and validation status. Optional synthesis cannot mutate this bundle. Scoring occurs later with independently protected ground truth unavailable to the engine.

The deterministic digest includes ordered evidence IDs/digests, relationship/gap/hypothesis values and rule/config versions. Exclude wall-clock run times, run UUID, audit IDs, lease timing, provider latency and model narrative. Publish the exclusion list in the manifest. A model's output is not reproducible merely because temperature or a seed is fixed. Duplicate ingest/retry must not duplicate evidence or alter ordering. A version mismatch is explicit incompatibility, never a silently upgraded replay.

## Time and clock-skew rules

Store original timestamp text, parsed UTC if valid, source clock domain, timestamp type, precision, declared offset and its provenance, observation time and ingestion time. Define offset as `source clock - reference clock`; a declared correction subtracts this offset without replacing the original. A trusted uncertainty bound produces an interval around corrected time incorporating precision and offset uncertainty. Compare intervals: A may precede B only when A's upper bound is strictly less than B's lower bound. Overlap, unknown bounds or unreliable clocks produce unordered/ambiguous status.

CA-DEC-003's ±2-second unknown-precision heuristic and 2/30-second offset flags are provisional fixture heuristics, not assurance that unknown clocks lie within those bounds. When clock uncertainty is unbounded, keep temporal order unknown; do not assign a bounded interval solely to make causal scoring work. Fixture-declared skew is distinguished from measured or guessed skew. Stable evidence-ID ordering breaks display ties only. Kubernetes resourceVersion, arrival order and ingestion time cannot establish cross-source causality.

## Gaps and partial failure

Each gap has a deterministic ID from run-input digest, expected source/query, type, affected entity/window and detector-rule version. Explicit types: missing, failed, out_of_scope, unverifiable, truncated, expired. Status also preserves authorization denial, rate limit, invalid schema and continuity loss as reason codes. A clean empty response proves only that the declared query returned no observations within its coverage, not that an event never occurred.

Before confirming a supported mechanism, intersect its required evidence windows with acquisition coverage and lifecycle availability. Unknown or missing consumption/configuration evidence blocks confirmation. A source outage cannot become evidence of absence; expiry cannot become a fresh successful replay. Propagate component failure to partial/failed run state while preserving valid deterministic outputs. Oversized input is rejected/truncated explicitly according to policy, with no hidden downsampling.

## Causal attribution constraints

| Decision point | Required rule | Prohibited shortcut |
|---|---|---|
| Candidate generation | Finite versioned mechanism templates and observable entities | Free-form model-generated causal graph or arbitrary executable rule |
| Supporting relation | Evidence meets a typed predicate with input IDs and rule/version | Treating temporal proximity or same entity name as a mechanism |
| Supported hypothesis | Required causal change, affected-entity/config-consumption link and compatible symptom evidence; no unresolved mandatory gap; contradictions evaluated | A single supporting citation overriding missing prerequisites |
| Contradicting evidence | Retain and expose each failed mechanism predicate or incompatible observation | Deleting contradictory evidence to improve narrative plausibility |
| Best supported | Deterministic rule precedence with explicit ties/limitations | Presenting a score/rank as calibrated causal probability |
| Abstention | Missing, conflicting, unsupported or ambiguous causal prerequisites yield unresolved/abstained status and reason | Selecting a correlated Deployment because ConfigMap evidence was removed |
| Narrative validation | Only approved structured facts can be represented as supported claims | Model promotion from correlation/unresolved to confirmed cause |

For CA-SCENARIO-001, a rollout is correlation evidence only. A supported ConfigMap mechanism needs the declared before/after value or safe equivalent, evidence that affected pods consumed it, and compatible pool-exhaustion symptoms. The fixture fault mechanism and a human ground-truth review establish the scenario's intended truth; the engine must not read that truth while generating a result. Claim wording distinguishes “supported by these observations” from proof of causality in arbitrary real incidents.

## State, replay and measurement

Run states: queued → collecting → sealed → assembling → deterministic_complete or partial; failures may occur at each stage. Optional synthesis has its own disabled/pending/validated/rejected/unavailable state. A partial deterministic run may still publish inspectable evidence; complete synthesis cannot turn it into a complete investigation. Scoring and approval are separate fields, never run states. Cancellation stops future acquisition/model calls and retains available artifacts with explicit cancelled state; retries create linked attempts once a manifest is sealed.

At replay start verify manifest digest, versions, input integrity and current availability. Read and compute within a bounded protected availability window or recheck lifecycle generation immediately before publishing; if deletion wins, return the lifecycle-specific incomplete state and discard disallowed cached payload. No raw-data lock may postpone an authorized deletion beyond its policy. Lifecycle worker marks unavailable before purge, so access checks remain effective even when cleanup fails. Use the states in the [lifecycle contract](../../evidence-lifecycle.md) without silent refetch.

Measure ingestion, assembly, scoring, synthesis and total time separately; record input counts/bytes, truncation and reference environment. CA-DEC-007 numeric budgets remain provisional. CA-TEST-FR-004 compares equivalent bundles across retries and input delivery permutations; CA-TEST-FR-003 covers invalid/missing timestamps, overlap and declared offsets; CA-TEST-FR-009 covers ties/gaps/contradictions; CA-TEST-FR-010 covers every lifecycle replay state. No such tests have run.
