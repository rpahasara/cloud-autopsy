# CA-P2-004e — first isolated, read-only Kubernetes collector (implementation plan, amended)

**Status:**
- **Approved in principle:** D1, D3, D4, D5 and D6, for synthetic-only local-cluster development.
- **D2:** the scope (snapshot-only collection) is accepted. Its timing representation is **amended here (rev. 2)**, as the product owner required.
- **Not authorized yet:** implementation. Nothing may be done until the [final execution scope](#scope) is authorized:
  - no cluster is created and no access to any cluster is granted;
  - no dependency is installed and no workflow is enabled;
  - nothing is deployed.

When authorized, the work is synthetic-only, under the [pre-gate development authorization](../ca-p2-003/ca-p2-003b-1.md). Stacked on [004d](ca-p2-004d.md) (PR #31).

**Goal:** collect approved Kubernetes resources from a **disposable local `kind` cluster** running synthetic workloads.
- **Access:** the collector is read-only, least-privilege and namespace-restricted.
- **Output:** sanitized evidence in the existing versioned contracts and bundle workflow.
- **Honesty:** gaps are recorded as gaps, and nothing claims timing or coverage that was not verified.

## 1. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | **A stdlib-only HTTPS client** with a fixed allowlist of GET paths. No new runtime dependency ([§3](#client)) | Approved in principle |
| D2 | **Snapshot-only collection, with no claimed timing or coverage.** A paginated list is recorded as what it is: one collection, consistent at one opaque resourceVersion, observed between two client-clock timestamps. It is **never** placed on the plan timeline as covered. Every successful list becomes a `partial` batch (`continuity_lost`): observations kept, coverage not counted. See [§6](#timing) | **Amended, rev. 2** |
| D3 | ConfigMaps (and Secrets) are not collected and not in the Role | Approved in principle |
| D4 | The API-server clock is declared `unknown` | Approved in principle |
| D5 | A separate GitHub Actions `kind` job, disposable per run; offline tests on Windows | Approved in principle |
| D6 | Events whose involved object is a Secret are withheld and counted | Approved in principle |

## 2. Scope

**In scope:**
- **Resources:** Pods, Deployments, ReplicaSets and Events (core `v1`) in **one** namespace (`ca-demo`), using list with pagination.
- **Output:**
  - a **sanitized collector recording** in a new adapter format, `ca-k8s-recording/0.3-provisional` ([§6.3](#format));
  - the bundle (kinds 0.2), created through `k8s_recording.convert`;
  - a collection report with codes and counts only.

**Out of scope:**
- watch and any continuous or historical coverage (004f, which needs a contract decision);
- ConfigMaps and Secrets;
- logs, exec, metrics and cluster-scoped resources;
- any write;
- any real or shared cluster;
- AI.

## 3. <a id="client"></a>Client options: dependency, licensing and security

| | **Stdlib HTTPS client (D1)** | Allowlisted `kubectl` subprocess | Python `kubernetes` client |
|---|---|---|---|
| New runtime dependencies | None | `kubectl` binary (Apache-2.0, about 50 MB, pinned by SHA-256) | `kubernetes` (Apache-2.0) and about 12 transitive wheels: `urllib3`, `requests`, `requests-oauthlib`/`oauthlib`, `google-auth`, `websocket-client`, `PyYAML`, `python-dateutil`, `six`, `durationpy`, and `certifi` (**MPL-2.0**, a file-level notice obligation) |
| Supply chain | Python stdlib only | One large Go binary; ±1 minor version skew | Largest tree in the repository, with an HTTP stack that has a history of advisories |
| Credentials | A token file and a CA file only | A kubeconfig can run **`exec`/auth-provider** commands | `load_kube_config` runs `exec` plugins too |
| Disk side effects | None | Discovery cache in `~/.kube/cache` | Optional caches and logging |
| Pagination and error control | Full: opaque tokens, `410`, size caps, timeouts, exact status mapping | `get --raw`, but errors come back as exit codes and stderr text | Good, through exceptions |
| Tests without a cluster | A loopback fake TLS API server on any OS | Needs the binary or a fake | Mock layers |

**D1 details.** The collector issues only these requests, as fixed templates where the namespace comes from configuration:
- `GET /api/v1/namespaces/{ns}/pods`
- `GET /apis/apps/v1/namespaces/{ns}/deployments`
- `GET /apis/apps/v1/namespaces/{ns}/replicasets`
- `GET /api/v1/namespaces/{ns}/events`

**Query parameters:** only `limit=<int>` and `continue=<token>` ([§6.2](#pagination)).

**What the client refuses, and what it never reads or writes:**
- any other path, method or parameter, and any redirect;
- proxies, environment variables, kubeconfig files and plugins;
- anything on disk except its two input files.

**Transport:** TLS is verified against the cluster CA file, with hostname checking. The bearer token comes from a file, and every request has a timeout.

`kubectl` stays a **CI test-harness tool only**.

## 4. RBAC (namespace-restricted, least privilege)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata: {name: ca-collector, namespace: ca-collector}
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: ca-collector-read, namespace: ca-demo}
rules:
- apiGroups: [""]
  resources: [pods, events]
  verbs: [get, list]
- apiGroups: [apps]
  resources: [deployments, replicasets]
  verbs: [get, list]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: ca-collector-read, namespace: ca-demo}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: ca-collector-read}
subjects: [{kind: ServiceAccount, name: ca-collector, namespace: ca-collector}]
```

**Deliberately left out of the Role:**
- `watch`;
- `configmaps` and `secrets`;
- every subresource (`pods/exec`, `pods/log`, `pods/attach`, `pods/portforward`, `*/proxy`, `*/status`);
- every write verb;
- every cluster-scoped resource;
- any ClusterRole or ClusterRoleBinding.

**Token:** a short-lived TokenRequest token (10 minutes), written to a `0600` file in a `0700` temporary directory outside Git and deleted at teardown.

## 5. Sanitization: no raw objects are persisted

Each page is parsed in memory with the strict JSON parser, under size and depth limits. Every item is **projected to an allowlist** immediately; nothing else is kept or written:

| Resource | Kept | Dropped (never written) |
|---|---|---|
| Pod | name, namespace, uid, resourceVersion, creationTimestamp, controller ownerReference (kind, name, uid), `spec.nodeName`, ConfigMap volume names with mount paths and `subPath` as a boolean, restart counts | annotations, labels, env and envFrom values, `secretKeyRef`/Secret volumes (counted only), command and args, status messages, managedFields |
| ReplicaSet and Deployment | the above metadata, the `deployment.kubernetes.io/revision` annotation only, the single container's name and image, ConfigMap reference names, Progressing condition type, reason and lastUpdateTime | every other annotation (including `last-applied-configuration`), env values, Secret references, managedFields, messages |
| Event | name, namespace, uid, resourceVersion, involved kind and name, type, reason, count, first and last timestamps, reporting component | `message`, `note`, related objects, series details. Events involving a `Secret` are withheld and counted (D6) |

## 6. <a id="timing"></a>Timing, consistency and coverage (D2, rev. 2)

### 6.1 What a paginated list does and does not establish

| Fact | Established? | How it is recorded |
|---|---|---|
| The pages form **one consistent collection** | Yes, when every page reports the **same collection-level `metadata.resourceVersion`** and the chain of continue tokens finished without `410` | `consistency: "consistent"` and `collection_resource_version` (opaque) in the recording. The RV goes into the batch cursor when it fits the cursor alphabet ([§6.4](#mapping)) |
| **Which** API-server state that collection reflects | Only as an **opaque** resourceVersion. RVs are compared for **equality only**, never ordered or turned into time | The same `collection_resource_version` |
| When the client sent the first request and received the last response | Yes, on the **client clock** (UTC wall time, plus a monotonic duration) | `client_first_request_at` and `client_last_response_at`, with `client_elapsed_ms` |
| When the API server took the snapshot | **No.** The API-server-to-client offset is unknown (D4), and the snapshot is taken somewhere around the first request, not at the last response | No `snapshot_at`. Nothing places the collection at an instant |
| That two resource kinds (Deployments and ReplicaSets) show the same moment | **No.** They are separate collections with separate RVs | Both RVs and both client brackets, recorded separately |
| Verified historical or continuous coverage of any interval | **No.** Unsupported in 004e | No `complete` or `empty` batch is ever produced by the collector |

### 6.2 <a id="pagination"></a>Pagination safeguards

- **The collection-level RV must match on every page.** A different `metadata.resourceVersion` on any page means the collection is not consistent: **all pages are discarded**, and the outcome is `failed` / `invalid_response` (code `collection_rv_changed`). Item `resourceVersion`s are never used for this check. They are evidence identity (`source_version`) only.
- **Continue tokens are opaque.**
  - **Use:** a token is sent back only on the next request of the **same** collection attempt, URL-encoded as a single query value (`urllib.parse.quote(token, safe="")`).
  - **Bounds:** it must be a string of at most 8 KiB with no control characters. Anything else is `invalid_response`.
  - **Never kept:** tokens are never logged, never written to the recording or report (only page counts), and never parsed.
- **After HTTP `410 Gone`:**
  - the current attempt's token, and any token in the `410` body, are **never reused**;
  - the attempt's pages are **discarded**, because they would not form a consistent collection with any later page;
  - the list restarts from the beginning, with no `continue` parameter, at most `max_restarts` times (default 1);
  - if every attempt ends in `410`, the outcome is `failed` / `source_unavailable` with code `list_expired`.

  No mixed-attempt collection is ever built.
- **Bounds:** if `max_pages` is reached while a continue token remains, the pages so far are one consistent prefix. The outcome is `partial` / `page_limit`, truncated, with `omitted_count` from `remainingItemCount` when present (otherwise unknown).
- **Duplicate detection:** a uid appearing twice in one collection is `invalid_response`.

### 6.3 <a id="format"></a>Smallest fail-closed representation: recording `0.3`

**What stays unchanged:** recording formats `0.1` and `0.2`, the batch, frozen-input and evidence contracts, the migrations, stored bytes and every pinned digest.
- Recording `0.2` keeps its **fixture-declared** `snapshot_at` for hand-written synthetic examples, in the same way fixture-declared clock offsets work.
- The collector never writes `0.2`.

**The new adapter-level format, `ca-k8s-recording/0.3-provisional` (collector provenance):**
- `"provenance": "collector"`;
- the declared API-server clock: `status: "unknown"`;
- for each resource:
  - `resource`, `file` and `sha256` (the sanitized projection, as for `0.2`);
  - `http_status`, an `error` code, and an `outcome` code: `consistent`, `truncated`, `rv_changed`, `expired`, `denied`, `rate_limited`, `timeout`, `unavailable` or `invalid`;
  - `collection_resource_version` (an opaque string, or null) and `pages`;
  - `restarts`;
  - `client_first_request_at` and `client_last_response_at` (RFC 3339 with milliseconds, client clock) and `client_elapsed_ms`;
  - `remaining_item_count`.
- **There is no `snapshot_at` and no `coverage` field.** A `0.3` recording that contains either is refused.

### 6.4 <a id="mapping"></a>Mapping to the existing batch contract (fail-closed)

| Recorded collection | Batch | Coverage field | Counted as covered? |
|---|---|---|---|
| `consistent` (any number of items, **including zero**) | `partial`, `continuity_lost`, observations kept | The client bracket `[floor_ms(first request), ceil_ms(last response) + 1 ms)`, declared and **unverified** | **No.** Partial coverage is never counted, so the whole window remains a `coverage_gap` |
| `truncated` (page bound) | `partial`, `page_limit`, truncated | The client bracket, unverified | No |
| `rv_changed` | `failed`, `invalid_response` | None | No |
| `expired` (410 after restarts) | `failed`, `source_unavailable` | None | No |
| `denied` (401/403) | `denied`, `authorization_denied` | None | No |
| `rate_limited` (429) | `failed`, `rate_limited` | None | No |
| `timeout` | `failed`, `timeout` | None | No |
| `unavailable` (TLS, connection or 5xx) | `failed`, `source_unavailable` | None | No |
| `invalid` (strict JSON, kind, item or size) | `failed`, `invalid_response` | None | No |
| Deployments and ReplicaSets, both `consistent` | `partial`, `continuity_lost` (two collections are never joined into one view) | The union of the two client brackets, unverified | No |

**Notes on the mapping:**
- **The collector never emits `complete` or `empty`.** An empty consistent list is `partial` with zero observations: "the list returned nothing at an unplaced moment" is not evidence that nothing happened.
- **The collection RV is recorded in the batch** as `cursor.after = "rv:<collection_resource_version>"` when it matches the batch cursor alphabet and length (otherwise `cursor.after` is a synthetic page-chain marker, and the RV stays in the recording and report). The frozen input then records which collection the evidence came from.
- **The plan window** is the configured look-back ending at `ceil_ms(last response) + 1 ms`, at most 1 hour. Its timestamps are client-clock values that the plan treats as reference time only for bookkeeping. No coverage inside it is ever counted, and the clock is declared `unknown`, so no ordering or coverage conclusion can rest on it.
- **Consequence:** collector investigations **always abstain** in 004e. That is the honest result until a reviewed contract can express verified collection timing or continuous coverage.

### 6.5 Follow-up (not in 004e)
These need a separate, versioned batch-contract decision, with no silent change to existing records:
- a batch outcome or `coverage_basis` that can say "consistent snapshot at an opaque RV, unplaced in time";
- a measured client-to-server offset provenance for clocks;
- watch-based continuous coverage, keyed to RV continuity (004f).

## 7. Errors, reports and leakage

- **Response bodies are never logged or echoed.** That includes Kubernetes `Status` messages, which can quote request data.
- **Errors:** exceptions raised by the client carry a fixed code and the HTTP status only. Tracebacks are caught at the collector boundary and reduced to `class name + code`.
- **The collection report** is canonical JSON with outcome codes, HTTP statuses, counts, page counts, restarts, opaque RVs, client timestamps, and withheld and out-of-scope counts. It never contains bodies, messages, tokens, continue tokens, headers or item fields beyond the projection.
- **Evidence identity** is unchanged: `source_version` is the item resourceVersion, and identity comes from configuration (`source_id`, `cluster_id`, `namespace`). Objects outside the namespace refuse the collection (004c behaviour). Honest abstention is preserved ([§6.4](#mapping)).

## 8. Tests (acceptance changes in rev. 2 are marked **new** or **changed**)

**Offline**, on every OS, including Windows and the existing offline CI job. A **loopback TLS fake API server** (stdlib, a per-run test certificate) serves scripted collections.

**Changed, from rev. 1:**
- Every successful collection becomes `partial` / `continuity_lost` with `coverage_claimed: false`.
- The frozen input shows `verified_ms == 0` for every acquisition and status `incomplete`.
- The investigation abstains.
- No collector batch is ever `complete` or `empty`. An empty list is `partial` with zero observations.
- No collector recording contains `snapshot_at` or `coverage`; a `0.3` recording with either is refused.

**New:**
- **RV consistency:** when page 2 returns a different collection-level `metadata.resourceVersion`, every page is discarded and the result is `failed` / `invalid_response` (`collection_rv_changed`). When item resourceVersions differ across pages, the collection is still consistent.
- **Opaque tokens:**
  - tokens with `+ / = & % ?` and spaces round-trip exactly, URL-encoded as a single value;
  - control characters and oversize tokens are refused;
  - no token appears in any written file or log line;
  - the fake server asserts that every token it receives is one it issued in the same attempt.
- **410 handling:**
  - the token from the failed attempt, and the one in the `410` body, are never sent again;
  - the restart request carries no `continue` parameter;
  - pages from the failed attempt are absent from the output;
  - after `max_restarts`, the result is `failed` / `source_unavailable` (`list_expired`).
- **Separate collections:** different RVs for Deployments and ReplicaSets give `partial` / `continuity_lost`, with both RVs in the report.
- **Client timestamps:** `client_first_request_at ≤ client_last_response_at`, the elapsed time comes from the monotonic clock, and the API-server clock is declared `unknown`.
- **Leakage:**
  - the fake server returns 403, 410, 429 and 500 with `Status.message` bodies containing planted secrets;
  - no planted value appears in exceptions, captured logs, the report, the recording, the bundle or the result.
- **Replay:** converting the `0.3` recording again gives a byte-identical bundle and result.

**Unchanged from rev. 1:**
- sanitization (the planted-value scan);
- the allowlist refusing other paths, methods and parameters;
- no redirects;
- TLS required;
- page bounds;
- 401, 403, 429, 5xx and timeout mapping;
- strict JSON, kinds and duplicates;
- other-namespace refusal;
- withheld Secret events.

**`kind` CI job (`collector-kind`)**, on hosted `ubuntu-24.04`. It is triggered manually (`workflow_dispatch`) and on pull requests that touch collector paths:
1. Download `kind` and `kubectl` at pinned versions and **verify their SHA-256**. Pull `kindest/node` by digest. All three are inventoried as CI-only tools.
2. Create a single-node cluster. The API server listens on `127.0.0.1` only.
3. Apply synthetic workloads:
   - `ca-demo` with a rollout, a crash-looping Pod, and a ConfigMap and Secret holding planted placeholder values;
   - a second namespace, `ca-other`, with similar objects.
4. Apply the RBAC (§4) and mint a 10-minute token.
5. **Negative RBAC, through two layers:**
   - **`kubectl auth can-i` is "no" for:**
     - `get`/`list` on secrets and configmaps;
     - `create pods/exec` and `get pods/log`;
     - writes to pods, deployments and replicasets;
     - `watch` on pods;
     - `list pods -n ca-other` and `list nodes`;
     - `get namespaces` and `create tokenrequests`.
   - The same matrix is sent to the API server with the collector token through a test-only raw function (bypassing the allowlist). Every request must get **403**.
   - Plus: the allowlisted client refuses to even form those requests.
6. **Collect** to produce the `0.3` recording, the bundle and the report. **Changed:**
   - every successful collection is `partial` / `continuity_lost`, with opaque collection RVs and client brackets recorded;
   - **new:** the collection RV is the same on every page of each collection;
   - the planted-value scan covers everything written;
   - the run is created offline and on the job's disposable PostgreSQL, byte-identical, and **abstains**.
7. **Faults:**
   - a revoked RoleBinding or an expired token: `denied`;
   - a closed port: `source_unavailable`;
   - a page limit of 1 with a page bound of 1: `partial` / `page_limit`.
   - A real `410` cannot be forced reliably on `kind`, so it is covered by the fake server.
8. Always delete the `kind` cluster and the token directory at the end.

## 9. Delivery steps (after authorization)

1. **Collector package:** `src/cloud_autopsy/collector/` with `config.py`, `client.py` (the allowlisted HTTPS client), `project.py` (the sanitizing projection, shared with the adapter) and `collect.py` (collections, the report and the `0.3` recording), plus `tools/collect_k8s.py`.
2. **Adapter:** `k8s_recording` accepts `ca-k8s-recording/0.3-provisional` with the [§6.4](#mapping) mapping. Recording formats `0.1` and `0.2`, and their pinned outputs, are unchanged.
3. **Offline tests:** the fake TLS API server (§8).
4. **`deploy/kind/`:** the cluster config, synthetic workloads and RBAC manifests.
5. **Workflow:** the `collector-kind` job, with supply-chain inventory entries for `kind`, `kubectl` and `kindest/node`. This is the only step with network downloads.
6. **Records:** `ca-p2-004e.md` and a draft PR with CI evidence.

## 10. Remaining risks

- **Hosted runners:** occasional `kind` start failures. One retry is allowed, and failures are reported, not hidden.
- **Collector runs always abstain** in 004e. That is intended, until a contract can express collection timing (§6.5).
- **RBAC cannot stop the API server returning Pod env values** to a permitted `list`. Protection relies on in-memory projection, tested by planted values.
- **Self-built TLS client:** security-sensitive. Independent security review is needed before any non-disposable cluster.

## 11. <a id="scope"></a>Final execution scope for authorization

Authorizing this plan permits exactly:
- **Code:** the collector package, the recording-`0.3` support in the adapter, offline tests with a fake TLS API server, and the `deploy/kind/` manifests, all on a new branch stacked on PR #31/#32.
- **One new CI job, `collector-kind`,** on GitHub-hosted runners only. It:
  - downloads pinned, checksum-verified `kind` and `kubectl` and a digest-pinned `kindest/node` (CI-only, inventoried);
  - creates and deletes a disposable single-node cluster per run;
  - uses synthetic workloads only.
- **Credentials:** a 10-minute ServiceAccount token inside that job only.

**Not permitted:**
- any change to existing contracts, migrations, stored bytes, recording `0.1`/`0.2` semantics or pinned digests;
- any cluster outside that CI job, and any access to an existing cluster;
- installing anything on your machine;
- runtime dependencies;
- ConfigMap or Secret access;
- watch;
- API write routes;
- dashboard changes;
- merging or deployment.

**Delivered as:** a draft PR with both existing CI jobs green, plus the `collector-kind` job's results, reported faithfully, including failures.
