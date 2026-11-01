# Independent held-out evaluation process

Exploratory evaluation of frozen candidate `c21b50dc5edd6cd07de55d2f3e0bce6103b4d952`. The reporting rules on this page are fixed when the seal is published and are not changed after any result is seen.

## Execution

1. The executor creates a clean worktree at the candidate. `run` refuses a different `HEAD` or any local change:

   ```bash
   git worktree add <ENGINE> c21b50dc5edd6cd07de55d2f3e0bce6103b4d952
   ```

2. Run every sealed family and variant. Fixture archives are verified against the seal first; a family that fails verification is reported as `not_run`, never repaired:

   ```bash
   python -I tools/heldout/heldout_kit.py run --engine-root <ENGINE> --seal evaluation-seal.json --fixtures CA-SCENARIO-008=<dir> --fixtures CA-SCENARIO-009=<dir> --fixtures CA-SCENARIO-010=<dir> --out <PRED> --record-out <PRED>.freeze.json
   ```

   Each variant runs offline with synthesis as declared by the fixture; no network, cluster or model is used. An exception in a variant is recorded in `execution-log.json` and the remaining variants continue. A family whose archive cannot be verified (changed, malformed, linked or missing files) is recorded with every sealed variant `not_run` and the other families still run. A variant whose file references a file outside the sealed set (for example a synthesis stub) is `not_run` with reason `variant_references_unsealed_file`; a variant with a malformed `synthesis` block or a non-string `stub` is `not_run` with reason `variant_file_malformed`, and the other variants and families still run. Retained-input replay is run for each completed variant.

3. Publish `<PRED>.freeze.json`, the predictions record, before any truth is released.

## Scoring

The reviewer scores with their own truth copy after the predictions record is public:

```bash
python -I tools/heldout/heldout_kit.py score --engine-root <ENGINE> --seal evaluation-seal.json --predictions <PRED> --predictions-record <PRED>.freeze.json --truth CA-SCENARIO-008=<truth.json>,<salt.hex> --truth CA-SCENARIO-009=... --truth CA-SCENARIO-010=... --out results.json
```

`score` re-verifies the predictions, opens each truth commitment, and passes the truth to the frozen scorer through a temporary pin file outside the repository. Results are driven by the seal, not the execution log: a sealed variant missing from the log is `not_run`. If a family's truth is not supplied, stored inside a Git work tree, unreadable, does not match its commitment or is not strict JSON, every executed variant of that family is `scoring_failed` with `detail.stage` `truth_not_supplied`, `truth_custody`, `truth_open`, `truth_commitment` or `truth_parse`; only the stage and error type are recorded, never truth content, and the other families are still scored. The frozen scorer computes the per-variant metrics and its own summary. The author then confirms that the revealed `truth_sha256` matches their copy.

## Reporting classes

Each variant receives exactly one primary class. Denominators always include every sealed variant.

| Primary class | Definition |
|---|---|
| `correct_attribution` | Resolved, and the exact causal change (`source_ref`) matches truth |
| `incorrect_attribution` | Resolved when a cause was expected, but the change differs from truth |
| `change_identity_unverifiable` | Resolved, but the named change could not be tied to sealed evidence; never credited |
| `justified_abstention` | Abstained where truth expects abstention |
| `unnecessary_abstention` | Abstained where truth expects a resolved cause |
| `resolved_when_abstention_expected` | Named a cause where truth expects abstention |
| `execution_failed` | The candidate raised or produced no artifacts; counts as not correct |
| `not_run` | The fixture archive failed verification, the variant references an unsealed file, or the variant is missing from the execution log; counts as not correct |
| `scoring_failed` | The truth or scorer could not process the case; reported as a defect and never repaired after results |

Flags (any number per variant): `false_cause_selected`, `run_state_mismatch`, `gap_mismatch`, `synthesis_status_mismatch`, `abstention_reason_mismatch`, `security_policy_fail`, `clock_order_mismatch`, `truth_mechanism_label_outside_development_vocabulary`.

## Mechanisms the candidate cannot evaluate

Report these separately and keep them in every denominator:

1. **Label outside vocabulary.** The truth's `mechanism` is not one the candidate can output (flag above). No run of the candidate can be credited, and the report says so explicitly.
2. **Change observed but not evaluable.** After scoring, the reviewer inspects only the frozen prediction artifacts (`bundle.json` ledger) for the true causal change. The reviewer records whether a hypothesis exists for it, and quotes any prerequisite the candidate marked unsatisfied, blocked or unmapped, with the reason it recorded.
3. **Evidence kind not interpreted.** An observation kind or attribute that was required for the cause but never appears in any hypothesis's cited evidence.

Each item lists the variant, the quoted artifact evidence, and whether the result was an abstention or a wrong attribution. "Unsupported" never converts a failure into an exclusion.

## Abstentions, partial results and failures

- **Abstentions**: report the candidate's recorded reasons verbatim beside the expected outcome.
- **Partial runs**: report expected versus actual run state and gaps.
- **Synthesis**: report the expected versus actual synthesis status and rejection reasons.
- **Failed executions**: report the error type and message from `execution-log.json`, and replay failures.
- **Integrity failures**: these are not result mismatches. Report every seal or verification failure verbatim.

## Thresholds

No acceptance threshold exists for this evaluation, and none may be introduced after results are seen. The corpus plan keeps all quality metrics and thresholds provisional until separately approved. Report raw counts with denominators. A zero denominator is `not_evaluated`, never 100%.

## <a id="defects-found-after-sealing"></a>Defects found after sealing

If the author, reviewer or executor finds an error in fixtures, truth or metadata after sealing:

- Do not edit the sealed material.
- Score and report the case as sealed. Add an entry under "Deviations" in the results report giving the defect, who found it, when, and whether it was found before or after seeing results.
- A corrected version is a new family version with a new seal and a new execution. Report both runs; neither replaces the other.

## Independence statement for the report

State who authored the scenarios and truth, who reviewed and held the truth, who executed, and whether anyone saw truth or results early. If the author had any exposure to restricted material, the family is reported as **not independent**.
