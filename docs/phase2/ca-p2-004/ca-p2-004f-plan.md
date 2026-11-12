# CA-P2-004f — continuous Kubernetes evidence acquisition by list and watch (implementation plan)

**Status (rev. 2, 2026-11-12):**
- **Approved for synthetic-only development:** F1, F2, F4 and F6–F10. **F6 is explicitly authorized:** migration `0008`, for the synthetic-only development environment, including the widened acquisition-batch version CHECK.
- **F3 and F5:** corrected in this revision as the product owner required ([§3.3](#rv), [§6.2](#observed), [§7](#contracts)). They need final confirmation.
- **Implementation is not authorized** until the final GO on the [execution scope](#scope): no watch code, no cluster and no merge.
- The only code in this revision is a characterization test of the **unchanged** time contract ([§6.2](#observed)).

When authorized, the work is synthetic-only, under the [pre-gate development authorization](../ca-p2-003/ca-p2-003b-1.md). It builds on [004e](ca-p2-004e.md), which is integrated into `main` at `d19893d`.

**Goal:** extend the read-only collector from one-off list snapshots to **continuous acquisition**, first against a disposable synthetic `kind` cluster:
- the collector proves exactly which periods it observed without a gap, and **records every other period as a gap**;
- evidence is placed in time only as far as the collector can actually establish;
- every existing investigation, contract version, migration and pinned digest stays byte-identical.

**What 004f will not do, stated up front.** A collector-only investigation will **still abstain** after 004f, even with perfect continuity:
- **No symptom source.** The engine needs a symptom (`log_line` with a mapped template, or `alert_firing`), and the collector reads neither. Pod logs are forbidden.
- **No limit values.** Both mechanisms need typed limit values. Sanitization drops env values, and ConfigMaps are excluded (004e D3).

004f removes **missing coverage** as a reason to abstain. It makes coverage gaps exact, and gives each observed change an honest time interval. Getting a resolved investigation needs a later, separately approved slice.

## 1. Decisions for the product owner

| # | Decision | Recommendation |
|---|---|---|
| F1 | **Collection protocol.** A paginated consistent **list**, then **watch** from the list's collection resourceVersion, with bookmarks requested ([§4](#protocol)). Streaming lists (`sendInitialEvents`) are not used in 004f | Approve |
| F2 | **What counts as verified coverage.** Only a period bracketed by **causal anchors on the collector's own clock**: the receipt of the list's first page at the start, and the send time of a **consistent-read progress probe** whose resourceVersion the watch later reaches, at the end ([§3](#establish)). Receiving events or bookmarks never extends coverage by itself | Approve |
| F3 | **Comparing resourceVersions** (rev. 2). Inside the collector's continuity proof only, resourceVersions of the **same resource type** in **one session** are compared as **arbitrary-size decimal integers**, by length and then lexicographically, on the documented basis in [§3.3](#rv). A separate input-size limit fails closed. The engine still never uses resourceVersions for chronology | Corrected; confirm |
| F4 | **Clocks.** Collector times come from one monotonic clock anchored to a single wall-clock reading. The collector's clock domain declares continuity only when no wall-clock step was detected; otherwise it is `step_declared`, which fails closed. **No measured API-server offset**: the API-server and component clocks stay `unknown` ([§6](#time)) | Approve |
| F5 | **Contract versions** (rev. 2). A third contract profile: acquisition batch **0.2** (a `coverage_basis` that is checked against the recording, plus new partial reasons) and observation kinds **0.3** (an `observed` timestamp and an explicit deletion kind). The **time-interval contract is unchanged**: a test shows it already represents the observed brackets conservatively ([§6.2](#observed)). Collector recording **0.4** at adapter level ([§7](#contracts)) | Corrected; confirm |
| F6 | **Migration `0008`** (additive, forward-only). It lists the new versions as supported, and widens the acquisition-batch version CHECK from "= 0.1" to "0.1 or 0.2". No stored row or existing migration changes ([§7.4](#migration)) | **Authorized** for the synthetic-only development environment, with regression tests |
| F7 | **RBAC.** Add `watch` to the existing Role on the same four resources in `ca-demo` only, and lengthen the token to 30 minutes. Still no Secrets, ConfigMaps, subresources, writes or cluster scope ([§8](#rbac)) | Approve |
| F8 | **Bounds** (defaults; [§10](#bounds)): session at most 10 minutes; at most 10,000 events per resource; lines at most 1 MiB; 90 s idle timeout; probes every 15 s; at most 3 reconnects and 2 relists | Approve |
| F9 | **CI.** A **separate** job, `collector-watch-kind`, with the same pinned tools and digest-pinned images as `collector-kind`, run on collector-path PRs and by manual dispatch. It is not a required check on `main` ([§11.3](#ci)) | Approve |
| F10 | **Engine.** The engine and mechanism catalog are unchanged. Engine-level fault tests use **offline synthetic fixtures** that add symptom and limit evidence, to prove that gaps block conclusions. No real-cluster resolution is claimed ([§11.2](#engine-tests)) | Approve |

## 2. Scope

**In scope (after authorization):**
- **Resources:** list and watch on Pods, Deployments, ReplicaSets and Events in one namespace, `ca-demo`.
- **Proof:** consistent-read progress probes, and the continuity proof built from them.
- **Gaps:** explicit gaps for every period that is not proven.
- **Recording and evidence:** a sanitized collector recording (`ca-k8s-recording/0.4-provisional`), deterministic offline replay, and the new contract profile (F5) with migration `0008` (F6).
- **Tests:** offline tests with a fake TLS watch server, engine-level fault tests, and the disposable `kind` job.

**Out of scope:**
- any real, shared or existing cluster;
- ConfigMaps, Secrets, logs, exec, metrics and cluster-scoped resources;
- streaming lists, and server-side apply or any write;
- measured API-server clock offsets;
- new engine mechanisms or symptom sources;
- dashboard changes, deployment, cloud credentials and runtime dependencies.

## 3. <a id="establish"></a>What the collector can and cannot establish

### 3.1 The basic facts it relies on
1. **A response comes after its request was sent, and before it was received** (real-time causality). The collector reads both moments on its own monotonic clock.
2. **A consistent read reflects at least every committed change.** A list request without `resourceVersion` returns a collection resourceVersion **at least as new as every change committed before the API server handled the request**. That handling happens after the client sent it.
3. **A watch started at resourceVersion `a`, and accepted without `410`, delivers every change of the watched collection with a resourceVersion greater than `a`, in order.** A bookmark with resourceVersion `b` means every change up to `b` has been delivered.
4. **resourceVersions of one resource type are ordered** and grow with commit order (F3, on the documented basis in [§3.3](#rv)).

### 3.2 Facts, and how each is recorded

| Fact | Established? | Basis |
|---|---|---|
| The starting state is one consistent collection | Yes | 004e pagination rules: the same collection resourceVersion `a` on every page |
| Every change committed **after the receipt of the first list page** is delivered by the watch | Yes, while continuity holds | Fact 2: state `a` was committed before that response. Facts 3–4: later commits have resourceVersions above `a` |
| Every change committed **before the send time `t_p` of a progress probe** that returned resourceVersion `p` is delivered, **once the watch has delivered an event or bookmark with resourceVersion ≥ `p`** | Yes | Facts 2–4. This is the **only** way coverage can end at a known time |
| **Verified coverage** | Yes, for exactly `[ceil(first list page received), floor(t_p))` on the collector clock, for the latest proven probe `p` of an unbroken segment | Fact 1 orders the two client times. The API-server clock is never needed |
| A bookmark or event, received without a probe being proven | **No coverage** | It shows progress in resourceVersion terms, but places nothing in time. Its server-side time is unknown |
| The watch connection stayed open | **No coverage by itself** | A silent connection proves nothing. Only resourceVersion continuity plus a proven probe does |
| A disconnect followed by a resume from the last delivered resourceVersion, accepted without `410` | Continuity holds **through** the disconnect, once a later probe is proven | Fact 3. The proof rests on resourceVersions, not on the connection |
| A `410 Gone`, a refused resume or a relist | **Continuity is broken.** The period from the last proven probe to the new list's first-page receipt is a gap | No proof spans it |
| **When a change happened**, on the collector clock | Bounded: after the send time of the latest probe (or list request) whose resourceVersion is **below** the change's, and no later than when the event was received | Facts 1–4. The interval is recorded as an `observed` timestamp ([§6.2](#observed)) |
| When a change happened on the API-server or component clock | **No.** `creationTimestamp`, Event `firstTimestamp`/`lastTimestamp` and condition times are kept raw in a domain declared `unknown` | 004e D4 is unchanged |
| The order of two observed changes | Only when their `observed` intervals do not overlap, compared within the collector's clock domain | The time contract's same-domain rule. resourceVersions never order evidence |
| That nothing happened in a covered period | Yes, **for the declared query only** (that resource, in that namespace, with the documented withholding), producing an `empty` batch | Nothing is claimed about other resources, namespaces or kinds of evidence |
| That a period with no proof had no changes | **Never** | It is a gap |

### 3.3 <a id="rv"></a>Comparing resourceVersions (F3, rev. 2)

004e used resourceVersions for **equality only**. Proving a probe requires checking that a delivered resourceVersion is **at least** the probe's, which is an ordering.

**Documented basis.** The product owner's review of the Kubernetes **v1.37** API documentation (2026-11-12) confirms that:
- resourceVersions are ordered **within the same resource type**;
- they may be compared as **arbitrary-size decimal integers**.

The implementation record will cite the exact documentation page and section, and the recording names the rule it used (`rv_comparison: "k8s-1.37-decimal"`), so a reviewer can reject it without re-collecting.

**The rule:**
- **Valid value:** a non-empty string of ASCII digits with **no leading zero**, matching `[1-9][0-9]*`. There is no integer-width assumption; values are never converted to a fixed-size integer.
- **Comparison:** the longer string is greater. Two strings of equal length compare lexicographically, which for these strings equals numeric order. Equal strings are equal.
- **Boundaries:** values are compared only when they belong to the **same resource type** (group, version and resource) **and the same collector session** against one API server. Examples:
  - a Pod resourceVersion is never compared with an Event or Deployment one;
  - values from different sessions, recordings or clusters are never compared.
- **Input limit (security, separate from the rule):** a resourceVersion longer than **128 characters** (the existing evidence-contract bound for `source_version`) is refused.
  - The segment fails closed (`invalid_response`), and no coverage is claimed past its last proven probe.
  - The limit exists to bound memory and parsing; it does not describe what the API server may send.
- **No regression:** a delivered resourceVersion lower than or equal to the previous one in the same watch stream, or a duplicate, is `invalid_response` for that segment.
- **Never used for chronology:** a resourceVersion never orders evidence and never sets chronology. The engine and the time contract are unchanged.

**Comparison tests** (offline, in the contract and collector suites):
- equal length;
- different lengths, including `"9"` against `"10"` and values longer than 20 and 40 digits;
- equality;
- refusal of leading zeros, signs, spaces, non-ASCII digits, empty strings and values over 128 characters;
- refusal to compare across resource types or sessions;
- regression and duplicate detection;
- the property that the comparison matches Python's arbitrary-precision `int` ordering over many generated values (used only as a test oracle).

## 4. <a id="protocol"></a>Protocol (per resource)

All four resources run independently. Their coverage and gaps are never joined into one view.

1. **Initial list.** A paginated consistent list, with the 004e safeguards: the same collection resourceVersion `a` on every page, opaque continue tokens, and a restart from scratch after `410`. The collector records the send time of the first request and the receipt time of the first page.
2. **Watch.** `GET …?watch=1&resourceVersion=a&allowWatchBookmarks=true&timeoutSeconds=N`, where `N` is at most the session's remaining time.
   - The response is newline-delimited JSON, parsed line by line under strict limits.
   - Each line is `ADDED`, `MODIFIED`, `DELETED`, `BOOKMARK` or `ERROR`. Anything else is `invalid_response`.
3. **Progress probes.** Every 15 s (F8), `GET` the same list path with `limit=1` and no `resourceVersion` (a consistent read).
   - The collector records the send time `t_p` and the returned collection resourceVersion `p`.
   - The returned item and continue token are **discarded unread** and never sent again.
   - A probe is **proven** when the watch delivers an event or bookmark with resourceVersion ≥ `p`.
4. **Reconnecting.**
   - **Triggers:** an idle timeout, a closed connection, or the server's `timeoutSeconds`.
   - **What happens:** the watch resumes from the **last delivered resourceVersion**, at most 3 times with bounded backoff (F8).
   - **If the resume is accepted:** continuity is kept ([§3.2](#establish)).
5. **`410` or expiry.** An `ERROR` event with code 410, or a 410 on resume.
   - The current segment **ends at its last proven probe**.
   - Events received after that probe are kept as **unverified** observations.
   - The collector relists, at most 2 times, and starts a new segment. The period in between is a gap.
6. **Errors.**
   - `401`/`403` (for example a revoked binding or an expired token): **denied**, the session ends, and the rest of the window is a gap.
   - `429` and `5xx`: bounded retry, then a gap.
   - Invalid lines, oversize lines, resourceVersion regression, or an object outside the namespace: `invalid_response`. The segment ends at its last proven probe.
7. **Shutdown.** This covers the end of the session duration, `SIGINT`/`SIGTERM`, or a bound being reached.
   - The collector sends one **final probe** and waits at most 90 s for it to be proven, then closes everything.
   - If the final probe is not proven, the tail after the last proven probe is an unverified `partial` batch.
   - Nothing is ever claimed past the last proven probe.

## 5. Gaps

Every part of the plan window outside verified coverage is a **gap**, recorded in the batches and turned into frozen-input gaps by the existing gap policy:

| Situation | Batch result | Coverage counted |
|---|---|---|
| Initial list state (the starting snapshot) | `partial`, `continuity_lost`, as in 004e (it describes a state, not changes) | No |
| A segment, from first-page receipt to a proven probe, where **every** change received became evidence | `complete` if changes were observed, `empty` if **no change of any kind** was received, with `coverage_basis` ([§7.2](#batch)) | **Yes** |
| A proven segment in which **any** change was withheld or not turned into evidence (Events involving Secrets, or anything outside the projection) | `partial`, `changes_withheld`, observations kept, with the withheld count in the report | **No** |
| Events after the last proven probe (tail, disconnect, 410, shutdown) | `partial`, `continuity_unproven` | No |
| Bounds reached (events, bytes or duration) | `partial`, `event_limit` or `response_too_large`, truncated | No |
| Denied, unavailable, rate-limited, timed out or invalid | `denied` or `failed` with the 004e reasons | No |
| Clock step detected ([§6](#time)) | Coverage is still recorded, but the clock domain declares `step_declared`. All ordering of collector-domain evidence fails closed | Coverage yes; ordering no |
| A period between two segments | No batch: a coverage gap | No |

The batch cursor chain stays unbroken (`cursor.after = "rv:<last resourceVersion>"`), so the frozen input can tell what was proven from what was not.

## 6. <a id="time"></a>Time and uncertainty (F4)

### 6.1 Clocks
- **The collector's clock domain**, `ca-collector-<session>`:
  - **Readings:** one wall-clock reading at session start, plus monotonic durations. Every collector time is that start reading plus a monotonic offset, rounded **outward** to milliseconds.
  - **Step check:** a wall-clock reading is taken at every probe, and its drift against the monotonic clock is checked. Drift over 250 ms marks the domain `step_declared` for the whole session.
  - **Declaration:** status `unknown` (no offset to any other clock is claimed), and continuity `declared_continuous` only when the step check passed.

  Under the existing time contract, same-domain intervals are then ordered without any offset. A step fails closed.
- **API-server and component clocks** (`creationTimestamp`, Event times, condition times): kept raw in a domain declared `unknown`, as in 004e. They are never ordered against collector times.
- **No HTTP `Date` header** or other measured offset is used, and none is recorded as a fact.

### 6.2 <a id="observed"></a>The `observed` timestamp: why the existing contract already fits (F5.1, F5.2)

**What is known.** For a watch event, the commit instant `c` satisfies `L < c < U` on the collector clock:
- `L` is the send time of the latest probe, or of the list request, whose resourceVersion is **below** the event's;
- `U` is the event's receipt time.

**How it is encoded,** in the existing `ca-time-interval/0.2-provisional` contract with no change:
- `raw` = `L` in RFC 3339 with nine fraction digits (UTC);
- `declared_precision_ns` = `U − L`.

**Why that is conservative, from the contract's established meaning:**
1. A parsed timestamp means "the instant lies in `[raw, raw + effective precision)`", where effective precision is the larger of the text's precision and the declared one. Nine fraction digits give a text precision of 1 ns, so the interval is exactly `[L, U)`. It contains `(L, U)`, so it is conservative, never narrower.
2. The millisecond interval the contract derives is `[floor(L), ceil(U) − 1]` (inclusive ms, meaning `[floor(L), ceil(U))`). It is widened outward by less than 1 ms on each side, and never narrowed.
3. Two `observed` times in the collector domain are ordered only when one's upper millisecond is strictly below the other's lower one. That holds only if every instant of the first precedes every instant of the second. Overlaps, and touches inside a millisecond, stay unordered.
4. A `step_declared` or unknown continuity fails ordering closed. A different clock domain (the API server's, declared `unknown`) is never ordered against the collector's.
5. **Width limits:** a bracket wider than the contract's one-day precision limit is refused, so it can never be recorded. A zero-width bracket is impossible (`U > L` on the monotonic clock) and is also refused.

**Proof by test.** `tests/contracts/test_observed_bracket.py` (14 tests, in this revision) checks all of the above against the **unchanged** contract code:
- exact lower and upper bounds;
- fractional milliseconds and exact millisecond edges;
- containment and tightness over 5,000 deterministic brackets;
- separated, touching, overlapping and inside-a-millisecond brackets;
- clock step, unknown continuity and cross-domain refusal;
- the one-day and zero-width limits;
- an exact record round trip.

**Conclusion:** **no time-interval contract change is needed.** The `observed` meaning is carried by the timestamp kind's name, which observation kinds 0.3 introduces ([§7.3](#kinds)). The contract's meaning of a timestamp does not change.

## 7. <a id="contracts"></a>Contract compatibility proposal (F5, F6)

### 7.1 Principles
- **No existing version changes meaning.** Contract profiles 1 (the baseline) and 2 (004d, kinds 0.2) are byte-for-byte unchanged, along with every stored row, recordings `0.1`–`0.3` and the six pinned result digests.
- **One profile per plan.** A plan pins one whole profile. A new **profile 3** = profile 2 + `acquisition-batch` **0.2** + `observation-kinds` **0.3**. Only collector-watch plans pin it.
- **Exact versions only.** Exact-match versioning still rejects any record that does not match its plan's pinned version.

### 7.2 <a id="batch"></a>`ca-acquisition-batch/0.2-provisional`
- **All 0.1 fields and rules, unchanged.**
- **One new required field, `coverage_basis`:**
  - `null` for `partial`, `failed` and `denied` batches.
  - For `complete` and `empty`, **required**, and exactly `{"kind": "watch_continuity", "resource_type", "session_id", "clock_domain_id", "rv_comparison": "k8s-1.37-decimal", "start_anchor": {"kind": "list_first_page_received", "at_ms", "resource_version"}, "end_anchor": {"kind": "probe_sent", "at_ms", "resource_version", "proven_by_resource_version"}}`.
- **Checks in the contract itself:**
  - `coverage.start` must equal `start_anchor.at_ms`, and `coverage.end` must equal `end_anchor.at_ms`, so coverage can never be wider than its basis;
  - every resourceVersion must be valid under [§3.3](#rv);
  - the start resourceVersion must not exceed the end one, and `proven_by_resource_version` must be at least the end anchor's;
  - `cursor.after` must be `rv:<proven_by_resource_version>`.

  A `complete` or `empty` batch without a valid basis is refused.
- **These checks are not enough by themselves.** They prove only that the basis is coherent, not that it is true. Truth is checked against the recording on replay ([§7.6](#replay-check)).
- **New partial reasons:** `continuity_unproven`, `event_limit` and `changes_withheld`.
- **Never evidence-complete or no-change when something is missing (F5.4):**
  - `complete` means every change received in the segment is an observation in the batch;
  - `empty` means no change of any kind was received, including withheld, out-of-projection or deleted objects;
  - otherwise the segment is `partial` / `changes_withheld`, and its coverage is not counted.
- **Frozen input:** sealing is unchanged. Clean batches are still `complete` or `empty`, untruncated and in the cursor chain. The basis is carried in the batch digest and shown in the batch listing.

### 7.3 <a id="kinds"></a>`ca-observation-kinds/0.3-provisional` (F5, rev. 2)

**This is the smallest compatible option.** Existing kind schemas are not changed for existing versions:
- **`observed` timestamp.** The optional timestamp kind `observed` is allowed for `pod`, `replicaset`, `deployment_rollout` and `k8s_event`, **only under a plan pinning 0.3**.
- **Labelling.** The 004d rule is that a record carries the registry version that introduced its kind. Rev. 2 states it precisely: a record carries **the earliest registry version under which that exact record is valid**.
  - A record **without** `observed` keeps its 0.1 or 0.2 label and is **byte-identical** to today's.
  - A record **with** `observed` is labelled 0.3. It is refused under 0.1 or 0.2 plans and by any reader that does not know 0.3.

  Nothing stored is re-labelled or reinterpreted.
- **Unchanged meanings:** existing timestamp kinds keep theirs (`event` is still the server-clock time 004e uses, such as `creationTimestamp`). Watch evidence adds `observed`; it does not replace `event`.
- **Duplicates:** an object version (`uid` with resourceVersion) is turned into evidence once per session. A relist after `410` does not re-emit versions the watch already delivered. That avoids two records with the same identity and different content.

**Decision on Kubernetes `DELETED` events (F5.3):**
- **Represented as evidence.** Kinds 0.3 adds one new kind, **`k8s_object_deleted`** (`since` 0.3, evidence class `K8S-DELETE`, source kind `kubernetes_api`). Its attributes are:
  - `object_kind`: `Pod`, `ReplicaSet`, `Deployment` or `Event`;
  - `name` and `uid`;
  - `source_version`: the resourceVersion of the delete event;
  - a **required** `observed` time.

  It carries nothing else from the deleted object.
- **Why:** if deletions were only counted, every segment containing one would have to be `partial` / `changes_withheld` (F5.4), and no deletion could be placed in time. Representing them keeps `complete` truthful.
- **Engine:** unchanged. No mechanism reads `k8s_object_deleted` in 004f.

### 7.4 <a id="migration"></a>Migration `0008` (F6)
**Forward-only and additive:**
- Insert `acquisition-batch` 0.2 and `observation-kinds` 0.3 into `ca.contract_version_supported`.
- Replace the CHECK on `ca.acquisition_batch.contract_version` with "0.1 or 0.2". Every existing row satisfies both the old and the new check.
- Ingest records each batch's own version instead of the module constant.

**Not changed:** `0001`–`0007`, stored bytes and grants.

**Regression tests (required by the F6 authorization):**
- **Before and after `0008` on one database:**
  - every stored run, batch, evidence version, frozen input and result row is byte-identical, compared by digest and raw bytes;
  - every existing run still verifies on read;
  - the six pinned result digests are unchanged.
- **The migration chain:**
  - `0001`–`0007` checksums are unchanged;
  - `0008` applies only forward, once, and is refused if any earlier checksum differs.
- **Profile 3:** a profile-3 plan is refused before `0008` and accepted after it.
- **Version boundaries:**
  - a 0.2 batch under a profile-1 or profile-2 plan is refused;
  - a 0.1 batch under a profile-3 plan is refused;
  - an `observed`-time or `k8s_object_deleted` record under a 0.1 or 0.2 plan is refused.
- **The widened CHECK** still refuses any version other than 0.1 and 0.2.

### 7.5 Collector recording `ca-k8s-recording/0.4-provisional`
- **Same envelope as 0.3:** `provenance: collector`, server clock `unknown`, and no `snapshot_at` or `coverage` field.
- **Additions per resource:**
  - the initial list (as 0.3);
  - an ordered stream of sanitized entries: `sequence`, collector time in ms, `type`, the resourceVersion, and the projected object or its withheld or out-of-scope reason;
  - every probe (send and receipt times, resourceVersion `p`, and whether and when it was proven);
  - every reconnect, relist, error code and bound reached;
  - the clock-step check results.
- **Strict replay:** the converter works only from the recording and never reads a clock. Replaying it gives a byte-identical bundle and result.
- **The recording contains facts only, never claims.** It has no batch outcomes, coverage or basis. All of those are derived on conversion.
- **Unchanged:** recordings 0.1–0.3 and their pinned outputs.

### 7.6 <a id="replay-check"></a>Coverage claims are checked against the evidence, not trusted (F5.5)
- **Derived, never copied.** The converter **derives** every batch, coverage interval and `coverage_basis` from the recording's own entries. Nothing in a basis is copied from input.
- **Before a `complete` or `empty` batch is emitted, the converter checks against the recorded entries that:**
  1. the start anchor is the recorded first-page receipt of a **consistent** list (004e rules), with that collection's resourceVersion, for the same resource type and session;
  2. the end anchor is a **recorded probe**, with its recorded send time and returned resourceVersion;
  3. a **recorded watch entry** in the same segment carries `proven_by_resource_version`, and that value is at least the probe's ([§3.3](#rv));
  4. between the start anchor and that entry there is no `410`, error, refused resume, relist, regression, invalid line, bound or step marker;
  5. the batch's observations are **exactly** the projected changes in the stream with resourceVersions in `(start, proven_by]`, and nothing was withheld (F5.4).

  Any failed check gives `partial` (`continuity_unproven` or `changes_withheld`), never `complete` or `empty`.
- **A replay check tool** re-derives a bundle from a recording and refuses any supplied bundle that is not byte-identical. The offline tests and the `kind` job run it on every recording.
- **Forged inputs.** Tests feed forged recordings and forged bundles, which must be refused or downgraded:
  - a probe with no proving entry;
  - a proving entry from another resource type or session;
  - a basis whose times or resourceVersions differ from the entries;
  - an `empty` batch over a segment with withheld changes;
  - a bundle edited after conversion.

## 8. <a id="rbac"></a>Security and RBAC changes (F7)

**Role (`ca-demo` only), changed from 004e:** add `watch` beside `get` and `list` on `pods`, `events`, `deployments` and `replicasets`. **Nothing else.**

**Still forbidden:**
- `configmaps` and `secrets`;
- every subresource;
- every write verb;
- any other namespace;
- every cluster-scoped resource;
- ClusterRoles and ClusterRoleBindings;
- token requests.

**Client allowlist, changed:**
- **Watch** may add exactly `watch=1`, `resourceVersion=<decimal>`, `allowWatchBookmarks=true` and `timeoutSeconds=<1..600>`.
- **Probes** use `limit=1` only.
- **Unchanged:** paths, methods, redirects (refused), proxies (none), kubeconfig (none) and TLS verification.

**Tokens:**
- A 30-minute TokenRequest token, in a `0600` file inside a `0700` directory, deleted at teardown.
- An **open watch is not cut off when RBAC is revoked**. Exposure is therefore bounded by `timeoutSeconds` (at most the session length) and the token lifetime. The `kind` job shows that the **resume** after revocation is refused (`403`), so the window becomes a gap.

**Negative RBAC additions**, checked by `can-i` and by raw requests with the real token, all expected `403`:
- watch on Secrets and ConfigMaps;
- watch in `ca-other`;
- cluster-wide watch (`/api/v1/pods?watch=1`, `/api/v1/events?watch=1`);
- watch on nodes and namespaces.

**Unchanged:** the 22-request matrix from 004e.

**Review:** the self-built TLS client, now handling long-lived streaming responses, still needs an **independent security review** before any non-disposable cluster.

## 9. Sanitization before anything is kept

- **Parsing:** each watch line is parsed with the strict JSON parser under size and depth limits, then **projected immediately** with the 004e allowlist. The raw line is dropped. Projection runs before buffering, so the buffer only ever holds projected objects.
- **Dropped and withheld:**
  - `ERROR` lines: only their HTTP code and reason enum are kept. `Status.message` text is never read into a log, report or exception.
  - **Events involving Secrets** are withheld and counted (004e D6). The query's declared scope says so, and an `empty` batch means "no non-withheld Events".
- **Out-of-namespace objects** refuse the segment (`invalid_response`).
- **Never written:** messages, env values, annotations other than the revision, managedFields, tokens, continue tokens, bookmark annotations and headers.

## 10. <a id="bounds"></a>Bounds, timeouts and graceful shutdown (F8)

| Bound | Default | When reached |
|---|---|---|
| Session duration | 10 min (and `timeoutSeconds` ≤ what remains) | Graceful shutdown with a final probe |
| Events per resource | 10,000 | Stop that resource. The tail after the last proven probe is `partial` / `event_limit` |
| Line size | 1 MiB | `invalid_response`. The segment ends at its last proven probe |
| Projected buffer | 64 MiB per session | Same as the event limit |
| Idle read timeout | 90 s | Reconnect (counted) |
| Reconnects / relists | 3 / 2 | Gap for the rest of the window |
| Probe interval / final-probe wait | 15 s / 90 s | — |

**Writing and shutdown:**
- **Where data goes:** writes go only to the output directory, and the recording is written atomically when the session ends.
- **On a signal or bound:** the collector stops reading, closes sockets, flushes the projected buffer, writes the recording and report, and exits non-zero if any resource ended `denied` or `invalid`.
- **Never kept:** partial raw data is never kept.

## 11. Tests

### 11.1 Offline: a fake TLS watch server (every OS, in the existing offline job)
The fake server serves scripted lists, watch streams and probe answers over loopback TLS. **Each scenario asserts the batches, gaps, coverage and observed brackets exactly:**
- **Continuity:** list handoff; events then a bookmark at or above the probe resourceVersion give one `complete` or `empty` segment with the exact bracket.
- **No proof, no coverage:** bookmarks with no probe, a probe never proven, or a silent open connection all give **zero** verified coverage.
- **Disconnects:**
  - a resume accepted from the last delivered resourceVersion keeps continuity;
  - a resume refused with `410` gives a gap between the last proven probe and the relist, and unverified tail events.
- **Other faults, each with its expected gap:**
  - an `ERROR` 410 event mid-stream;
  - `401` or `403` on resume (revoked binding);
  - `429` and `5xx` storms;
  - truncated, oversize or malformed lines;
  - resourceVersion regression, duplicates and non-decimal resourceVersions (unprovable session);
  - an object from another namespace.
- **Bounds and shutdown:** the event limit, buffer limit and session end, plus `SIGTERM` during a segment, give a tail `partial`, never coverage past the last proven probe.
- **Clock step:** a simulated wall-clock jump against the monotonic clock declares `step_declared`, and ordering fails closed.
- **Leakage:** planted secrets in objects, `Status.message`, bookmark annotations and error bodies never appear in any file, log, exception, report, bundle or result.
- **Replay:** the 0.4 recording replays to a byte-identical bundle and result; the converter reads no clock.
- **resourceVersion comparison:** the [§3.3](#rv) test list.
- **Replay validation of coverage claims:** the [§7.6](#replay-check) forged-input cases.
- **Observed brackets:** `test_observed_bracket.py` (in this revision), plus end-to-end checks that every `observed` time in a converted bundle equals the bracket derived from its recorded probe and receipt times.
- **Compatibility:** all existing suites and the six digests are unchanged. Profile-1 and profile-2 plans refuse 0.2 batches and 0.3 kinds. The migration regression tests are in [§7.4](#migration).

### 11.2 <a id="engine-tests"></a>Engine-level fault injection (offline, synthetic fixtures)
Collector-only data cannot resolve (see the top of this plan). These tests use **synthetic** bundles that combine 0.4-style watch evidence with fixture-declared symptom (`log_line`) and limit evidence in the collector clock domain. They prove that **missing evidence never becomes a false conclusion**:

| Scenario | Expected |
|---|---|
| A limit-lowering rollout observed in a proven segment, then the symptom later in a non-overlapping interval, with no gaps | `resolved` (control case) |
| The same, but the rollout falls in a **gap** (410 or relist) | `abstained`, `limiting_evidence_gaps`, an `unobserved_change` placeholder |
| The rollout is only in an **unproven tail** (unverified) | `abstained` |
| Overlapping observed brackets for the rollout and the symptom | `abstained`, `ordering_unknown` |
| A clock step during the session | `abstained`, `ordering_unknown` |
| A symptom before the rollout | `abstained`, `contradicting_evidence_present` |
| Two candidate rollouts, one in a gap | `abstained`, never the visible one by elimination |

### 11.3 <a id="ci"></a>The `collector-watch-kind` CI job (F9)
**Setup:**
- Same pinned and checksum-verified `kind` and `kubectl`, same digest-pinned images, same 127.0.0.1-only cluster and synthetic workloads as `collector-kind`.
- The RBAC of §8 is applied.

**The negative RBAC matrix:** the 004e set plus the new watch refusals.

**Steps:**
1. **Start the collector** for a 4–6 minute session.
2. **Drive scripted changes:** a rollout, a scale change and a crash-looping Pod.
3. **Inject faults on the real cluster:**
   - delete the RoleBinding mid-session, so the resume after a forced reconnect gets `403` and the rest is a gap;
   - restart the API-server container, so the session reconnects and either resumes or ends in a gap, with whichever happened recorded truthfully;
   - run a session with an event limit of 5, which must end in `partial` / `event_limit`.
4. **Check the result:**
   - every scripted change appears either inside a proven segment or as unverified tail or gap evidence, **never silently missing**;
   - coverage never extends past a proven probe;
   - the investigation abstains offline and in a database-verified replay on the job's disposable PostgreSQL;
   - the leak scan is clean.
5. **Cleanup** always runs.

**Not on `kind`:** a real `410` cannot be forced reliably there; the fake server covers it.

**Not required on `main`:** the job stays optional, like `collector-kind`.

## 12. Delivery steps (after authorization)
1. **Contracts:** batch 0.2, kinds 0.3 and profile 3, with contract tests. Migration `0008` with database tests.
2. **Collector:** `watch.py` (the stream reader, probes and segments), allowlist additions, bounds and shutdown. A `--watch` mode in `tools/collect_k8s.py`.
3. **Adapter:** recording 0.4 conversion with strict replay.
4. **Offline tests:** the fake TLS watch server, plus the engine-level fixtures.
5. **CI:** `deploy/kind/` RBAC change and the `collector-watch-kind` job, with supply-chain entries unchanged (same tools).
6. **Records:** `ca-p2-004f.md`, and a draft PR with CI evidence reported faithfully.

## 13. Remaining risks
- **resourceVersion ordering (F3)** rests on the documented Kubernetes v1.37 behaviour for one resource type. A server that sends non-conforming values makes the session unprovable: it fails closed, with no coverage claimed.
- **Bookmark timing is chosen by the server.** Probes may be proven late, which shortens the coverage at the end of a session. The design only loses coverage, never invents it.
- **Long-lived connections** widen the self-built TLS client's attack surface. Independent review is still required.
- **Coverage is on the collector's clock.** Other sources (logs, alerts) need their own relation to that domain before cross-source ordering, which is a later slice.
- **Still abstains on collector data alone** (no symptom source, no limit values), by design.

## 14. <a id="scope"></a>Final execution scope for authorization
Authorizing this plan would permit exactly:
- **Contracts (F5):** acquisition batch 0.2 with the contract checks of §7.2, observation kinds 0.3 as in §7.3, and contract profile 3. The time-interval contract is **unchanged**.
- **Migration `0008` (F6)**, as authorized, with the §7.4 regression tests.
- **Code:** the watch collector with the §3.3 comparison rule, the recording 0.4 adapter with the §7.6 replay checks, offline and engine-level tests, and the `deploy/kind/` RBAC change (F7). All on a new branch from `main`.
- **One new CI job, `collector-watch-kind`** (F9), on GitHub-hosted runners only, with a disposable cluster and synthetic workloads.
- **Credentials:** a 30-minute ServiceAccount token inside that job only.

**Not permitted:**
- changes to existing contract versions, migrations `0001`–`0007`, stored bytes, recordings 0.1–0.3 or the six pinned digests;
- any existing or production cluster;
- ConfigMaps, Secrets, logs, writes or cluster scope;
- runtime dependencies or installs on your machine;
- engine or UI changes;
- merging or deployment.
