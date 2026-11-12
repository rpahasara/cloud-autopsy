# CA-P2-004e — first isolated, read-only Kubernetes collector (implementation plan, not approved)

**Status:** plan only. Nothing here may be done until the product owner approves this plan:
- no cluster is created and no access to any existing cluster is granted;
- no dependency is installed and no workflow is enabled;
- nothing is deployed.

When approved, the work is synthetic-only, under the [pre-gate development authorization](../ca-p2-003/ca-p2-003b-1.md). Stacked on [004d](ca-p2-004d.md) (PR #31).

**Goal:** collect the approved Kubernetes resources from a **disposable local `kind` cluster** running synthetic workloads. The collector is read-only, least-privilege and namespace-restricted. Its output is sanitized evidence in the existing versioned contracts and the existing bundle workflow. It records honest gaps and never claims coverage it did not verify.

## 1. Decisions to approve

| # | Decision | Recommendation |
|---|---|---|
| D1 | API client | **A stdlib-only HTTPS client** (`http.client` + `ssl`) with a fixed allowlist of GET paths. No new runtime dependency. Compared in [§3](#client) |
| D2 | Coverage in this slice | **Point-in-time list snapshots only**, with `snapshot_instant` coverage as in 004d. Continuous watch coverage is **004f**, because claiming it needs a reviewed batch-contract change (§6) |
| D3 | ConfigMaps | **Not collected in 004e and not in the RBAC Role.** RBAC cannot grant metadata-only access: any `list configmaps` permission can also read values. The metadata-only API (PartialObjectMetadata) returns no key names, so it cannot fill `configmap_metadata` honestly. Options for a later decision: a kinds `0.3` with "key names unknown", or leaving ConfigMaps out |
| D4 | Clock | The API-server clock is declared **`unknown`**. Only `fixture_declared` offsets exist, and a collector measurement is not a fixture declaration. Ordering degrades honestly. A measured-offset provenance is a separate contract follow-up |
| D5 | Test environment | **A separate GitHub Actions job** on a hosted Ubuntu runner that creates and destroys a `kind` cluster per run. It is manually triggered (`workflow_dispatch`), plus a path-filtered `pull_request` trigger. Nothing runs on the Windows machine except offline tests |
| D6 | Events about Secrets | **Withheld and counted.** Even a Secret's *name* never becomes evidence (closes the PR #31 review P2) |

## 2. Scope

**In scope:**
- **Resources:** Pods, Deployments, ReplicaSets and Events (core `v1`) in **one** namespace (`ca-demo`), using list with pagination.
- **Output:**
  - a **sanitized** recording (`ca-k8s-recording/0.2-provisional`) that holds projected objects only;
  - the bundle (kinds 0.2), created through `k8s_recording.convert`;
  - a collection report with codes and counts only.

**Out of scope:**
- watch and continuous coverage (004f);
- ConfigMaps (D3), Secrets, logs, exec, metrics and cluster-scoped resources;
- any write;
- any real or shared cluster;
- AI.

## 3. <a id="client"></a>Client options: dependency, licensing and security

| | **Stdlib HTTPS client (recommended)** | Allowlisted `kubectl` subprocess | Python `kubernetes` client |
|---|---|---|---|
| New runtime dependencies | None | `kubectl` binary (Apache-2.0, about 50 MB, pinned by SHA-256 from `dl.k8s.io`) | `kubernetes` (Apache-2.0) and a transitive tree: `urllib3` (MIT), `requests` (Apache-2.0), `requests-oauthlib`/`oauthlib` (ISC/BSD), `google-auth` (Apache-2.0), `websocket-client` (Apache-2.0), `PyYAML` (MIT), `python-dateutil` (Apache-2.0/BSD), `six` (MIT), `certifi` (**MPL-2.0**, a file-level notice obligation), `durationpy` (MIT). About 12 wheels to hash-lock and review |
| Supply-chain and CVE exposure | Python stdlib only | One large Go binary. Version-skew policy ±1 minor | High: an HTTP stack with a history of advisories (urllib3, requests) |
| Credential handling | Token file and CA file only; we parse nothing else | A kubeconfig can name **`exec`/auth-provider plugins** that run arbitrary commands. We would generate it ourselves and refuse any `exec` | `load_kube_config` also runs `exec` plugins. We would use explicit `Configuration` objects only |
| Side effects | None | Discovery cache written to `~/.kube/cache` (raw API data on disk); environment and plugin lookup | Optional caches and logging; large defaults surface |
| Pagination and errors | Full control: `limit`, `continue`, `410 Gone`, size caps, timeouts, exact status mapping | `get --raw` keeps control but errors arrive as exit codes and stderr text | Good control; exceptions wrap HTTP status |
| Testing without a cluster | A loopback fake API server (TLS, canned pages and faults) on any OS | Needs the binary, or a fake on `PATH` | Mock layers |
| Fit with the project | Matches the stdlib-only core (pg8000 is the only runtime dependency) | Adds a binary distribution concern | Adds the largest dependency tree in the repository |

**Recommendation: D1.** The collector issues only these GET requests, as fixed templates where the namespace comes from configuration:
- `GET /api/v1/namespaces/{ns}/pods?limit=N[&continue=T]`
- `GET /apis/apps/v1/namespaces/{ns}/deployments?limit=N[&continue=T]`
- `GET /apis/apps/v1/namespaces/{ns}/replicasets?limit=N[&continue=T]`
- `GET /api/v1/namespaces/{ns}/events?limit=N[&continue=T]`

**What the client refuses, and what it never reads or writes:**
- any other path, method, or query parameter, and any redirect;
- proxies, environment variables, kubeconfig files and plugins;
- anything on disk except its two input files.

**Transport:** TLS is verified against the cluster CA file (no `insecure`), with hostname checking. The token comes from a file and is never logged. Timeouts are per request, response bodies are capped at 1 MiB per page, and the number of pages is bounded.

`kubectl` stays a **CI test-harness tool only**: cluster setup and `auth can-i` checks, never the collector.

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
- `watch` (that is 004f);
- `configmaps` (D3);
- `secrets`;
- subresources: `pods/exec`, `pods/log`, `pods/attach`, `pods/portforward`, `*/proxy`, `*/status`;
- every write verb;
- every cluster-scoped resource;
- any ClusterRole or ClusterRoleBinding.

**Token:** a short-lived TokenRequest token (`kubectl create token ca-collector -n ca-collector --duration=10m`), written to a `0600` file in a `0700` temporary directory outside Git and deleted at teardown. The ServiceAccount itself has no auto-mounted token.

## 5. Sanitization: no raw objects are persisted

Each page is parsed in memory with the strict JSON parser, under size and depth limits. Every item is immediately **projected to an allowlist**; nothing else is kept or written:

| Resource | Kept | Dropped (never written) |
|---|---|---|
| Pod | name, namespace, uid, resourceVersion, creationTimestamp, controller ownerReference (kind, name, uid), `spec.nodeName`, ConfigMap volume names with mount paths and `subPath` as a boolean, container restart counts | annotations, labels, env and envFrom values, `secretKeyRef`/Secret volumes (counted only), images, command and args, status messages, managedFields |
| ReplicaSet and Deployment | the above metadata, the `deployment.kubernetes.io/revision` annotation only, the single container's name and image, ConfigMap reference names, Progressing condition type, reason and lastUpdateTime | every other annotation (including `last-applied-configuration`), env values, Secret references, managedFields, condition messages |
| Event | name, namespace, uid, resourceVersion, involved kind and name, type, reason, count, first and last timestamps, reporting component | `message`, `note`, related objects, series details. **Events whose involved kind is `Secret` are withheld and counted** (D6) |

**What is written to disk:**
- **The sanitized recording:** the projected objects plus a manifest with `snapshot_at` per response. It is the input for **deterministic replay**: converting it again gives a byte-identical bundle (tested).
- **The bundle.**
- **The collection report:** codes and counts.

A test scans every written byte for the planted synthetic sensitive values: env values, a Secret's data and name, event messages, and `last-applied-configuration` content.

## 6. Coverage, gaps and failure mapping

| Situation | Batch outcome | Coverage |
|---|---|---|
| A complete list (all pages, one resourceVersion) | `complete` / `empty` | `[snapshot_at, +1 ms)` (snapshot). `snapshot_at` = the time the last page was received, on the collector's clock (D4) |
| More pages than the bound | `partial`, `page_limit`, truncated, `omitted_count` from `remainingItemCount` | Not verified |
| `410 Gone` (the continue token expired mid-list) | `partial`, `continuity_lost` | Not verified |
| 401 / 403 | `denied`, `authorization_denied` | None |
| 429 (bounded retries with backoff, then give up) | `failed`, `rate_limited` | None |
| Timeout | `failed`, `timeout` | None |
| TLS, connection or 5xx failure | `failed`, `source_unavailable` | None |
| A body that is not strict JSON, has the wrong kind, or contains an item that cannot be converted | `failed`, `invalid_response` | None |
| Deployments and ReplicaSets listed at different instants | `partial`, `continuity_lost` (as in 004d) | Not verified |

**Continuous coverage (004f):** a watch from a list's resourceVersion, with bookmarks, shows that every change between two resourceVersions was seen. Mapping that to wall-clock coverage, and to `410` or expiry gaps, needs a reviewed batch-contract extension. Until then, 004e claims none.

## 7. Identity, time and determinism

- **Fixed identity:** the source identity comes from configuration (`source_id`, `cluster_id`, `namespace`), never from the cluster. The API server URL and CA are fixed per run.
- **Namespace isolation:** an object outside the namespace refuses the whole collection, reusing 004c.
- **Raw time:** timestamps are kept raw with their precision. The clock domain is declared `unknown` (D4).
- **Replay:** the bundle and its investigation are deterministic given the sanitized recording, and the database path is byte-identical to offline (reusing the 004a/004d tests).

## 8. Tests

**Offline, on every OS, including your Windows machine and the existing offline CI job:**
- A **loopback TLS fake API server** (stdlib, a test-only certificate generated per run) serves canned pages and faults: pagination, `continue`, `410`, 401, 403, 429, 5xx, timeouts, oversize pages, malformed JSON, wrong kinds, other-namespace objects, Secret-involving events, and planted sensitive fields.
- **Assertions:**
  - the outcome mapping (§6);
  - sanitization: no planted value or field appears anywhere written;
  - the allowlist: any other path, method or parameter is refused before sending;
  - no redirects are followed;
  - TLS verification is required;
  - replay determinism.

**`kind` CI job (`collector-kind`)**, on hosted `ubuntu-24.04`. It is triggered manually (`workflow_dispatch`) and on pull requests that touch collector paths. Steps:
1. Download `kind` and `kubectl` at pinned versions and **verify their SHA-256**. Pull `kindest/node` **by digest**. All of these are inventoried in `supply-chain/dependency-inventory.json` as CI-only tools.
2. Create a single-node cluster. The API server listens on `127.0.0.1` only, with no extra port mappings.
3. Apply synthetic manifests:
   - `ca-demo` with `checkout-api` and a ConfigMap and Secret holding synthetic placeholder values;
   - a rollout (an image change) and a crash-looping Pod, to produce Events;
   - a second namespace, `ca-other`, with similar objects.
4. Apply the ServiceAccount, Role and RoleBinding (§4) and mint a 10-minute token.
5. **Negative RBAC tests:**
   - **`kubectl auth can-i` as the ServiceAccount is "no" for:**
     - `get`/`list` on secrets and configmaps;
     - `create pods/exec` and `get pods/log`;
     - `create`, `update`, `patch` and `delete` on pods, deployments and replicasets;
     - `watch` on pods;
     - `list pods -n ca-other` and `list nodes`;
     - `get namespaces` and `create tokenrequests`.
   - The same matrix is then **sent to the API server** using the collector's token through a test-only raw request function (bypassing the allowlist). Every request must get **403**.
   - Plus: the allowlisted client refuses to even form those requests.
6. Run the collector to produce the sanitized recording, the bundle and the report. Check:
   - the expected outcomes, and the sensitive-value scan of everything written;
   - `create_investigation --offline`, and on the job's disposable PostgreSQL, database-verified creation that is byte-identical to offline.
7. **Fault injection:**
   - revoke the RoleBinding and collect again: everything `denied`;
   - collect with an expired token: `denied`;
   - point at a closed port: `source_unavailable`;
   - set a page limit of 1 with a page bound of 1: `partial`/`page_limit`.
8. Always run `kind delete cluster` at the end, and remove the token directory.

## 9. Delivery steps (after approval)

1. **Collector package:** `src/cloud_autopsy/collector/` with `config.py`, `client.py` (the allowlisted HTTPS client), `project.py` (sanitizing projection, shared with the adapter) and `collect.py` (orchestration and the report), plus `tools/collect_k8s.py`. Offline tests with the fake TLS server.
2. **Manifests:** `deploy/kind/` with the cluster config, synthetic workloads and RBAC.
3. **Workflow and inventory:** the `collector-kind` CI job and supply-chain inventory entries for `kind`, `kubectl` and `kindest/node`. This is the only step with network downloads.
4. **Records:** the implementation record `ca-p2-004e.md`, and a draft PR with CI evidence.

## 10. Remaining risks

- **Hosted-runner limits:** `kind` on hosted runners occasionally hits resource limits or fails to start. One retry is allowed, and failures are reported, not hidden.
- **No continuous coverage until 004f:** a snapshot covers 1 ms, so investigations will usually abstain, which is honest.
- **RBAC cannot stop the API server returning Pod env values** to a permitted `list`. Protection relies on in-memory projection, tested by the planted-value scan, not on RBAC.
- **Self-built TLS client:** this is security-sensitive code. Independent security review is needed before any non-disposable cluster.
