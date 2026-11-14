# CA-P2-004g: why a real rollout still abstains apart from logs (analysis and proposal)

**Status (2026-11-14):**
- **M12a, M12b and M12c are implemented**, with the product owner's safeguards, as recording **0.6** (`app/completeness.py`, `_acquisition_v6`). Recordings 0.4 and 0.5 convert exactly as before. [§Implementation](#implemented) has the details.
- **M12d is implemented with a causal-scope safeguard** ([§M12d](#m12d-implemented)). The contract change it needed, sub-interval coverage under batch 0.3, was approved in principle and is implemented. The engine-side guard is proposed separately and is **not** implemented.
- **The Events acquisition** cannot prove coverage after it goes quiet. This is Kubernetes protocol behaviour, not a collector defect ([§Events](#events)).
- The sections below the implementation notes are the original analysis and proposal.

**Reproduced by:** `tests/collector/test_rollout_completeness.py`. These are characterization tests that pin today's fail-closed behaviour. On a real cluster, the first `collector-logs-kind` run showed causes 1 and 2:
- 10 `no_new_revision` changes;
- 2 `node_missing` and 2 `container_statuses_missing`.

Causes 3 and 4 occur in every run.

**Log coverage is not one of the causes.** With batch 0.3 (M11), proven log coverage is a complete batch with a `log_sequence_continuity` basis. The causes below come from the Pod, Deployment, ReplicaSet and Event acquisitions, and from the plan window. Log continuity never stands in for any of them.

## <a id="implemented"></a>Implementation (recording 0.6)

**M12a: Deployment updates.** The projection now keeps `metadata.generation` and a SHA-256 of the spec without its template (`specDigest`); the digest is compared only for equality and keeps no value. Within one segment, an unconverted Deployment version is compared with the previous delivered version of the same UID (the listed state, or an earlier event). A deletion resets the comparison.
- **`status_only`:** the generation, revision and spec digest are unchanged, and all three are present.
- **`accounted_by_rollout`:** the generation rose while the revision and spec digest did not change, and a later event of the same UID, within the same segment and proof and at that same generation, converted into a rollout with a higher revision. This is how `kubectl set env` appears.
- **Everything else stays withheld.** That includes a scale or strategy change (the spec digest changes), a missing generation or digest, and a generation rise with no later rollout at that generation.

**M12b: Pods first seen before they can be represented.** The projection now keeps the phase, a `started` flag for each container and init container (whether it is running, or has terminated now or before), and the init containers' names. Never states' messages, reasons or exit codes.

An unconvertible pending observation is `superseded` only when all of these hold:
- the phase is `Pending`;
- the spec has no init containers;
- no container or init container has started, and every status shows its `started` flag;
- a later observation of the same UID converts within the same segment and proof;
- nothing in between was a deletion or another failure.

**Recording 0.6 also adds two log gaps:**
- A pod that has init containers gets the log gap `init_containers_not_collected`, because only regular containers are followed.
- A symptom line without a protocol lower bound gets the log gap `symptom_unplaced`. Such a line could precede the change, unseen.

**M12c: the listed state.** A consistent, proven list now opens the first complete batch, as "the state at the start anchor, plus every change until the end anchor".
- **Kept distinguishable.** Listed objects carry only their API-server `event` time and never an `observed` bracket, so they are never presented as witnessed during the segment.
- **Benign list notes.** A Deployment with no previous revision is counted as `listed_state`.
- **Still partial:** a withheld list item (for example an Event about a Secret), a truncated list, or an unproven segment keeps the 0.4 partial batches.

**Provenance.** Every classified change is counted by class, with its UID, resourceVersion and event type (`classified_items`). Unclassified ones stay `changes_withheld`.

**M12d (measurement).** The incident window is set before collection with `--incident-window START:END` (seconds after the session starts) and recorded in the 0.6 manifest. The report gives:
- `requested_incident_window_ms`;
- `verified_interval_ms`: the intersection of every acquisition's clean coverage, which must be contiguous; it is `null` when there is none;
- `requested_inside_verified`;
- the plan window;
- the acquisitions with unclean batches.

The plan window is the recording's span, as before. Nothing is excluded.

**Tests:**
- `tests/collector/test_completeness_v6.py` (16): classification unit tests, and 0.6 sessions for each cause, alone and together.
- The adversarial cases:
  - a scale change still withholds;
  - pending init-container activity is never hidden;
  - an unplaced symptom is a gap;
  - a withheld listed item keeps the starting state partial;
  - with no common verified interval, the interval is reported as none;
  - a 0.5 recording is unchanged.
- `tests/engine/test_window_safety.py` (2): a rollout known only from the list (no bracket), or witnessed after the symptom, never supports an in-window symptom.
- **Unchanged:** the six pinned digests, the existing false-cause traps and every earlier suite.

## <a id="m12d-implemented"></a>M12d as implemented (2026-11-14)

**Contract (batch 0.3, in CA-P2-002e).** For either basis kind, a complete or empty batch may claim any non-empty coverage *inside* the interval its anchors prove, never beyond it. The anchors, resourceVersions and session still state the whole proof. Batch 0.2 is unchanged.

**The verified interval V** is computed from the basis anchors of complete and empty batches alone, never from claimed coverage. It must be contiguous for every acquisition.

**The converter narrows the plan window to the incident window W** (declared before collection) only when all three hold (`_window_decision`):
1. **Proof.** V exists and contains all of W.
2. **Cleanness.** Every batch of every acquisition is complete or empty: no partial tail, no unproven segment.
3. **Causal scope.** Every causally relevant observation that carries an `observed` bracket has that bracket entirely inside W:
   - a rollout, a ConfigMap change, a deletion or an alert;
   - a symptom log line.

**When narrowed:**
- the batches claim exactly W and keep their whole proofs;
- every observation stays in front of the engine;
- replay re-derives the narrowed bundle byte for byte.

**Otherwise,** the full-span window and its gaps remain, so the investigation abstains.

**The report keeps:**
- the requested window and V;
- whether the window was narrowed;
- every reason narrowing was refused;
- the relevant observations outside W, by source reference, kind and bracket, with no payload.

**Why the safeguard is in the converter.** The engine reads the plan window only for the result header and the coverage holes, and evaluates every sealed observation. `tests/engine/test_window_safety.py` shows that a cause and symptom entirely before the plan window still resolve when the engine runs on its own. The converter therefore never narrows while relevant evidence lies outside W:
- a cause and symptoms outside W never resolve W;
- neither does a cause outside W with a symptom inside;
- a contradiction just outside W keeps the full window.

**Proposed engine guard (defense in depth; needs separate approval; not implemented).** When the plan pins rule profile 2, a prerequisite may be satisfied only by observations whose `observed` bracket lies entirely inside the plan window. Contradictions would still use every observation. Without that guard, the window rule depends on the converter, as bases already do: a bundle that was not derived from a recording is not protected by replay.

**Tests** (`tests/collector/test_window_scope.py`, 9; `tests/engine/test_window_safety.py`, 4), covering the product owner's cases:
1. inside → narrowed;
2. a rollout and its symptoms outside → refused;
3. a rollout outside, the symptom inside → refused;
4. a contradicting symptom just outside → refused and listed;
5. missing coverage inside W → refused;
6. no common verified interval → refused;
7. an unproven tail → refused;
8. the six digests unchanged (engine suite).

An end-to-end session also narrows for real: clean batches claiming W, nothing dropped, byte-identical replay, zero gaps.

## <a id="events"></a>Why the Events acquisition stops proving coverage

**Observed on kind** (run 43567724688). The Events acquisition had a single segment that ended at session end, and its proof stopped about 25 s in. After that, every probe stayed unproven. Pods, Deployments and ReplicaSets were proven to the end.

**Cause: Kubernetes protocol behaviour, not a collector defect.**
- A probe is proven only when the watch later delivers an event or BOOKMARK at or above the probe's resourceVersion.
- kube-apiserver serves Events **without a watch cache** by default (its default watch-cache size for `events` is 0). BOOKMARKs are produced by the watch cache, so an Events watch receives none. Kubernetes does not guarantee periodic BOOKMARKs in any case.
- In `ca-incident`, Events stop soon after the rollout, while the global revision keeps advancing (leases, node status, other namespaces). From then on nothing can prove a later probe, however healthy the open watch is.
- In `ca-demo`, the 004f job's crash-looping pod emits Events continuously, which is why the problem never showed there.
- The collector claims nothing it cannot prove, which is correct.

**Reproduction.**
- `tests/collector/test_events_proof.py` (fake API) shows a quiet Events watch without BOOKMARKs while the rest of the cluster advances the revision:
  - one segment, ended by the session;
  - idle-timeout resumes only;
  - 0 BOOKMARKs;
  - the last delivery is an event;
  - every later probe unproven;
  - Pods proven to the end.
- The kind check prints the same facts (`app/stream_facts.py`) for every resource, so the real run shows them directly.

**Smallest safe alternatives (each needs approval; none implemented):**
1. **Recommended: an explicit plan without Events for incident runs.** No current mechanism reads `k8s_event`. A recorded collector choice (for example `--no-events`, stated in the manifest, the plan's expected acquisitions and the report, with this reason) would stop claiming or gapping Events. This is never a silent removal, and the dashboard would say that Events were not collected.
2. **A per-acquisition kind declaration.** The plan states which kinds each query produces, and the engine counts a gap as limiting only for mechanisms that need those kinds. It is more general, but it is a plan-contract and engine change.
3. **Not recommended: an end-of-session reconciliation list.** It could detect missed changes and missed deletions, but not an object both created and deleted inside the interval, so it is weaker than a proof.

Generating artificial Events to keep the watch busy is rejected: it would make the test pass without making the collector's evidence any stronger.

## <a id="m12d-contract"></a>M12d: the contract change (original proposal, now implemented)

**Why the plan window cannot be narrowed today.** Under acquisition batch 0.3, a complete or empty batch's coverage must **equal** its basis anchors (`acquisition._check_basis`), and coverage must lie inside the plan window. So the plan window must contain every acquisition's whole proven interval. It cannot be a requested incident window that sits strictly inside the verified interval. Narrowing it would require clipping coverage away from the anchors, which the contract refuses, and rightly so under the current wording.

**Proposed change (batch 0.3 only, still unmerged; 0.1 and 0.2 unchanged).** For both basis kinds, a batch's coverage may be **a sub-interval of** its anchors instead of exactly equal to them. The basis still states the full proven interval, and the batch claims completeness only over its stated coverage.

**The converter would set the plan window to the predefined incident window W only when all of these hold:**
1. W lies inside the verified interval V, computed from bases alone;
2. every acquisition has only clean batches (no tail, no partial, no unproven segment);
3. every observation stays in the bundle, including evidence observed outside W but inside V.

The engine therefore still sees a contradiction or another change just outside W. Nothing is dropped, so no exclusion record is needed.

**When any condition fails,** the converter keeps today's full-span window, and the run abstains on its gaps. The report states which condition failed.

**What the outcome would mean.** "Resolved" would mean resolved over the requested incident window, which is entirely verified, with every collected observation still examined. It would not be a narrower, qualified analysis, so the result contract is unchanged.

**What the change needs:**
- the batch 0.3 wording and its contract tests (sub-interval accepted; outside the anchors refused);
- the converter rule above, with the adversarial tests already listed;
- no engine, result or migration change.

## The four causes

| # | Cause | Where | Today | Why fail-closed |
|---|---|---|---|---|
| 1 | Status-only Deployment updates (status, conditions, `observedGeneration`) during a rollout | `_convert_object`: a Deployment change without a higher revision is `no_new_revision` | Counted as unconverted, so the Deployment batch is `partial` / `changes_withheld` | A delivered change that was not turned into evidence could hide a relevant change, so 004f counts it against completeness |
| 2 | Pods first seen pending (no node, no container statuses) | `K._pods`: `node` and `restart_count` are required by the `pod` kind | Unconverted (`node_missing`, `container_statuses_missing`), so the Pod batch is `partial` / `changes_withheld` | The required fields are absent, so they are never invented |
| 3 | The initial list state | `_acquisition`: the list is "a state at an unplaced moment" | One `partial` / `continuity_lost` batch per resource, in **every** run | A list proves the state at its resourceVersion, not when objects changed |
| 4 | The plan window spans the whole recording | `convert`: window = earliest to latest recorded time | Coverage holes at the window's edges for every acquisition, in **every** run | Coverage is only what a basis proves; the rest of the window is a gap |

Each one alone yields `limiting_evidence_gaps`, so every real investigation abstains even when the causal evidence is complete. Fixing only causes 1 and 2 would not be enough, because 3 and 4 remain.

## Proposals (each needs approval)

### M12a: classify status-only Deployment updates by `metadata.generation`, without a new kind

**Change:**
- Project `metadata.generation`, an integer from the API server.
- A Deployment `MODIFIED` event counts as **status-only** only when both hold:
  - its generation equals the generation of the previous delivered version of the same UID;
  - its revision annotation is unchanged.
- A status-only change is counted under its own category, `status_only`. It is not withheld and yields no evidence.
- Any change whose generation rises without a new revision stays `changes_withheld`, exactly as today. Examples are a replica-count change or a strategy change: a spec change that is not a rollout.

**Why the coverage claim stays true.** The batch still claims that every change up to the proving resourceVersion was delivered and examined. The classification only states, from a field the API server maintains, that the desired state did not change. No mechanism reads Deployment status today, so no contradiction is hidden. If a future mechanism does read status, it must consume these events instead.

**Tests:**
- A status-only update is `status_only` and the batch is complete.
- A generation increase without a revision change (for example `kubectl scale`) stays `changes_withheld`.
- A missing or non-integer generation stays withheld.
- A generation that regresses is refused.

### M12b: a pending Pod observation is *superseded*, never filled in

**Change.** A Pod event that cannot be converted because it is pending counts as **superseded** only if a later event of the same UID, within the same proof, converts. Otherwise it stays `changes_withheld`. No required field is ever invented.

**Why it is safe.** A pending pod has no running container, so it cannot have written a symptom. Its later, scheduled version carries the node, owner and restart count. Its `ADDED` event's observed bracket remains the creation bound used for log brackets.

**Tests:**
- Pending then scheduled is superseded.
- Pending and never scheduled stays withheld.
- Pending then deleted stays withheld.
- A later version that also fails to convert stays withheld.

### M12c: the list snapshot opens the first proven batch

**Change.** The listed objects go into the first proven `complete` batch, instead of a separate `partial` / `continuity_lost` batch. Its `watch_continuity` basis already starts at `list_first_page_received` with the list's resourceVersion. The batch then states: "the state at the start anchor, plus every change until the end anchor". The listed objects keep only their `event` times on the unknown API-server clock, so the engine never orders them by a collector time.

**When it does not apply.** A truncated list, or a segment that is not proven, keeps the current partial batches.

**Tests:**
- A clean list plus watch gives one complete batch that contains the snapshot.
- A truncated list stays partial.
- A segment that is not proven stays partial.
- Listed objects carry no `observed` time.
- Profile-3 recordings converted under the old rule remain byte-identical when replayed by the old converter version. This needs a recording version bump (0.6) so old bundles are never re-derived differently.

### M12d: the plan window is the jointly verified interval

**Change:**
- The plan window becomes the interval verified for **every** mandatory acquisition. It starts at the latest start anchor and ends at the earliest end anchor.
- Evidence outside it is not part of the investigation. It is left out of the bundle and **counted in the report**, by acquisition and kind.
- A run whose mandatory acquisitions share no verified interval keeps today's behaviour, and all of its gaps.

**Why it is acceptable.** The window is the stated scope of the investigation. Within it, every mandatory acquisition is proven, so a cause or contradiction inside it is covered. Something outside it is outside the investigation by definition. The report and the dashboard must say so plainly.

**Tests:**
- The window equals the joint interval.
- Excluded evidence is counted.
- An acquisition with no proof keeps its gaps.
- A symptom just inside the window is ordered against the rollout as before.

## What would remain true

- Nothing is marked complete without a basis, and log continuity never implies watch continuity.
- Every remaining failure stays a gap, and every gap still limits the mechanisms that need its kinds.
- The six pinned digests, the profile-1, 2 and 3 results, and migrations `0001`–`0008` are unaffected. M12c would need a new recording version so earlier recordings convert exactly as before.

## Recommended order

1. Approve or adjust M12a–d **together**: P1 needs all four.
2. Implement them in the CA-P2-007a slice, test first.
3. Measure against the approved development-set thresholds.

**Until then, the honest result on the kind cluster is as follows:**
- Log coverage proven (batch 0.3).
- Typed limit change observed.
- Every symptom ordered after the rollout.
- The investigation abstains on the four causes above.
