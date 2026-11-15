# CA-P2-007 development-set evaluation (ca-eval-scorer/0.2-provisional)

Scenario file `ca-eval-timing-matrix/0.1-provisional`, `sha256:27e43de22e6fbd2d482b79bafa96b112071237c625c42ddc45f52b811ed082f1`. Developer-authored synthetic development set; not independent accuracy certification.

Integrity: the records are exactly the pre-registered run set (checked before scoring).

## Acceptance criteria

| Criterion | Value | Met |
|---|---|---|
| every_negative_abstains | 12/12 | yes |
| zero_false_causes | 0 | yes |
| citations_valid | 45/45 | yes |
| zero_leaks | 0 | yes |
| deterministic_replay | 45/45 | yes |
| no_harness_failures | 0 | yes |

**All criteria met: yes**

## Per scenario

| Scenario | Kind | Probe s | Action s | Window s | Rotation s | Prediction | Attempted | Correct | Necessary abst. | Unnecessary abst. | False cause | Unsupported | Harness failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TP01 | positive | 5 | 25 | [20, 140] | 5 | resolve: v0.1 reference; rollout bracket opens at the +20 s probe, about 25 ms inside | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP02 | positive | 5 | 25 | [10, 140] | 5 | resolve: about 10 s of margin | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP03 | positive | 2 | 25 | [20, 140] | 5 | resolve: the latest probe before the rollout is at +22 or +24 s | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP04 | positive | 8 | 25 | [20, 140] | 5 | uncertain: the rollout (about +24 s) races the +24 s probe; if it precedes it, the bracket opens at +16 s and narrowing is refused (abstain) | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP05 | positive | 8 | 25 | [10, 140] | 5 | resolve: the bracket opens at +16 s or +24 s, both inside | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP06 | positive | 5 | 21 | [20, 140] | 5 | uncertain: the rollout (about +20 s) races the +20 s probe; if it precedes it, the bracket opens at +15 s (abstain) | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP07 | positive | 5 | 21 | [10, 140] | 5 | resolve: the bracket opens at +15 s or +20 s, both inside | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP08 | positive | 8 | 21 | [20, 140] | 5 | abstain (unnecessary): the latest probe before the rollout is at +16 s, outside the window | 3/3 | 0 | 0 | 3 | 0 | 0 | 0 |
| TP09 | positive | 8 | 21 | [10, 140] | 5 | resolve: the bracket opens at +16 s, inside | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP10 | positive | 5 | 25 | [20, 140] | 15 | resolve: slower log rotation widens symptom brackets, but symptoms start about 30 s after the rollout | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TP11 | positive | 5 | 35 | [20, 140] | 5 | resolve: later action; the bracket opens at the +30 s probe; symptoms end before +140 s | 3/3 | 3 | 0 | 0 | 0 | 0 | 0 |
| TN01 | negative | 8 | 21 | [10, 140] | 5 | abstain: no typed limit change (false-cause trap) | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| TN02 | negative | 2 | 25 | [10, 140] | 5 | abstain: symptoms precede the change (contradiction) | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| TN03 | negative | 8 | 25 | [10, 140] | 5 | abstain: the change is outside the investigated scope | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |
| TN04 | negative | 2 | 21 | [10, 140] | 5 | abstain: the limit is raised (false-cause trap) | 3/3 | 0 | 3 | 0 | 0 | 0 | 0 |

## Every run

| Run | Expected | Actual | Reasons | Narrowed | Refused | Rollout margin ms | Symptom margin ms | Citations | Leaks | Replay | DB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TN01-01 | abstained | abstained | no_supported_hypothesis | True |  | 6009 | 25107 | True | 0 | True | True |
| TN01-02 | abstained | abstained | no_supported_hypothesis | True |  | 6008 | 25098 | True | 0 | True | True |
| TN01-03 | abstained | abstained | no_supported_hypothesis | True |  | 6008 | 25113 | True | 0 | True | True |
| TN02-01 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 14088 | -19910 | True | 0 | True | True |
| TN02-02 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 14082 | -19911 | True | 0 | True | True |
| TN02-03 | abstained | abstained | contradicting_evidence_present, limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | no_common_verified_interval, unclean_batches, relevant_evidence_outside_incident_window | 14083 | -19906 | True | 0 | True | True |
| TN03-01 | abstained | abstained | no_supported_hypothesis | True |  | None | None | True | 0 | True | True |
| TN03-02 | abstained | abstained | no_supported_hypothesis | True |  | None | None | True | 0 | True | True |
| TN03-03 | abstained | abstained | no_supported_hypothesis | True |  | None | None | True | 0 | True | True |
| TN04-01 | abstained | abstained | no_supported_hypothesis | True |  | 10070 | 25102 | True | 0 | True | True |
| TN04-02 | abstained | abstained | no_supported_hypothesis | True |  | 10067 | 25094 | True | 0 | True | True |
| TN04-03 | abstained | abstained | no_supported_hypothesis | True |  | 10068 | 25101 | True | 0 | True | True |
| TP01-01 | resolved | resolved |  | True |  | 26 | 25109 | True | 0 | True | True |
| TP01-02 | resolved | resolved |  | True |  | 26 | 25116 | True | 0 | True | True |
| TP01-03 | resolved | resolved |  | True |  | 26 | 25075 | True | 0 | True | True |
| TP02-01 | resolved | resolved |  | True |  | 10023 | 25124 | True | 0 | True | True |
| TP02-02 | resolved | resolved |  | True |  | 10025 | 25093 | True | 0 | True | True |
| TP02-03 | resolved | resolved |  | True |  | 10022 | 25105 | True | 0 | True | True |
| TP03-01 | resolved | resolved |  | True |  | 4084 | 25080 | True | 0 | True | True |
| TP03-02 | resolved | resolved |  | True |  | 4085 | 25079 | True | 0 | True | True |
| TP03-03 | resolved | resolved |  | True |  | 4071 | 25104 | True | 0 | True | True |
| TP04-01 | resolved | resolved |  | True |  | 4015 | 25121 | True | 0 | True | True |
| TP04-02 | resolved | resolved |  | True |  | 4015 | 25116 | True | 0 | True | True |
| TP04-03 | resolved | resolved |  | True |  | 4017 | 25110 | True | 0 | True | True |
| TP05-01 | resolved | resolved |  | True |  | 14016 | 25122 | True | 0 | True | True |
| TP05-02 | resolved | resolved |  | True |  | 14015 | 25128 | True | 0 | True | True |
| TP05-03 | resolved | resolved |  | True |  | 14014 | 25106 | True | 0 | True | True |
| TP06-01 | resolved | resolved |  | True |  | 30 | 25111 | True | 0 | True | True |
| TP06-02 | resolved | resolved |  | True |  | 20 | 25109 | True | 0 | True | True |
| TP06-03 | resolved | resolved |  | True |  | 24 | 25106 | True | 0 | True | True |
| TP07-01 | resolved | resolved |  | True |  | 10023 | 25103 | True | 0 | True | True |
| TP07-02 | resolved | resolved |  | True |  | 10027 | 25105 | True | 0 | True | True |
| TP07-03 | resolved | resolved |  | True |  | 10022 | 25094 | True | 0 | True | True |
| TP08-01 | resolved | abstained | limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | relevant_evidence_outside_incident_window | -3989 | 25109 | True | 0 | True | True |
| TP08-02 | resolved | abstained | limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | relevant_evidence_outside_incident_window | -3993 | 25094 | True | 0 | True | True |
| TP08-03 | resolved | abstained | limiting_evidence_gaps, no_supported_hypothesis, unresolved_hypotheses_present | False | relevant_evidence_outside_incident_window | -3991 | 25092 | True | 0 | True | True |
| TP09-01 | resolved | resolved |  | True |  | 6008 | 25094 | True | 0 | True | True |
| TP09-02 | resolved | resolved |  | True |  | 6010 | 25106 | True | 0 | True | True |
| TP09-03 | resolved | resolved |  | True |  | 6009 | 25088 | True | 0 | True | True |
| TP10-01 | resolved | resolved |  | True |  | 23 | -4950 | True | 0 | True | True |
| TP10-02 | resolved | resolved |  | True |  | 22 | -4957 | True | 0 | True | True |
| TP10-03 | resolved | resolved |  | True |  | 23 | -4955 | True | 0 | True | True |
| TP11-01 | resolved | resolved |  | True |  | 10040 | 25102 | True | 0 | True | True |
| TP11-02 | resolved | resolved |  | True |  | 10038 | 25100 | True | 0 | True | True |
| TP11-03 | resolved | resolved |  | True |  | 10043 | 25111 | True | 0 | True | True |

Positive rollout margins after the window start (ms): [-3993, -3991, -3989, 20, 22, 23, 23, 24, 26, 26, 26, 30, 4015, 4015, 4017, 4071, 4084, 4085, 6008, 6009, 6010, 10022, 10022, 10023, 10023, 10025, 10027, 10038, 10040, 10043, 14014, 14015, 14016]
Positive runs whose window was not narrowed: 3
Positive unnecessary abstentions: 3
