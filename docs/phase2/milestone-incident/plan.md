# Milestone plan: an end-to-end synthetic incident investigation

**Status:**
- **Revision 2.** The overall direction of M1–M9 was approved on condition that log continuity, pod identity, RBAC and environment handling, and the evaluation thresholds were corrected. This revision makes those corrections ([§2](#decisions), [§4](#collection), [§5](#identity), [§6](#rbac), [§10](#evaluation)) and records why they do not widen scope ([§13](#scope)).
- It is a planning artifact, not a gate disposition, a specialist approval or a production-readiness claim.

**Base:** `main` at `402531d` (after the [third integration](../integration.md)).

**Goal:** show **real root-cause investigation value** end to end. On a disposable kind cluster, a synthetic incident is caused by a real infrastructure change. Cloud Autopsy collects both that change and the application's symptom evidence, read-only and sanitized, and then:
- stores the evidence;
- replays it deterministically from PostgreSQL;
- resolves the true cause **only** when the evidence, including proof of complete log coverage, supports it;
- abstains, with the reason, in every other case;
- shows the result in the existing dashboard.

More evidence collection by itself is not the goal. Success must never come from overstating how complete the evidence is.

## 1. <a id="today"></a>Where the product stands

**What already works on real collected data** ([004e](../ca-p2-004/ca-p2-004e.md), [004f](../ca-p2-004/ca-p2-004f.md), [005b](../ca-p2-005/ca-p2-005b.md)):
- read-only list and watch collection, with sanitizing projections;
- verified coverage and explicit gaps;
- session-scoped `observed` brackets on the collector's own clock;
- rule profile 2;
- write-once results, verified on read;
- the dashboard.

**Why every real investigation abstains today.** The engine needs three things that real collection does not provide:

| Needed by `rollout_limit_reduction` | Today |
|---|---|
| A symptom: a `log_line` with template `POOL_EXHAUSTED` | **No symptom source.** Result: `no_symptom_observed` |
| A typed limit change: `field_changes` mapped to a catalog key | Only changed field **paths** are recorded; env values are withheld. Result: `no_mechanism_maps_changed_fields` |
| A symptom on the **new** revision's pods, **strictly after** the rollout, with no unexamined evidence that could contradict it | Never exercised |

**The demo workload** (`pause`) emits nothing. The synthetic positive controls resolve on **constructed** evidence and are not evidence that real collection can resolve.

## 2. <a id="decisions"></a>Decisions

Approved in direction, with the revision-2 corrections:

| # | Decision | Revision 2 |
|---|---|---|
| M1 | Symptoms from container logs through the Kubernetes API (`pods/log`, follow mode). Metrics deferred ([§4.8](#metrics)) | Unchanged |
| M2 | `get pods/log` in **`ca-incident` only**, in the disposable kind cluster | Refusal tests specified ([§6.1](#rbac-tests)) |
| M3 | Template-allowlist sanitization; raw lines never stored | Sequence envelope added ([§4.2](#envelope)) |
| M4 | Declared numeric limit keys (`DB_POOL_MAX` → `pool.maxConnections`) | Rejection rules specified ([§6.2](#env)) |
| M5 | Observation kinds **0.4**, migration **`0009`**, recording **0.5** | **Narrowed.** `log_line` under kinds 0.4 belongs to the existing source kind `kubernetes_api`, because `pods/log` *is* a Kubernetes API subresource. No source-registry or batch-contract change ([§13](#scope)) |
| M6 | No new mechanism and no new ordering rule. Profile 2 also accepts kinds 0.4 | Plus: the engine maps kinds to source kinds through the **pinned** registry, which matters once `log_line` has two source kinds ([§11](#slices)) |
| M7 | ConfigMap values stay unread | Unchanged |
| M8 | CI-only, digest-pinned `busybox` workload image | Unchanged |
| M9 | Development-set harness with sealed truth and a product scorer | Thresholds fixed ([§10](#evaluation)) |
| **M10** | **New, needs approval:** a declared bound **δ = 2 s** on the delay between the application writing a line and the container runtime appending it to the node log file. It is used **only** to lower the start of a log line's `observed` bracket ([§4.4](#brackets)) | Approve. It is an assumption, recorded in every recording and in the result's plan, not a measurement |

## 3. <a id="incident"></a>The synthetic incident

**Namespace.** `ca-incident` contains only the incident workload. `crashy` stays in `ca-demo`.

**Workload (`checkout-api`, busybox shell):**
- reads `DB_POOL_MAX` from its environment, and its own pod UID and container name from the Downward API;
- writes **only** enveloped lines ([§4.2](#envelope)), from a single writer;
- runs a deterministic demand schedule chosen by the scenario;
- logs `POOL_EXHAUSTED` while demand exceeds the limit;
- logs `HEARTBEAT` every second;
- logs `STOPPED` on `SIGTERM`.

**Cause (P1).** `kubectl set env deployment/checkout-api DB_POOL_MAX=4` (from 16) triggers a rollout. Only the new ReplicaSet's pods run with the lower limit, so only they log `POOL_EXHAUSTED`.

## 4. <a id="collection"></a>Log collection, continuity and coverage

### 4.1 What the transport does not prove

None of these establish that every application log line was received:
- a successful follow connection;
- an open stream;
- the end of a stream;
- a Pod-watch resourceVersion probe.

A follow stream can silently skip lines when:
- the kubelet rotates the log file;
- a byte limit is reached;
- the connection drops;
- the collector attaches late;
- the line is partial.

The transport also carries no sequence information. **Coverage is therefore proven from the content of the log itself, or not at all.**

### 4.2 <a id="envelope"></a>The sequence envelope

Every line the workload writes has this form:

```
CA1 boot=<8 hex> seq=<n> <TEMPLATE> [key=value ...]
```

- **`boot`** is random for each process start (container instance).
- **`seq`** starts at 1 and increases by exactly 1 per line.
- **`seq=1` is always `STARTED pod_uid=<uid> container=<name>`.**
- **The envelope is a declared property of the synthetic workload,** named in the scope declaration with its version.

A log without a valid envelope can never establish coverage, so it always produces a limiting gap. This is deliberate. It also means that, under this design, an ordinary application without such an envelope could not resolve an investigation. That limit is stated here, not hidden.

### 4.3 Three states, kept apart

| State | What establishes it | What it supports |
|---|---|---|
| **Observed line** | A complete, newline-terminated line received on a recorded stream, with a valid envelope, attributed to a verified instance ([§5](#identity)) | That line exists, with its template, fields and bracket |
| **Continuous interval** of a container instance | Lines `seq=1 … k` of one `boot` all observed, with no number missing and no conflicting duplicate | No line written by that instance **before line `k`** exists unobserved |
| **Unknown coverage** | Everything else | Nothing. It is a limiting gap when it overlaps the investigation window ([§4.6](#window)) |

**Duplicates are expected.** Overlapping streams deliver the same line twice ([§4.4](#brackets)). Two copies of a `(boot, seq)` must have identical sanitized content, otherwise the instance's identity is in conflict and its coverage is unknown.

### 4.4 <a id="brackets"></a>Streams and brackets

**Streams per container instance:**
1. **History attach.** When the Pod watch first reports the instance, the collector opens a follow stream without `tailLines`, which returns the instance's whole log so far. This is how `seq=1` is obtained.
2. **Rotation.** Every 5 s the collector opens a new stream with `tailLines=0` at send time `O`. It closes the previous stream only once the new one has delivered a line `s` and the previous one has delivered every line up to `s − 1`. If that overlap cannot be shown, the old stream stays open until the next rotation. If it ends first, continuity is broken.
3. **Final drain.** At session end, after the final watch probe is sent at `P_end`, the collector waits δ and opens one last `tailLines=0` stream per live instance. It waits for a `HEARTBEAT` that is contiguous with what it already has.

**The `observed` bracket `[L, U)` of a line** (same encoding as [004f §6.2](../ca-p2-004/ca-p2-004f-plan.md#observed); no time-contract change):
- **`U`** is the earliest receipt of the line. The application wrote it before any copy arrived.
- **`L` from a `tailLines=0` stream** opened at `O` is `O − δ`. The stream returns only lines appended to the node file after the kubelet began following, which is after `O`. The application wrote the line at most δ earlier (M10).
- **`L` when a line has several copies** is the largest of these values.
- **`L` from a history attach:**
  - if the pod was **created during the session**, `L` is the pod's own creation lower bound from the watch (004f's `L` for its `ADDED` event), because a container cannot write before its pod exists;
  - if the pod **predates the session**, the line has **no** `observed` time and is never ordered.
- **The runtime's own timestamp** is kept as an `event` time in a domain declared `unknown`, and is never ordered.

**Bracket width.** A bracket wider than the contract's limit is refused, so the line counts as a gap.

### 4.5 Conservative handling of each failure

| Situation | Handling |
|---|---|
| Stream disconnects without overlap | Lines after the last contiguous one are unknown, and the next stream shows a `seq` jump: gap |
| Container restart (new `boot`) | A new instance needs its own `seq=1`, via a history attach. The previous instance is complete only if its `STOPPED` was observed contiguously; otherwise its tail is unknown: gap |
| Late attachment (first observed `seq` > 1, or history rotated away) | Gap from the instance's start |
| Truncation (`limitBytes`, or the line or byte limits) | The stream ends; any resulting `seq` jump is a gap |
| Partial line (no newline at stream end) | Discarded and not counted. Its `seq` is never assumed |
| Over-long or unparseable line | Breaks continuity: gap. It is never stored |
| Log rotation on the node | Any lost line shows as a `seq` jump: gap |
| Pod termination | The instance is complete through `STOPPED`. Without `STOPPED`, its tail is unknown: gap |
| Unmatched template inside a valid envelope (for example a planted line) | Counted for continuity, never stored ([§7](#sanitize)) |

### 4.6 <a id="window"></a>Which coverage is required

**The window.** The investigation window is the watch's verified coverage, from the first list receipt to `P_end`.

**Every container instance** of every pod in `ca-incident` that existed at any time in the window must be **continuous** across its part of the window:
- from `seq=1`;
- to its observed `STOPPED`, or to a line whose `L` is at or after `P_end` (the final drain gives that line).

**Gaps.** Any instance that falls short produces a gap on the source, in the batch for that pod. Through the existing `limiting_gaps` rule, a gap there blocks support for **every** mechanism that needs `log_line` or `pod`. A gap is never shrunk to "probably fine".

### 4.7 <a id="positive"></a>Why P1 can still resolve without weakening any of this

**Timeline (all times on the collector clock).** The driver applies the Deployment after the session starts. The rollout's watch bracket is `[L_r, U_r)` and its commit is `c_r`.
1. **New pods appear after the commit.** They are created after `c_r`. Their history attach yields `seq=1`, and rotations keep continuity.
2. **The first symptom comes much later.** Demand reaches the new limit at least 30 s after a new container starts, so the first `POOL_EXHAUSTED` is appended no earlier than `c_r + 30 s`.
3. **The stream delivering it is recent.** It was opened at most about 5 s before the append (the rotation period), so `L_sym ≥ c_r + 30 − 5 − δ = c_r + 23 s`.
4. **So the symptom is ordered after the rollout.** Since `U_r` is `c_r` plus the watch delivery delay (normally well under a second), `L_sym > U_r` holds unless that delay exceeds 23 s. If it ever does, the case abstains with `ordering_unknown`, which is fail-closed and reported.
5. **The old pods leave cleanly.** They log no symptom (limit 16 > demand 8). They receive `SIGTERM` and log `STOPPED`, so they are complete. Surviving new pods are covered to `P_end` by the final drain.
6. **Result.** No gap, a typed limit reduction, a symptom on the new revision ordered after the rollout, and no contradiction.

This is what `rollout_limit_reduction` requires, so the run resolves. Nothing is assumed complete without proof, and the only assumption, δ, is declared.

**The safeguards still bite in the failure cases.** N5 and N6 deny or cut log access, and the new offline cases (§9) break the envelope, the sequence, the identity and the overlap. Each of those must abstain.

### 4.8 <a id="metrics"></a>Metrics are deferred

No mechanism consumes `metric_sample`, and collecting it properly needs new infrastructure or a wider RBAC grant.

## 5. <a id="identity"></a>Pod identity and source provenance

`pods/log` addresses a pod by **name**. Each line is bound to a pod **UID**, namespace, container and collector session by three independent checks. All three must agree, or the stream's lines are not attributed and the instance's coverage is unknown, which is a gap.

1. **Watch binding.** A stream is opened only for a `(namespace, name)` that the Pod watch currently maps to exactly one UID that is not being deleted. The converter re-derives, from the recorded watch, that the mapping did not change between the stream's open and its last used receipt: no `DELETED`, and no `ADDED` with a different UID, for that name. Any change makes the stream unattributable.
2. **Content binding.** An instance's `seq=1` line (`STARTED pod_uid=… container=…`) must name the watch's UID and the requested container. Every later line carries that instance's `boot`, which ties it to the verified `STARTED` line. Lines whose `boot` has no verified `STARTED` are unattributable.
3. **Recheck after close.** After each stream closes, the collector issues `GET pods/{name}` (already allowed) and records the UID. A different UID or a `404` makes the stream unattributable unless the watch already recorded the pod's deletion **after** the stream's last used line.

**Provenance on each `log_line`:**
- `source_uid` = pod UID;
- attributes: pod name, container, `boot`, `seq`, stream identity and session ID.

The rollout mechanism reaches a pod's ReplicaSet through `owner_replicaset` of **that UID** from the watch, never through the name.

**Tests** (offline, against the fake API server):
- **Name reuse:** a pod is deleted and recreated with the same name and a new UID mid-stream, and the server serves the new pod's log. No line is attributed to the old UID, and the run abstains.
- **Identity mismatches:** the `STARTED` UID or container does not match, a `boot` appears without `STARTED`, or a `GET` recheck returns a different UID or `404` before the watch shows the deletion. Each makes the stream unattributable and records a gap.
- **Cross-rollout attribution:** a reused name moves from an old ReplicaSet's pod to a new one's. The symptom is not credited to the new revision.

## 6. <a id="rbac"></a>RBAC and environment values

### 6.1 <a id="rbac-tests"></a>RBAC

**The incident Role** (namespace `ca-incident` only, in the disposable kind cluster):
- `get`, `list` and `watch` on `pods`, `replicasets`, `deployments` and `events`;
- `get` on `pods/log`.

The existing `ca-demo` and `ca-other` Roles are unchanged and do not gain `pods/log`.

**The kind check proves, with the collector's real token,** that each of these is forbidden:
- `pods/log` in `ca-demo`, `ca-other` and `kube-system`;
- `secrets` and `configmaps` in every namespace;
- `pods/exec` and `pods/attach`;
- `nodes` and `namespaces`;
- every write (`create`, `update`, `patch`, `delete`) on pods, deployments and `pods/log`.

### 6.2 <a id="env"></a>Declared numeric limits

**The scope declaration** names each limit key, its container and its catalog key, for example `checkout-api / DB_POOL_MAX → pool.maxConnections`. A key name that looks like a credential is refused as a declaration.

**A value is read only if all of these hold:**
- the key is declared;
- it is set by a literal `value` (not `valueFrom`);
- the value matches `^(0|[1-9][0-9]{0,5})$`.

**Everything else is withheld and counted, and produces no typed change:**
- `secretKeyRef`, `configMapKeyRef`, `fieldRef` and `resourceFieldRef` sources;
- `envFrom`;
- malformed integers such as `" 4"`, `"04"`, `"1e3"`, `"-4"`, `"４"` and `"4\n"`;
- undeclared keys, and declared keys in other containers.

The rollout then has no typed limit change, so it is not supported. That is the safe direction.

### 6.3 Sanitize before persistence

**Logs and env values are reduced in memory, before anything is written:**
- each log line becomes `(stream, receipt, boot, seq, template, typed fields)`, or `(…, boot, seq, unmatched)`;
- env becomes only the declared integers.

**Raw responses are never persisted.** A needle scan covers:
- the recording;
- the bundle;
- the database rows;
- the API JSON;
- the rendered dashboard HTML.

It looks for:
- planted log lines: a password, bearer token, email, JWT-shaped string and free text;
- planted env values, including undeclared keys;
- the collector token.

## 7. <a id="sanitize"></a>Template catalog

**Templates:**
- `STARTED` (`pod_uid`, `container`);
- `HEARTBEAT`;
- `CONFIG_LOADED` (`key`, `value`: integer);
- `POOL_EXHAUSTED` (`pool`, `in_use` and `max`: integers);
- `REQUEST_OK`;
- `STOPPED`.

**Matching rules:**
- each template is one anchored pattern with typed captures;
- the existing `_LogFields` rules still apply;
- `message` is optional in kinds 0.4 and never set by the collector;
- a valid envelope with an unknown template, or with a field that fails its type, counts for continuity and is otherwise dropped, as `log_lines_unmatched`.

**Version.** The catalog's version and digest are recorded in the recording manifest.

## 8. <a id="time"></a>Ordering summary

All ordering uses rule profile 2, unchanged:

| Pair | Ordering |
|---|---|
| Rollout vs. symptom, same session | Ordered only if `L_sym > U_r` to the millisecond; otherwise `ordering_unknown` |
| Runtime or API-server timestamps | Never ordered |
| History lines of pods older than the session | No `observed` time, so never ordered |
| Different sessions | Refused (`observed_clock_domains_mixed`) |

## 9. <a id="cases"></a>Positive and negative cases

### Kind cases

Every kind case runs on the disposable cluster, then offline and through PostgreSQL verification:

| ID | Scenario | Expected result |
|---|---|---|
| P1 | `DB_POOL_MAX` 16 → 4 by rollout; demand rises to 8 | **resolved**, `rollout_limit_reduction` |
| P2 | As P1, with planted sensitive log lines and env values | **resolved**; zero leaks |
| N1 | False-cause trap: image-only rollout, while demand exceeds the unchanged limit | abstained; the rollout is never selected |
| N2 | False-cause trap: limit raised 4 → 16, with symptoms from demand | abstained; never selected |
| N3 | Symptom **before** a limit-lowering rollout | abstained |
| N4 | Limit lowered, demand stays below it | abstained (`no_symptom_observed`) |
| N5 | Log access denied for the run | abstained (`limiting_evidence_gaps`) |
| N6 | Log stream truncated (byte limit forced low) | abstained (`limiting_evidence_gaps`) |
| N7 | Cross-scope trap: limit lowered in another namespace | abstained; never selected |

### Offline cases (deterministic, fake API server)

- **Continuity:** a `seq` jump, a missing `STARTED`, a duplicate with different content, a disconnect without overlap, a restart without `STOPPED`, a late attach, a partial line, an over-long line, and the final drain missing.
- **Identity:** name reuse, a `STARTED` mismatch, and a recheck mismatch ([§5](#identity)).
- **Environment:** every rejection rule of [§6.2](#env).
- **Ordering:** a bracket overlap gives `ordering_unknown`.

Each case has an exact expected outcome and gap list.

## 10. <a id="evaluation"></a>Development-set evaluation (thresholds fixed)

**Truth.** The scenario driver writes each run's truth file at injection time, outside the collector's output. A product test proves that the collector, converter, engine and API never open it. It is modelled on the frozen prototype's `test_no_truth_file_is_opened_during_a_run`, and the prototype itself is not changed.

**Scorer.** A product scorer (`tools/eval`, standard library only) scores stored, verified product results against the truth. Its metric definitions follow the [benchmark plan](../../reviews/phase1d/benchmark-plan.md).

**Thresholds** (provisionally approved; for this developer-authored synthetic milestone only):

| Measure | Threshold |
|---|---|
| Correct resolution, P1 | at least **8 of 10** repetitions |
| Correct resolution, P2 | at least **8 of 10** repetitions |
| False-cause selections across all negative repetitions | **0** |
| Negative cases that abstain | **every** repetition of N1–N7 |
| Citation validity | **100%** |
| Planted-sensitive-data leaks | **0** |
| Deterministic replay (conversion twice, offline vs. database) | byte-identical in **every** run |

**Also reported, never hidden:**
- every unnecessary abstention, with its reason;
- every timing failure, such as `ordering_unknown` from bracket overlap, or a missing final-drain heartbeat.

**Runs.** The manually dispatched job `incident-eval-kind` runs 10 repetitions of P1 and P2 and at least 3 of each negative case. Pull-request CI runs P1, N1 and N5 once.

**These thresholds certify nothing about accuracy beyond this development set** ([§12](#independent)).

## 11. <a id="slices"></a>Delivery slices

Each slice is a separate draft PR, stacked in order. Regression tests are written before fixes, and real disposable-kind CI verifies each slice that touches collection:

| Slice | Content |
|---|---|
| **CA-P2-002e** | Kinds 0.4: `log_line` with source kind `kubernetes_api`, an `observed` time and an optional `message`. Migration `0009` (supported-version rows only). Contract tests |
| **CA-P2-004g** | Collector and converter: the log streams with rotation and final drain; the envelope and continuity derivation; identity binding and recheck; the template sanitizer; declared limits giving `field_changes`; recording 0.5; offline fault injection; the incident RBAC and refusal checks |
| **CA-P2-005c** | Engine: profile 2 accepts kinds 0.4, and kind-to-source-kind mapping uses the pinned registry. No mechanism or rule change. The six pinned digests and all profile-1 and profile-2 results are unchanged |
| **CA-P2-006e** | Dashboard: the log-evidence row with provenance (template and fields only). Browser tests for a resolved and an abstained case |
| **CA-P2-007a** | The workload and namespace, the scenario driver with sealed truth, the scorer, `incident-eval-kind`, and the milestone report |

## 12. <a id="independent"></a>Independent evaluation of the product engine

**The frozen prototype's evaluation does not transfer.** It measured different code (`prototype/ca_spike` at `c21b50d`), on fixture inputs, under different contracts. The product engine runs on real collected inputs with gaps, coverage and observed brackets.

**This milestone's development set is not independent either.** It is authored by the engine's builder, so it can find defects but cannot certify accuracy.

**The independent evaluation, later** (CA-P2-007, CA-P2-010, CA-P2-011):
1. Held-out scenarios are authored with **PR #14**'s kit and custody rules ([corpus plan](../../scenarios/corpus-plan.md)), by someone other than the builder.
2. The product engine and catalog are frozen and tagged before the held-out set is opened.
3. The product scorer runs once, with targets fixed in advance ([CA-DEC-006](../../architecture/adr/CA-DEC-006.md)).
4. The results are reported as they come.

**PR #14** stays separate, open and unchanged.

## 13. <a id="scope"></a>Why revision 2 does not widen scope

**Narrower than revision 1:**
- **No source-registry change.** Adding a source kind would have needed `ca-source-registry/0.2`. Instead, `log_line` under kinds 0.4 uses the existing `kubernetes_api` source kind.
- **No batch-contract change.** Log batches use `coverage_basis: null`. Their continuity is proven from the recorded envelope and re-derived by the converter on every verification, and any shortfall is a gap.

**Inside the already approved slices:**
- **New mechanics.** The envelope, the stream rotation and the identity checks are workload, collector and converter work in CA-P2-004g and CA-P2-007a.
- **New decision.** The only one is **M10** (δ), an explicit assumption that makes the bracket conservative instead of silently optimistic.

**Unchanged:**
- existing contracts, migrations `0001`–`0008`, the six pinned digests, the three truth pins and the frozen prototype;
- engine mechanisms and ordering rules.

## 14. <a id="boundaries"></a>Boundaries

These hold for the whole milestone:
- **Synthetic only.** Only the disposable kind cluster is used: no real, shared or production cluster, and no cloud credentials.
- **No access to Secrets, ConfigMaps, `pods/exec`, nodes or namespaces.** `pods/log` is read in `ca-incident` only.
- **No new runtime dependency.** The busybox image is CI-only and inventoried.
- **No engine mechanism expansion** and no UI redesign.
- **An abstention is never reported as resolved.** A synthetic positive is never presented as evidence about real incidents.
- **No merge into `main`, force-push, deployment or settings change** without separate authorization.

## 15. <a id="risks"></a>Remaining risks

**Assumptions:**
- **δ is assumed, not measured.** If the runtime ever delayed a line by more than 2 s, a bracket could start too late. Its only use is the start of an `observed` bracket. The positive case keeps more than 20 s of margin, and the value is recorded in every run.

**Measured outcomes:**
- **Ordering.** Positive runs can abstain from bracket overlap. This is measured and reported.

**Limits of the design:**
- **The envelope is required.** Without the declared envelope, coverage can never be proven, so applications without it always abstain.
- **Allowlist completeness.** Typed fields limit what can leak but cannot rule out a secret inside an allowed field in general.

**What the results show:**
- **One mechanism.** Success shows value for `rollout_limit_reduction` only.
- **Author bias.** The development set is not independent ([§12](#independent)).
