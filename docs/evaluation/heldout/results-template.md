# Held-out evaluation results — `<<FILL: run label>>`

Copy this template for each scored run. Fill every field from `results.json` and the custody records. Delete no rows; a case that could not be scored stays in every table with its class. No pass/fail threshold applies.

## Identity and custody

| Item | Value |
|---|---|
| Candidate commit | `c21b50dc5edd6cd07de55d2f3e0bce6103b4d952` |
| Engine / scorer versions | `<<FILL>>` / `<<FILL>>` |
| Kit commit and version | `<<FILL>>` / `ca-heldout-kit/0.2` |
| Seal digest and publication reference | `<<FILL>>` |
| Predictions aggregate and publication reference | `<<FILL>>` |
| Truth SHA-256 per family (revealed at scoring) | `<<FILL>>` |
| Author / reviewer / executor | `<<FILL>>` |
| Truth commitment confirmed by author and reviewer copies | `<<FILL: yes/no per family>>` |
| Any early exposure of truth, fixtures or results | `<<FILL>>` |

## Every variant

| Family | Variant | Execution | Primary class | Flags | Expected outcome | Engine outcome / recorded reasons | Selected change (`source_ref`) | Run state (expected / actual) | Replay |
|---|---|---|---|---|---|---|---|---|---|
| CA-SCENARIO-008 | `<<FILL>>` | | | | | | | | |
| CA-SCENARIO-009 | `<<FILL>>` | | | | | | | | |
| CA-SCENARIO-010 | `<<FILL>>` | | | | | | | | |

## Counts (all sealed variants in every denominator)

| Measure | Engine | Naive baseline |
|---|---|---|
| Result correct | `<<n/N>>` | `<<n/N>>` |
| Correct cause on resolvable variants | `<<n/N>>` | `<<n/N>>` |
| Justified abstention on unresolvable variants | `<<n/N>>` | `<<n/N>>` |
| Unnecessary abstention on resolvable variants | `<<n/N>>` | `<<n/N>>` |
| False cause selected (identity-verifiable traps) | `<<n/N>>` | `<<n/N>>` |
| False-cause trap identity unverifiable | `<<n/N>>` | `<<n/N>>` |
| Required-evidence recall (per variant) | `<<FILL>>` | — |
| Execution failed / not run / scoring failed | `<<n / n / n>>` | — |

Copy the frozen scorer's `scorer_summary_of_scored_variants` verbatim as an appendix. It covers scored variants only, so failed and not-run variants must also appear in the counts above.

## Successes

`<<FILL: cases the candidate handled correctly, with artifact references>>`

## Failures

`<<FILL: every incorrect, unnecessary or unexpected outcome, failed execution and mismatch flag, with artifact references>>`

## Mechanisms the candidate cannot evaluate

| Family / variant | Category (label / not evaluable / evidence kind) | Quoted artifact evidence | Resulting class |
|---|---|---|---|
| `<<FILL>>` | | | |

## Adversarial and security assertions

`<<FILL: hostile evidence handling, synthesis rejections, prohibited output keys, security policy results>>`

## Deviations

`<<FILL: defects found after sealing, integrity failures, or "none">>`

## Limitations and independence

`<<FILL: independence statement per evaluation-process.md; size of the corpus; exposure status>>`

This is exploratory evaluation evidence. It does not approve any SSDLC gate, ADR or acceptance criterion, and the three families are retired as held-out once this report is published.
