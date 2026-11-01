# Full Phase 1 evaluation corpus plan (Draft)

Owner: Evaluation engineer. Approval: pending product / requirements authority and independent gate review under [CA-DEC-006](../architecture/adr/CA-DEC-006.md). Related work: CA-008 / issue #8 (harness), CA-009 / issue #9 (initial family), CA-010 / issue #10 (full gate review). CA-FR-011 / CA-TEST-FR-011 covers versioned execution/scoring; CA-SEC-007 / CA-TEST-SEC-007 covers frozen-input integrity.

The five CA-SCENARIO-001 variants qualify the initial investigation harness. Passing them cannot pass the full evaluation gate. Plan ten independent scenario families below, within the required 8–12 range; variants do not increase the family count. Only CA-SCENARIO-001 is presently specified. Remaining rows are planned coverage, not built scenarios or test evidence.

| Planned ID | Coverage category | Evaluation split |
|---|---|---|
| CA-SCENARIO-001 | Config change versus correlated rollout; gap, injection, skew and model failure variants | Development / harness qualification |
| CA-SCENARIO-002 | Resource saturation versus correlated scaling change | Development |
| CA-SCENARIO-003 | Dependency outage with contradictory healthy local telemetry | Development |
| CA-SCENARIO-004 | Network/DNS failure versus application rollout | Development |
| CA-SCENARIO-005 | Restart/OOM ordering across clock domains | Development |
| CA-SCENARIO-006 | Benign rollout/no incident; avoid invented causes | Development |
| CA-SCENARIO-007 | Mixed connector outage and evidence expiry; explicit abstention | Development |
| CA-SCENARIO-008 | Unseen causal fault and distractor combination | Held out |
| CA-SCENARIO-009 | Unseen missing/contradictory evidence combination | Held out |
| CA-SCENARIO-010 | Unseen adversarial telemetry and source-identity collision | Held out |

An independent reviewer freezes held-out fixtures, ground truth and scorer versions before scored execution. Authors cannot solely approve their own truth/scorer. Keep held-out material separate from tuning inputs; after inspection or tuning exposure, version and replace it for future generalization claims. Report every family and variant, failed/partial/excluded runs and exclusion reasons. Never remove difficult cases to reach a threshold.

Before full gate use, define each family’s ground truth, source allowlist, mechanism, false-cause and abstention expectations, split, versions and security assertions. Freeze the chosen 8–12 families and aggregation/denominator rules before seeing gate results. Proposed scoring reports both claim-weighted aggregate support (supported factual claims / all factual claims) and per-family support; citation-ID validity is valid in-bundle IDs / all cited IDs. Zero-denominator cases are explicitly not evaluated, never automatically 100%. Benchmark abstention, false-cause, required-evidence recall and deterministic equivalence separately. Repeated performance runs must declare count, warmup and p95 calculation before execution. All quality metrics, thresholds and performance budgets remain provisional until benchmarked and explicitly approved.
