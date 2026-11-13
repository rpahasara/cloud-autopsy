# CA-P2-005b — ordering by Kubernetes `observed` brackets (engine plan)

**Status:**
- **This is a documentation-only plan for product-owner approval.**
- No engine, UI, database or contract change is made. Nothing is merged or deployed.

**Base:** stacked on CA-P2-004f (draft PR #37, `bc2eaff`), which introduced `observed` timestamps (observation kinds 0.3, contract profile 3).

**Goal:** let the engine order evidence by collector-observed brackets where, and only where, that ordering is trustworthy, without any new route to a false causal conclusion.

## 1. What the engine does today (reviewed)

- **Timeline** (`engine/timeline.py`, `ca-timeline-rules/0.1-provisional`):
  - it lists **every** timestamp of every member as its own entry, so 0.3 records already show their `observed` entries;
  - `adjacent_orderings` applies `timeinterval.compare` to neighbouring entries;
  - display order is not chronology.
- **Causal ordering** goes through **one function**: `timeline.event_order(a, b, domains)`, reached through `mechanisms._Context.order`. It compares the two records' **`event`** stamps with `timeinterval.compare`. Every mechanism rule uses it:
  - `_ordered_chain` (change → load, load → symptom, rollout → symptom);
  - `_not_before` (ambiguous logs);
  - both contradiction checks (a symptom before the change or the rollout).
- **Fail-closed behaviour comes from the time contract and is unchanged:**
  - overlap gives `unordered`;
  - a `step_declared` or unknown continuity gives `unordered`;
  - different domains need declared, bounded offsets, so an `unknown` clock never orders across domains;
  - resourceVersions are never an input.
- **Causation is not ordering.** A hypothesis is `supported` only when every prerequisite is satisfied: a typed limit-lowering change, a mapped symptom, the right pod identity and the right scope. Any limiting gap or unknown makes it `unresolved`; any contradiction makes it `contradicted`. The outcome is `resolved` only with a symptom seen, exactly one supported hypothesis and no unresolved one.
- **Versions:**
  - a plan pins `rule_versions`, and `engine/inputs.py` refuses any plan whose `rule_versions` differ from the single built-in set;
  - the result records `engine_version` (a constant) and the plan's `rule_versions`;
  - the database stores `engine_version`, `catalog_version` and `timeline_rules_version` as free text (no CHECK on their values), and checks only the result contract version (`0.2`);
  - verify-on-read **re-executes the engine** and requires identical bytes.

**Consequence:** a new ordering rule must be selected by the plan's pinned rule versions. A replay of any stored result must use exactly the rules it was produced with.

## 2. Proposal (smallest change)

### 2.1 Timestamp-selection policy: `ca-timeline-rules/0.2-provisional` (decision E1)

`ordering_stamp(evidence, rules)` chooses **one** stamp per piece of evidence. Ordering is then `timeinterval.compare(ordering_stamp(a), ordering_stamp(b), domains)`, exactly as today.

| Rules pinned | Evidence | Stamp used |
|---|---|---|
| timeline 0.1 (every existing plan) | any | `event` (today's behaviour, byte for byte) |
| timeline 0.2 | carries an `observed` stamp (only records labelled kinds 0.3 can) | **`observed` only**; there is **no fallback** to `event`, even when `observed` cannot order |
| timeline 0.2 | no `observed` stamp | `event` |

**Why `observed` only, without fallback:**
- For a watched change, the `event` stamp is a server-clock time such as `creationTimestamp`, not the time of the change.
- Falling back to it when the bracket cannot order would let a weaker stamp decide an ordering the stronger one refused.

**Everything else stays with the time contract:**
- `observed` brackets are on the collector's clock (status `unknown`, continuity `declared_continuous` or `step_declared`);
- they order only against stamps in the **same** domain, or against domains with a declared, bounded relation (none exists today);
- overlap, touching within a millisecond, a step or unknown continuity stay `unordered`.

**Never used:** resourceVersions, ingestion order, display order or batch sequence.

**Alternative (not recommended):** compare every admissible pair of stamps and order only when no pair contradicts. It is more expressive, but harder to explain, and it lets two different time meanings for one record compete.

### 2.2 What does not change
- **Mechanism catalog** (`ca-mechanism-catalog/0.1`): the same mechanisms, prerequisites, symptom mapping and scope rules. Hypothesis IDs, which digest the catalog version, are unchanged.
- **Gap and contradiction rules,** pod-identity ambiguity, and cluster and namespace isolation.
- **The result contract** (`ca-investigation-result/0.2`): same shape. The result already records `rule_versions`, so a reader knows which policy produced each ordering.

### 2.3 Rule profiles (decision E2)
- **Like contract profiles:** `RULE_PROFILES = (profile 1: today's five rule versions, profile 2: the same, with timeline-rules 0.2)`, and `inputs.py` accepts a plan pinning exactly one profile.
- **Recorded versions:** `timeline.build` records the pinned timeline-rules version. `result.build` keeps `engine_version` = `ca-engine/0.1-provisional`; the ordering policy is a timeline rule, and the engine code serves both profiles.
- **Allowed pairs:** rule profile 2 is allowed **only** with contract profile 3 (the only one whose records can carry `observed`). Any other pairing is refused by `inputs.py`.

### 2.4 Who pins rule profile 2 (decision E3)
- **Opt-in only.** `k8s_watch_recording.convert(..., rule_profile=2)` and `tools/collect_k8s.py --ordering-rules 0.2`. The default stays rule profile 1.
- **Existing bundles** keep the rules they pinned. Every 0.4 bundle from PR #37 pins profile 1 and replays exactly as before; nothing is re-labelled or re-investigated.
- **Replay check:** `verify_bundle` reads the rule profile the bundle's plan pins and re-derives with it, so either profile replays byte-identically.

### 2.5 Database (decision E4)
**No migration is needed:**
- result rows store the rule versions as free text under the unchanged result contract 0.2;
- plan rows have no CHECK on `rule_versions`;
- old and new results coexist, and each verifies on read by re-executing the rules it pinned.

A database test proves this before anything is merged (§4).

### 2.6 What this slice will and will not achieve (decision E5)
**It will:** order collector-observed Kubernetes evidence among itself (rollout, ReplicaSet, pod and Event changes) where the brackets are separated. Contradictions such as "a pod restarted before the rollout" become provable where they really hold.

**It will not make collector investigations resolve.** The mechanisms still need:
- a **symptom** (`log_line`/`alert_firing`), which the collector does not read;
- **typed limit values**, which are withheld.

Ordering a symptom against a collector bracket would need a **proven relation between the log clock and the collector clock**. None exists, and declaring one would be a separate decision. Collector-only and real-cluster investigations therefore keep abstaining. **That is the correct result.**

## 3. Causal-correctness guarantees (unchanged rules, restated as acceptance criteria)
- Ordering alone never satisfies a mechanism. A typed limit-lowering change, a mapped symptom and a trusted pod identity are each still required.
- Missing symptoms (`no_symptom_observed`) and unmapped or non-numeric values still prevent support.
- Limiting gaps, `unresolved` hypotheses and contradictions apply exactly as now. A profile-3 batch that is `partial` (`continuity_unproven`, `changes_withheld`, `event_limit`) is a gap.
- Joins stay inside one registry-bound `(cluster_id, namespace)`. Ordering never relaxes scope.

## 4. Tests (acceptance criteria)
Offline, engine-level, with synthetic profile-3 fixtures as in `tests/engine/test_watch_fault_injection.py`, run under **both** rule profiles where meaningful:

| # | Case | Expected |
|---|---|---|
| T1 | Strictly separated `observed` brackets (rollout, then pod and symptom, all in the collector domain) | Rules 0.2: `before` (basis same-domain), positive control **resolved**. Rules 0.1 on the same evidence: `event` stamps decide, as today |
| T2 | Overlapping brackets; brackets touching inside one millisecond | `unordered` (overlap), `ordering_unknown`, abstained |
| T3 | Evidence without `observed` (kinds 0.1/0.2 records in a profile-3 run) | Its `event` stamp is used, as before |
| T4 | A record with `observed` whose domain is `step_declared` or of unknown continuity | `unordered`, no fallback to `event`, abstained |
| T5 | Mixed clocks: collector-observed rollout against node-clock logs (unknown or offset-declared domains with no relation to the collector) | `unordered` (unknown clock), abstained |
| T6 | Cross-cluster and cross-namespace evidence with separated brackets | Never joined: no prerequisite satisfied across scopes |
| T7 | Gaps (a rollout in a `continuity_unproven` batch, a relist gap) and contradictions (a symptom bracket before the rollout bracket) | Abstained with `limiting_evidence_gaps` / `contradicting_evidence_present` |
| T8 | Negative control: ordering established (rollout before symptom) but causation not (an image-only rollout with no field changes, or a non-lowering value) | `not_supported`, abstained (`no_supported_hypothesis`) |
| T9 | Positive control: every prerequisite truly supported under rules 0.2 | `resolved`, `rollout_limit_reduction`, citing the observed-ordered pair |
| T10 | Deterministic replay: the same input gives byte-identical results under each profile; verify-on-read re-executes with the pinned profile | Identical bytes |
| T11 | Historical results: the six pinned digests, the semantic views, every example bundle, recording 0.1–0.4 replays and all stored-result tests | Unchanged |
| T12 | Profile pairing: rule profile 2 with contract profile 1 or 2, or an unknown rule version | Refused by `inputs.py` |
| T13 | Database (CI): a profile-1 and a profile-2 run in one database; both stored, verified on read and equal to offline. A forged result claiming the other profile fails verification | Pass; no migration |
| T14 | ResourceVersions: two records whose resourceVersions suggest an order but whose brackets overlap | `unordered`; the resourceVersion plays no part |

## 5. <a id="pr37"></a>PR #37 review: findings that bear on ordering (recorded separately)

| # | Finding | Risk | Recommendation |
|---|---|---|---|
| R1 | **The collector clock domain id is the fixed string `ca-collector`.** The approved 004f plan said `ca-collector-<session>` | Low today, because a bundle holds one session. Across sessions, brackets share a domain id but are anchored to different wall readings. Any future input mixing sessions would make same-domain ordering rest on wall-clock accuracy, not the monotonic clock | **Fix in PR #37 before it merges:** a session-specific domain id (a one-line collector change, re-pinning nothing historical). Rules 0.2 must also require one collector domain per investigation |
| R2 | `k8s_object_deleted` has an `event` stamp in the collector domain (the same bracket as `observed`) | None today (no mechanism reads deletions). Under rules 0.1, deletion events could be ordered against other collector-domain `event` stamps, and there are none | Keep. Under rules 0.2, deletions use `observed` like everything else |
| R3 | In profile-3 runs under rules 0.1, the **timeline** already lists `observed` entries, and its `adjacent_orderings` can state `before` between neighbouring collector-domain entries | Descriptive only (mechanisms do not read it), and correct per the time contract. A reader could mistake it for causal use | Note in the dashboard and record wording. No rule change |
| R4 | `observed` brackets on **unverified** evidence (from `partial` batches) are still causally sound, but the batch is a gap | The gap rules already make such hypotheses unresolved | Keep. T7 covers it |
| R5 | Step detection samples wall-clock drift only at probes, while brackets come from the monotonic clock | Conservative: a wall step never corrupts a monotonic bracket, but it still fails ordering closed | Keep (fail closed). A later refinement could separate wall-anchor accuracy from monotonic continuity |
| R6 | Pending pods and status-only Deployment changes are unconverted, so their segments are `partial` | Under rules 0.2 those segments are gaps, so rollout hypotheses stay unresolved on real clusters | Expected. Real resolution needs the evidence kinds and a symptom source (§2.6) |

## 6. Decisions requested

| # | Decision | Recommendation |
|---|---|---|
| E1 | Selection policy: `observed` only when present, no fallback (§2.1) | Approve |
| E2 | Version changes: **`ca-timeline-rules/0.2-provisional` only**; engine, catalog, result and clock-declaration versions unchanged; rule profiles 1 and 2; rule profile 2 only with contract profile 3 | Approve |
| E3 | Opt-in: the converter and CLI choose rule profile 2 explicitly; existing bundles keep profile 1 | Approve |
| E4 | No database migration; proven by T13 | Approve |
| E5 | Accept that collector-only investigations still abstain; any log-to-collector clock relation is a separate, later decision | Approve |
| E6 | R1: make the collector domain id session-specific in PR #37 before merge | Approve |

## 7. Implementation scope, once authorized
- **Engine:**
  - `engine/__init__.py`: rule profiles;
  - `engine/timeline.py`: `ordering_stamp` and a profile-selected rule version;
  - `engine/mechanisms.py`: `_Context.order` uses `ordering_stamp`;
  - `engine/inputs.py`: profile and pairing checks.
- **Recording and CLI:** `app/k8s_watch_recording.py` (opt-in `rule_profile`, profile-aware `verify_bundle`) and `tools/collect_k8s.py`.
- **Tests:** T1–T14, and the existing suites unchanged.
- **Not in scope:** new mechanisms or kinds; log collection; clock relations; result shape changes; database migrations; UI changes; merging or deployment.
