# Initial comparative benchmark protocol (Proposed)

Owner: Evaluation engineer. Approval: product + independent evaluation/gate reviewer + security reviewer. Decisions CA-DEC-003/004/006/007/008. Trace CA-FR-003/004/005/006/008/009/010/011/013; CA-NFR-001/007/008/009; CA-SEC-001 through CA-SEC-012. No benchmark runner, fixture workload, model or comparator has been installed or executed for this plan.

## Questions and experiment arms

Primary questions: does deterministic reconstruction improve supported mechanisms, false-cause rejection and appropriate abstention at matched evidence access; does adding constrained AI improve explanation utility without changing authoritative causal output; and what evidence/maintenance cost distinguishes Cloud Autopsy from existing approaches? Do not assume a favorable result.

| Arm | Proposed configuration | Role and restrictions |
|---|---|---|
| CA-BENCH-B0 | Simple versioned temporal-correlation heuristic | Diagnostic floor to expose distractors, not the sole competitive baseline; no claim that this represents existing tools |
| CA-BENCH-B1 | Cloud Autopsy deterministic engine, synthesis disabled | Primary product baseline; frozen evidence, versioned rules, no truth access or live fetch during reconstruction |
| CA-BENCH-B2 | B1 plus bounded local-model explanation and deterministic fact validator | AI-assistance ablation; same bundle/ledger as B1; compare extra unsupported text, explanation utility and overhead |
| CA-BENCH-B3 | K8sGPT analyzers without explanation | Existing non-AI Kubernetes diagnostic comparator; supported input/schema scope recorded |
| CA-BENCH-B4 | K8sGPT with pinned local backend and reviewed analyzer configuration | Existing AI-assisted comparator; no external provider, broad operator mode or unreviewed cache/permissions |
| CA-BENCH-B5 | HolmesGPT with pinned local backend and explicitly allowed read-only toolsets | Existing investigation agent; isolated credentials/network, bounded tool calls, complete tool transcripts; disable mutations/arbitrary execution before use |
| CA-BENCH-B6 | Fixed Prometheus/log queries and investigator dashboard checklist | Existing workflow reference; rules-only outputs evaluated separately from any later human timing study; human expertise and task order require control |

Exact tool/image/model weights, licenses, prompts, backend compatibility and hardware are not selected. Current research releases are not automatic pins. A comparator that cannot safely operate under the approved boundary is “not evaluated — capability/security constraint,” not a zero-accuracy result. Publish that limitation. Never relax product permissions solely to make an agent comparison work.

## Two separate comparison tracks

1. **Matched-evidence reasoning track:** deliver semantically equivalent frozen observations, query results and metadata to each compatible arm through reviewed adapters. Log the full evidence visible to each arm. Preserve source facts/uncertainty/gaps; never provide Cloud Autopsy's hypotheses, derived causal assertions or truth labels to competitors. If a native tool cannot consume equivalent inputs without material alteration, mark it incompatible with this track and use the other track; do not silently rewrite the tool and call the result native.
2. **End-to-end acquisition track:** reset an identical isolated synthetic environment per trial, schedule the same fault/observation windows, and allow each approved tool its declared read-only source access. Report evidence recall/coverage, collection cost and reasoning outcomes separately. Live-tool access differences are recorded confounders, not evidence of reasoning superiority.

Do not pool tracks or compare matched-input latency with live-acquisition latency. For AI arms, use the same local model/runtime/context limits where natively supported and report any difference; otherwise stratify rather than attribute results solely to architecture. Model hardware is measured separately from the provisional deterministic 4-vCPU/8-GiB reference. No assumption is made that a chosen model fits that reference machine.

## Corpus, truth and leakage prevention

Use the [ten-family corpus plan](../../scenarios/corpus-plan.md), within the required 8–12 independent-family range. Families 001–007 are development/calibration; 008–010 are held out under independent custody. Scenario 001 variants A–E qualify the harness only and count as one family. Specify each scenario's mechanism, expected observations, non-causal distractors, gap/clock/injection variants, assessability, reset criteria and permitted sources before execution. Include benign/no-cause cases and cases where abstention is the correct answer.

Ground-truth author cannot solely approve truth or scorer. Freeze fixture/truth/scorer/policy/config hashes before scoring; keep truth and fault-injection labels out of source messages, prompts, engine inputs and telemetry names. Replace any held-out case exposed to tuning. Freeze final quality thresholds and exclusions after development calibration but before running the held-out gate. A safety/gate change after results creates a new version and a fresh evaluation, not a retroactive pass.

## Execution and proposed sample plan

First qualify scenario 001 A–E across B1, integrity/tamper, expiry and malicious-input cases; failures block scaling the benchmark. Then run every approved arm over the same selected full-corpus cases with randomized arm order and recorded environment resets. Proposed initial quality sample: one baseline run plus two repeat/permuted-delivery runs per deterministic case; five independent attempts per AI case, with seeds/settings recorded where available. Variant and family counts remain separate. These counts are provisional feasibility choices for review, not a power calculation or gate budget.

For proposed performance characterization, use three declared warmups and 30 measured repetitions per approved reference workload/arm that is safe to run; report cold-start separately and define p95 by nearest-rank before measurement. Record CPU/RAM, disk, concurrency, input records/bytes, stage timings, tool calls, model tokens, truncation, network bytes and failures. Apply reviewed finite deadlines/retries/output limits first; a timeout is retained as an outcome. No benchmark sends telemetry to an external provider without separate egress/security approval, including comparator runs.

## Metrics and denominators

| Metric | Definition / interpretation |
|---|---|
| Required-evidence recall | Required observable fixture facts acquired / required observable fixture facts within approved source scope; report out-of-scope requirements separately |
| Citation-ID validity | Valid same-bundle evidence IDs / all cited IDs; measures identifier membership only. Missing native citation support is capability N/A, not fabricated citations |
| Supported factual-claim rate | Independently adjudicated supported factual claims / all emitted factual claims, including unsupported explanation text; report aggregate and per-family rates |
| Causal attribution accuracy | Correctly supported declared mechanisms / assessable cause-required cases, using the blinded mechanism rubric; correct entity alone is insufficient. Report missing/failed outputs and justified abstention separately |
| False-cause selection | Trials confirming a declared non-causal distractor / assessable false-cause-trap trials; expose counts and every selected distractor |
| Abstention correctness | Correct abstentions / designated unresolvable cases; additionally report unnecessary abstentions / resolvable cases and resolution coverage so blanket refusal cannot win |
| Unsupported confirmed cause | Count of confirmed causal statements lacking required mechanism evidence; any such case is visible independently of aggregate support |
| Deterministic equivalence | Equivalent canonical bundle/ledger digests / eligible identical versioned-input repeat pairs; model wording excluded. Unsupported comparator replay is capability N/A |
| Security and integrity | Counts of mutation attempts/successes, forbidden tool/egress attempts, canary propagation, undetected tamper and false approval claims; rejected malicious attempts still recorded |
| Replay completeness | Counts of complete-equivalent, incomplete-expired/deleted, missing-unexplained, integrity-mismatch and unavailable-metadata outcomes against expected lifecycle state |
| Latency and cost | Per-stage median/p95, total, failures/timeouts, evidence bytes, model/tool overhead and hardware; no unpriced “cost savings” claim |

Zero denominators are N/A with count zero, never 100%. Record unsupported, empty, failed and unparseable outputs without dropping trials; structural failure is a separate rate and cannot improve claim-support by emitting nothing. Native outputs lacking citation IDs can still receive blinded fact/mechanism scoring against common truth, with citation/replay capability reported separately. Fixed extraction/adjudication rules cannot supply citations or causal facts absent from the tool's output.

Two independent scorers adjudicate factual/mechanism labels on tool-blinded outputs where practical; record disagreements and a preappointed adjudicator. Publish family-level paired differences and counts. Use family-clustered intervals only when justified by the small sample; repeated model runs/variants are not independent incident families. Ten synthetic families are exploratory evidence, insufficient for broad population-level superiority, commercial MTTR or guaranteed-safety claims. If held-out results inform tuning, they cease to be held out for the next claim.

## Run artifact and gate disposition

Each result links arm/tool/image/model/prompt/adaptor versions; scenario/variant/truth/scorer digests; exposed-evidence manifest; permissions/network policy; hardware and limit policy; raw safe output/tool transcript; machine/human score report; failure/exclusion reason; stage timings and reviewer/adjudication references. Keep artifacts under approved retention and safe-output rules. Preserve failed runs and all retries.

CA-DEC-006's historical 70% and stricter proposed quality targets, and CA-DEC-007's performance/capacity numbers, remain provisional. First calibrate on development cases, obtain explicit scoped gate approval, freeze the independent protocol, then execute the gate corpus. Passing documentation checks or observing zero failures in a finite sample is not product/security sign-off. Under the current proposed security gate any unresolved Critical/High finding blocks passage; changing that policy requires a new explicit decision, not implicit risk acceptance.
