# Milestone plan: an end-to-end synthetic incident investigation (proposal)

**Status:**
- A documentation-only plan, for product-owner approval. Nothing here is implemented.
- No collector, contract, migration, engine or dashboard change is made until the decisions in [§2](#decisions) are approved.
- It is a planning artifact, not a gate disposition, a specialist approval or a production-readiness claim.

**Base:** `main` at `402531d` (after the [third integration](../integration.md)).

**Goal:** show **real root-cause investigation value** end to end. On a disposable kind cluster, a synthetic incident is caused by a real infrastructure change. Cloud Autopsy collects both that change and the application's symptom evidence, read-only and sanitized, and then:
- stores the evidence;
- replays it deterministically from PostgreSQL;
- resolves the true cause when, and only when, the evidence proves it;
- abstains, with the reason, in every case where it does not;
- shows the result in the existing dashboard.

More evidence collection by itself is not the goal. The milestone is judged by measured outcomes on positive and negative cases ([§9](#evaluation)).

## 1. <a id="today"></a>Where the product stands

**What already works on real collected data** ([004e](../ca-p2-004/ca-p2-004e.md), [004f](../ca-p2-004/ca-p2-004f.md), [005b](../ca-p2-005/ca-p2-005b.md)):
- read-only list and watch collection of Deployments, ReplicaSets, Pods and Events, with sanitizing projections;
- verified coverage and explicit gaps;
- session-scoped `observed` brackets on the collector's own clock;
- rule profile 2, which orders by those brackets;
- write-once result storage, verified on read by exact replay;
- the dashboard.

**Why every real investigation abstains today.** The engine needs three things that real collection does not yet provide:

| Needed by `rollout_limit_reduction` | Today |
|---|---|
| A symptom: a `log_line` with template `POOL_EXHAUSTED` (or an `alert_firing`) | **No symptom source exists.** The only collector source kind is `kubernetes_api`, and `log_line` belongs to source kind `loki`. Result: `no_symptom_observed` |
| A typed limit change: `field_changes` on the rollout, mapped to a catalog key | The collector records changed field **paths** but never values (env values are withheld by design). Result: `no_mechanism_maps_changed_fields` |
| A symptom on the **new** revision's pods, **strictly after** the rollout | Possible in principle with profile 2's observed brackets, but never exercised without a symptom |

**What the demo workload cannot provide.** `checkout-api` runs `registry.k8s.io/pause`, which emits no logs and no metrics and has no endpoint.

**Synthetic results so far are not evidence of real resolution.** The six pinned synthetic variants and the profile-2 positive control resolve on **constructed** symptom evidence. The 005b record states explicitly that this "is not evidence that real collector-only investigations can resolve".

## 2. <a id="decisions"></a>Decisions requested

| # | Decision | Recommendation |
|---|---|---|
| M1 | **Symptom source.** Container logs read through the Kubernetes API (`GET pods/{name}/log`, follow mode), **not** Loki or Prometheus, which would be new infrastructure. Metrics are deferred ([§4.4](#metrics)) | Approve |
| M2 | **RBAC change.** Grant the collector `get` on `pods/log` in the **incident namespace only**. `pods/log` is on today's refusal list. Secrets, ConfigMaps, `pods/exec`, nodes and namespaces stay refused, and the kind RBAC check is updated to prove it | Approve: the one deliberate widening |
| M3 | **Log sanitization by template allowlist.** Raw log lines are never stored. Each line is matched against a pinned template catalog; only the template name and typed, allowlisted fields are kept. An unmatched line is counted, never kept ([§5](#sanitize)) | Approve |
| M4 | **Declared limit keys.** A scope declaration names which container env keys are numeric limits and which catalog key each one maps to (`DB_POOL_MAX` → `pool.maxConnections`). Only those keys' values are read, only if they are plain integers. Every other env value stays withheld, as today | Approve |
| M5 | **Contract additions** (additive; no existing version changes): observation kinds **0.4** (a pod-log source kind for `log_line`, an `observed` time on `log_line`, and an optional `message`); a supported-version migration **`0009`**; collector recording **0.5** | Approve |
| M6 | **Engine scope.** **No new mechanism** and no new ordering rule. Reuse `rollout_limit_reduction` and rule profile 2 as they are. Only input acceptance changes: profile 2 also accepts kinds 0.4 | Approve |
| M7 | **ConfigMap values stay unread.** The ConfigMap path (`config_limit_reduction`) is not exercised on real data in this milestone | Approve |
| M8 | **Workload image.** A digest-pinned `busybox` image runs a short shell script that simulates checkout demand against its pool limit. It is a CI/test image only, inventoried as `build-and-test`, so the product runtime stays standard library only | Approve, or choose `python:3.13-slim` |
| M9 | **Evaluation.** A development-set harness with sealed scenario truth and a product scorer ([§9](#evaluation)). It is explicitly **not** the held-out evaluation, which remains PR #14's job, later ([§10](#independent)) | Approve |

## 3. <a id="incident"></a>The synthetic incident

**Namespace.** A new namespace, `ca-incident`, contains only the incident workload. The noisy `crashy` Deployment stays in `ca-demo`, so every pod in the log scope can actually log.

**Workload (`checkout-api`):**
- reads `DB_POOL_MAX` from its environment at start;
- logs `CONFIG_LOADED key=pool.maxConnections value=<n>`;
- runs a deterministic synthetic demand schedule, chosen per scenario by an environment variable (demand rises from a low base to a plateau of about 8 concurrent connections, 30 s after start);
- logs `POOL_EXHAUSTED pool=checkout-db in_use=<n> max=<n>` whenever demand exceeds the limit, and `REQUEST_OK` lines otherwise;
- in some cases also writes planted sensitive lines (a password, a bearer token, an email address, a free-text error) that must never be persisted.

**Cause.** A `kubectl set env deployment/checkout-api DB_POOL_MAX=4` (from 16) triggers a rollout. Only the new ReplicaSet's pods run with the lower limit, so only they log `POOL_EXHAUSTED`. That is exactly what `rollout_limit_reduction` requires:
- the rollout is observed;
- its typed `field_changes` lower a mapped limit;
- the symptom appears on the new revision's pods, strictly after the rollout.

## 4. <a id="collection"></a>Symptom collection

### 4.1 Protocol

Pod logs are collected **inside the existing watch session**, so their `observed` brackets are on the same session clock as the rollout's:
1. When the Pod watch first reports a pod in the incident namespace, the collector opens `GET …/pods/{name}/log?follow=true&tailLines=0&container=<c>&limitBytes=<b>`.
2. For each line received, the bracket is `[L, U)` on the collector clock:
   - `L` is the **send time of that stream's open request**;
   - `U` is the receipt time of the line.
   
   With `tailLines=0`, the API server only returns lines written after it started following, which happens after the request was sent. So the true write time lies inside the bracket. This is the same encoding and the same conservatism argument as [004f §6.2](../ca-p2-004/ca-p2-004f-plan.md#observed), and it needs no time-contract change.
3. The line's own container-runtime timestamp (`timestamps=true`) is kept only as an `event` time in a per-node clock domain declared `unknown`. It is never ordered against collector times.
4. Every stream ends with a recorded reason, as watch segments do.

### 4.2 Bounds

All limits are fixed by the collector, recorded in the plan, and reaching one is recorded as a gap:
- at most 16 pods per session;
- at most 64 KiB and 2,000 lines per pod;
- a maximum line length of 1,024 bytes;
- the existing session time limit;
- one stream per container, and no re-open after a failure.

### 4.3 <a id="gaps"></a>Gaps: fail closed

A pod's log is **complete** only if its stream ended with a clean end of stream after the Pod watch had already reported that container as terminated. In every other case the collector records a gap on the log source for that pod, and the engine treats it as limiting through the existing `limiting_gaps` rule:
- a byte, line or pod limit is reached;
- a stream fails, or access is denied;
- a pod is seen too late, or not at all;
- a container restarts.

**A pod still running at session end is not, by itself, a gap.** If it were, every positive case would abstain. So coverage for a running pod is declared as the verified interval **`[L_open, U_last_probe]`**, exactly like a watch segment:
- An unknown interval is a gap; a covered interval is not.
- A pod with an uncovered interval that **overlaps the investigation window** blocks resolution.

This mirrors 004f's verified coverage. The exact rule is finalized, with tests, in the contract slice.

### 4.4 <a id="metrics"></a>Why metrics are deferred

`metric_sample` is consumed by no mechanism, so collecting it would add evidence without adding investigation value. Doing it properly needs either Prometheus (new infrastructure) or the pod proxy (a wider RBAC grant). A later slice can add metric symptoms once a mechanism uses them.

## 5. <a id="sanitize"></a>Sanitization and sensitive-data exclusion

**Template catalog.** A pinned catalog maps each template to one anchored regular expression with **typed** captures:
- `CONFIG_LOADED`: `key` (a catalog key name), `value` (an integer);
- `POOL_EXHAUSTED`: `pool` (a name), `in_use` (an integer), `max` (an integer);
- `REQUEST_OK`: no fields.

**Rules:**
- **Only fields survive.** A matched line keeps only its template and validated fields. The existing `_LogFields` rules still apply: credential-like keys are refused, at most 16 keys, values of 256 characters or fewer.
- **Free text is dropped.** `message` becomes optional in kinds 0.4 and the collector never sets it.
- **Unmatched lines are counted only,** as `log_lines_unmatched`, per pod. A line is also unmatched if any captured value fails its type check.
- **Sanitized in memory.** Sanitization happens before anything is written to disk, as the projections do today. Raw responses are never persisted.
- **Collector limits are also checked by the converter.** It refuses a recording that contains any non-allowlisted field.

**Tests:**
- Planted needles in the workload's output, including a password, a token, an email, a JWT-shaped string and a ConfigMap note, never appear in the recording, the bundle, the database, the API or the dashboard.
- The existing `kind_checks.py` scan is extended to cover them.

## 6. <a id="time"></a>Provenance and timestamp relationships

**Provenance.** Every `log_line` carries the same provenance as other collector evidence:
- `source_id`, cluster and namespace binding;
- `source_uid` (the pod UID);
- container name;
- stream identity and session ID;
- a content digest.

The recording manifest records the template catalog's version and digest. The dashboard can therefore show which log stream, pod and revision each symptom came from.

**What can be ordered** (rule profile 2, unchanged rules):

| Pair | Ordering |
|---|---|
| Rollout vs. symptom, same session | Ordered only if the symptom's `L` is strictly after the rollout's `U` (to the millisecond). Otherwise `ordering_unknown`, and the investigation abstains |
| Anything vs. an API-server or container-runtime timestamp | Never ordered (domain `unknown`) |
| Different collection sessions | Refused (`observed_clock_domains_mixed`) |

**Known risk.** If the collector opens a new pod's log stream **before** it receives the Deployment change, the symptom bracket overlaps the rollout bracket and the case abstains. This is fail-closed, not wrong, and the harness measures how often it happens as an unnecessary abstention ([§9](#evaluation)). A tightening technique (overlapping stream rotation) is noted as a later option, not part of this milestone.

## 7. <a id="cases"></a>Positive and negative test cases

Every case runs on the disposable kind cluster, then goes through the offline pipeline and PostgreSQL verification.

| ID | Scenario | Expected result |
|---|---|---|
| P1 | `DB_POOL_MAX` 16 → 4 by rollout; demand rises to 8 after the rollout | **resolved**, `rollout_limit_reduction`, citing the rollout and the new pods' `POOL_EXHAUSTED` lines |
| P2 | As P1, with planted sensitive log lines | **resolved**; no planted value persisted anywhere |
| N1 | **False-cause trap:** image-only rollout (no limit change), while demand exceeds the unchanged limit | abstained (`no_supported_hypothesis`); the rollout **must not** be selected |
| N2 | **False-cause trap:** `DB_POOL_MAX` raised 4 → 16, with symptoms from demand anyway | abstained; the rollout must not be selected |
| N3 | Symptom **before** the change: old pods already exhausted, then a limit-lowering rollout | abstained (`contradicting_evidence_present`) |
| N4 | Limit lowered but demand stays below it | abstained (`no_symptom_observed`) |
| N5 | Log access denied (RBAC withheld for this run) | abstained (`limiting_evidence_gaps`) |
| N6 | Log stream cut mid-session (byte limit forced low) | abstained (`limiting_evidence_gaps`) |
| N7 | **Cross-scope trap:** limit lowered in `ca-other`; symptom in `ca-incident` | abstained; the `ca-other` rollout must not be selected |

**Offline coverage.** Fault-injection versions of N3–N7, and the bracket-overlap case, also run offline against the fake API server, so they are deterministic in the offline CI job.

## 8. <a id="replay"></a>Deterministic replay, storage and the dashboard

**Replay and storage.** These reuse what exists:
- conversion is run twice and must be byte-identical;
- the result is stored once and verified on every read by exact replay;
- the database run must be byte-identical to the offline run.

**Dashboard.** The resolved P1 run must show:
- the outcome (with the existing resolved styling);
- the rollout, with its typed limit change;
- the cited symptom lines as **template and fields only**, with pod, revision and stream provenance;
- the ordering basis.

Abstained runs must show their reasons. A browser test asserts that an abstained run never looks like a confirmed cause (the existing test, extended to the new cases). No UI redesign is made; only the evidence view gains a log-evidence row type if needed.

## 9. <a id="evaluation"></a>Evaluation for this milestone (development set)

**Truth is sealed and independent of the pipeline.** The scenario driver writes each run's truth file at injection time. It records what was changed, the correct cause, or "no resolvable cause", and the trap identity.
- The truth file is stored outside the collector's output directory.
- The collector, converter, engine and API never open it. A new product test proves this, modelled on the frozen prototype's `test_no_truth_file_is_opened_during_a_run` (the prototype itself is not changed).

**Product scorer.** A product scorer (`tools/eval`, standard library only) compares stored, verified results with truth. Its metric definitions are the ones in the [benchmark plan](../../reviews/phase1d/benchmark-plan.md) and the prototype scorer; its code is new, and it scores **product** results:

| Metric | Definition | Milestone target |
|---|---|---|
| False-cause selection | A run resolved to a cause that truth says is wrong, over all runs with a trap or no resolvable cause | **0**, with the count and the run IDs reported |
| Correct cause on resolvable runs | Resolved to the true cause, over P1–P2 runs | Reported with a 95% Wilson interval; the bar is set at approval (proposed: at least 8 of 10) |
| Unnecessary abstention | Abstained on P1–P2, by reason (for example `ordering_unknown`) | Reported, never hidden |
| Correct abstention | Abstained on N1–N7 | **All** runs |
| Citation validity | Every citation resolves to sealed evidence | 100% |
| Sensitive-data leaks | Planted needles found anywhere | **0** |

**Runs.** Each case runs at least 10 times in a manually dispatched job, `incident-eval-kind`, to measure flakiness and the bracket-overlap rate. Pull-request CI runs P1, N1 and N5 once each.

**Pass rule.** The milestone passes only if all of these hold:
- zero false causes;
- every negative run abstains;
- zero leaks;
- every replay is byte-identical;
- the positive success rate meets the approved bar.

A miss is reported as measured. It is never reworded.

## 10. <a id="independent"></a>How the product engine will be evaluated independently

**Why the frozen prototype's evaluation is not sufficient.** Its results apply to the prototype engine (`prototype/ca_spike`) at `c21b50d`, on fixture inputs, with the prototype scorer. The product engine differs in every one of these:
- it is different code (`ca-engine/0.1-provisional`);
- it uses different contracts, with gaps, coverage and observed brackets;
- it will now run on real collected inputs.

None of the prototype numbers transfer.

**What this milestone provides, and what it does not.** It provides the measurement **machinery**: sealed truth, a product scorer, and repeatable kind cases. The development set is authored by the same person who builds the engine, so it is **not independent**. It can find defects, but it cannot certify accuracy.

**The independent evaluation, later** (backlog CA-P2-007, CA-P2-010 and CA-P2-011):
1. **Authoring.** Held-out scenarios are authored with **PR #14's** authoring kit and custody rules ([corpus plan](../../scenarios/corpus-plan.md)), by someone other than the engine's builder.
2. **Freezing.** The product engine and catalog versions are frozen and tagged **before** the held-out set is opened, as was done for the prototype.
3. **Running.** The same product scorer runs once on the held-out set. Its definitions and targets are fixed in advance ([CA-DEC-006](../../architecture/adr/CA-DEC-006.md): zero false-cause selections, full correct abstention on gap cases).
4. **Reporting.** The results are reported as they come, including unnecessary abstentions.

**PR #14** stays separate, open and unchanged in this milestone. Integrating it is a separate decision, taken when a held-out evaluation is arranged.

## 11. <a id="slices"></a>Delivery slices (after approval)

Each slice is a separate draft PR, stacked in order, with tests written before fixes:

| Slice | Content |
|---|---|
| **CA-P2-002e** | Contracts: kinds 0.4 (`log_line` source kind for the pod log, an `observed` time on `log_line`, optional `message`); the template catalog contract; migration `0009` (supported versions only); contract tests, including the log coverage rule |
| **CA-P2-004g** | Collector: the log streams inside the watch session, the bounds, the template sanitizer, the declared limit keys giving `field_changes`, recording 0.5 and the converter, offline fault injection, and the RBAC update with its kind refusal check |
| **CA-P2-005c** | Engine: profile 2 accepts kinds 0.4. No mechanism or rule change. The six pinned digests and the profile-1 and profile-2 results are unchanged |
| **CA-P2-006e** | Dashboard: the log-evidence row and provenance, plus browser tests for P1 and an abstained case |
| **CA-P2-007a** | Evaluation: the incident workload and namespace, the scenario driver with sealed truth, the product scorer, the `incident-eval-kind` job, and the milestone report |

## 12. <a id="boundaries"></a>Boundaries

These hold for the whole milestone:
- **Synthetic only.** Only the disposable kind cluster is used: no real, shared or production cluster, and no cloud credentials.
- **No access to Secrets, ConfigMaps, `pods/exec`, nodes or namespaces.** `pods/log` is read in the incident namespace only (M2).
- **No new runtime dependency.** The workload image is a CI-only, inventoried component.
- **History stays fixed.** No change to existing migrations, contract versions, the frozen prototype, the three truth pins or the six pinned digests.
- **No engine mechanism expansion** beyond input acceptance (M6), and no UI redesign.
- **An abstention is never reported as resolved.** A synthetic positive is never presented as evidence about real-world incidents.
- **No merge, force-push, deployment or settings change** without separate authorization.

## 13. <a id="risks"></a>Remaining risks

**Ordering:**
- **Bracket overlap.** Positive runs may abstain with `ordering_unknown` if a log stream opens before the rollout is received. This is measured, not hidden ([§6](#time)).
- **Coverage rule complexity.** The log coverage interval ([§4.3](#gaps)) is new reasoning. It is designed and tested in CA-P2-002e before any collector code is written.

**Sanitization:**
- **Allowlist completeness.** A real application could log a secret inside a field that the catalog allows. The catalog's typed fields (integers and short names) limit this, but cannot rule it out in general.

**What the results show:**
- **Single mechanism.** Success shows end-to-end value for one mechanism, `rollout_limit_reduction`. It says nothing about mechanisms that do not exist yet.
- **Author bias.** The development set is not independent ([§10](#independent)).
