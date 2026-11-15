# CA-P2-007a development-set evaluation (ca-eval-scorer/0.1-provisional)

Scenario file `sha256:970f12fc9109da0c2ddef1ef17bd557cc27e01646a399e3b12e67001875d48e9`. Developer-authored synthetic development set; not independent accuracy certification.

## Acceptance criteria

| Criterion | Value | Met |
|---|---|---|
| P1_correct | 10/10 | yes |
| P2_correct | 10/10 | yes |
| every_negative_abstains | 21/21 | yes |
| zero_false_causes | 0 | yes |
| citations_valid | 41/41 | yes |
| zero_leaks | 0 | yes |
| deterministic_replay | 41/41 | yes |
| no_harness_failures | 0 | yes |

**All criteria met: yes**

## Per scenario

| Scenario | Kind | Attempted | Correct | Necessary abst. | Unnecessary abst. | False cause | Unsupported | Harness failures |
|---|---|---|---|---|---|---|---|---|
| P1 | positive | 10/10 | 10 | 0 | 0 | 0 | 0 | 0 |
| P2 | positive | 10/10 | 10 | 0 | 0 | 0 | 0 | 0 |
| N1 | negative | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N2 | negative | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N3 | negative | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N4 | negative | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N5 | negative | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N6 | negative | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N7 | negative | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |

## Every run

| Run | Expected | Actual | Reasons | Window narrowed | Refused | Rollout margin (ms) | Citations | Leaks | Replay | DB |
|---|---|---|---|---|---|---|---|---|---|---|
| N1-01 | abstained | abstained | no_supported_hypothesis | True |  | 29 | True | 0 | True | True |
| N1-02 | abstained | abstained | no_supported_hypothesis | True |  | 31 | True | 0 | True | True |
| N1-03 | abstained | abstained | no_supported_hypothesis | True |  | 27 | True | 0 | True | True |
| N2-01 | abstained | abstained | no_supported_hypothesis | True |  | 27 | True | 0 | True | True |
| N2-02 | abstained | abstained | no_supported_hypothesis | True |  | 34 | True | 0 | True | True |
| N2-03 | abstained | abstained | no_supported_hypothesis | True |  | 27 | True | 0 | True | True |
| N3-01 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 30 | True | 0 | True | True |
| N3-02 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 27 | True | 0 | True | True |
| N3-03 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 25 | True | 0 | True | True |
| N4-01 | abstained | abstained | no_supported_hypothesis, no_symptom_observed | True |  | 27 | True | 0 | True | True |
| N4-02 | abstained | abstained | no_supported_hypothesis, no_symptom_observed | True |  | 32 | True | 0 | True | True |
| N4-03 | abstained | abstained | no_supported_hypothesis, no_symptom_observed | True |  | 28 | True | 0 | True | True |
| N5-01 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 29 | True | 0 | True | True |
| N5-02 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 26 | True | 0 | True | True |
| N5-03 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 28 | True | 0 | True | True |
| N6-01 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 26 | True | 0 | True | True |
| N6-02 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 27 | True | 0 | True | True |
| N6-03 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 25 | True | 0 | True | True |
| N7-01 | abstained | abstained | no_supported_hypothesis | True |  | None | True | 0 | True | True |
| N7-02 | abstained | abstained | no_supported_hypothesis | True |  | None | True | 0 | True | True |
| N7-03 | abstained | abstained | no_supported_hypothesis | True |  | None | True | 0 | True | True |
| P1-01 | resolved | resolved |  | True |  | 28 | True | 0 | True | True |
| P1-02 | resolved | resolved |  | True |  | 26 | True | 0 | True | True |
| P1-03 | resolved | resolved |  | True |  | 26 | True | 0 | True | True |
| P1-04 | resolved | resolved |  | True |  | 25 | True | 0 | True | True |
| P1-05 | resolved | resolved |  | True |  | 24 | True | 0 | True | True |
| P1-06 | resolved | resolved |  | True |  | 26 | True | 0 | True | True |
| P1-07 | resolved | resolved |  | True |  | 25 | True | 0 | True | True |
| P1-08 | resolved | resolved |  | True |  | 23 | True | 0 | True | True |
| P1-09 | resolved | resolved |  | True |  | 26 | True | 0 | True | True |
| P1-10 | resolved | resolved |  | True |  | 91 | True | 0 | True | True |
| P2-01 | resolved | resolved |  | True |  | 31 | True | 0 | True | True |
| P2-02 | resolved | resolved |  | True |  | 32 | True | 0 | True | True |
| P2-03 | resolved | resolved |  | True |  | 28 | True | 0 | True | True |
| P2-04 | resolved | resolved |  | True |  | 26 | True | 0 | True | True |
| P2-05 | resolved | resolved |  | True |  | 22 | True | 0 | True | True |
| P2-06 | resolved | resolved |  | True |  | 24 | True | 0 | True | True |
| P2-07 | resolved | resolved |  | True |  | 26 | True | 0 | True | True |
| P2-08 | resolved | resolved |  | True |  | 28 | True | 0 | True | True |
| P2-09 | resolved | resolved |  | True |  | 27 | True | 0 | True | True |
| P2-10 | resolved | resolved |  | True |  | 24 | True | 0 | True | True |

Positive rollout margins after the window start (ms): [22, 23, 24, 24, 24, 25, 25, 26, 26, 26, 26, 26, 26, 27, 28, 28, 28, 31, 32, 91]
Positive runs whose window was not narrowed: 0
