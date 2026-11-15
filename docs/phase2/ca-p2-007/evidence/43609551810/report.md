# CA-P2-007 development-set evaluation (ca-eval-scorer/0.2-provisional)

Scenario file `ca-eval-scenarios/0.2-provisional`, `sha256:fecb7c20e1d9e74b6f257ce6f6131ab5cf41ae86b7eaec7ca40fbac5547625a8`. Developer-authored synthetic development set; not independent accuracy certification.

Integrity: the records are exactly the pre-registered run set (checked before scoring).

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

| Scenario | Kind | Probe s | Action s | Window s | Rotation s | Prediction | Attempted | Correct | Necessary abst. | Unnecessary abst. | False cause | Unsupported | Harness failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | positive | 5 | 25 | [10, 140] | 5 |  | 10/10 | 10 | 0 | 0 | 0 | 0 | 0 |
| P2 | positive | 5 | 25 | [10, 140] | 5 |  | 10/10 | 10 | 0 | 0 | 0 | 0 | 0 |
| N1 | negative | 5 | 25 | [10, 140] | 5 |  | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N2 | negative | 5 | 25 | [10, 140] | 5 |  | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N3 | negative | 5 | 25 | [10, 140] | 5 |  | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N4 | negative | 5 | 25 | [10, 140] | 5 |  | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N5 | negative | 5 | 25 | [10, 140] | 5 |  | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N6 | negative | 5 | 25 | [10, 140] | 5 |  | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| N7 | negative | 5 | 25 | [10, 140] | 5 |  | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |

## Every run

| Run | Expected | Actual | Reasons | Narrowed | Refused | Rollout margin ms | Symptom margin ms | Citations | Leaks | Replay | DB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| N1-01 | abstained | abstained | no_supported_hypothesis | True |  | 10015 | 25074 | True | 0 | True | True |
| N1-02 | abstained | abstained | no_supported_hypothesis | True |  | 10017 | 25059 | True | 0 | True | True |
| N1-03 | abstained | abstained | no_supported_hypothesis | True |  | 10019 | 25148 | True | 0 | True | True |
| N2-01 | abstained | abstained | no_supported_hypothesis | True |  | 10017 | 25103 | True | 0 | True | True |
| N2-02 | abstained | abstained | no_supported_hypothesis | True |  | 10015 | 25063 | True | 0 | True | True |
| N2-03 | abstained | abstained | no_supported_hypothesis | True |  | 10019 | 25133 | True | 0 | True | True |
| N3-01 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 10019 | -19923 | True | 0 | True | True |
| N3-02 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 10016 | -19923 | True | 0 | True | True |
| N3-03 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 10016 | -19922 | True | 0 | True | True |
| N4-01 | abstained | abstained | no_supported_hypothesis, no_symptom_observed | True |  | 10018 | None | True | 0 | True | True |
| N4-02 | abstained | abstained | no_supported_hypothesis, no_symptom_observed | True |  | 10018 | None | True | 0 | True | True |
| N4-03 | abstained | abstained | no_supported_hypothesis, no_symptom_observed | True |  | 10018 | None | True | 0 | True | True |
| N5-01 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 10019 | None | True | 0 | True | True |
| N5-02 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 10018 | None | True | 0 | True | True |
| N5-03 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 10017 | None | True | 0 | True | True |
| N6-01 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 10016 | None | True | 0 | True | True |
| N6-02 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 10016 | None | True | 0 | True | True |
| N6-03 | abstained | abstained | limiting_evidence_gaps, no_supported_hypothesis, no_symptom_observed, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches | 10026 | None | True | 0 | True | True |
| N7-01 | abstained | abstained | no_supported_hypothesis | True |  | None | None | True | 0 | True | True |
| N7-02 | abstained | abstained | no_supported_hypothesis | True |  | None | None | True | 0 | True | True |
| N7-03 | abstained | abstained | no_supported_hypothesis | True |  | None | None | True | 0 | True | True |
| P1-01 | resolved | resolved |  | True |  | 10016 | 25068 | True | 0 | True | True |
| P1-02 | resolved | resolved |  | True |  | 10018 | 25118 | True | 0 | True | True |
| P1-03 | resolved | resolved |  | True |  | 10019 | 25125 | True | 0 | True | True |
| P1-04 | resolved | resolved |  | True |  | 10018 | 25095 | True | 0 | True | True |
| P1-05 | resolved | resolved |  | True |  | 10018 | 25073 | True | 0 | True | True |
| P1-06 | resolved | resolved |  | True |  | 10017 | 25124 | True | 0 | True | True |
| P1-07 | resolved | resolved |  | True |  | 10019 | 25082 | True | 0 | True | True |
| P1-08 | resolved | resolved |  | True |  | 10019 | 25127 | True | 0 | True | True |
| P1-09 | resolved | resolved |  | True |  | 10019 | 25093 | True | 0 | True | True |
| P1-10 | resolved | resolved |  | True |  | 10018 | 25078 | True | 0 | True | True |
| P2-01 | resolved | resolved |  | True |  | 10018 | 25109 | True | 0 | True | True |
| P2-02 | resolved | resolved |  | True |  | 10017 | 25065 | True | 0 | True | True |
| P2-03 | resolved | resolved |  | True |  | 10019 | 25087 | True | 0 | True | True |
| P2-04 | resolved | resolved |  | True |  | 10018 | 25078 | True | 0 | True | True |
| P2-05 | resolved | resolved |  | True |  | 10018 | 25118 | True | 0 | True | True |
| P2-06 | resolved | resolved |  | True |  | 10019 | 25125 | True | 0 | True | True |
| P2-07 | resolved | resolved |  | True |  | 10019 | 25084 | True | 0 | True | True |
| P2-08 | resolved | resolved |  | True |  | 10018 | 25113 | True | 0 | True | True |
| P2-09 | resolved | resolved |  | True |  | 10018 | 25136 | True | 0 | True | True |
| P2-10 | resolved | resolved |  | True |  | 10019 | 25099 | True | 0 | True | True |

Positive rollout margins after the window start (ms): [10016, 10017, 10017, 10018, 10018, 10018, 10018, 10018, 10018, 10018, 10018, 10018, 10019, 10019, 10019, 10019, 10019, 10019, 10019, 10019]
Positive runs whose window was not narrowed: 0
Positive unnecessary abstentions: 0
