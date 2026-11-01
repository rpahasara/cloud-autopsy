# Kubernetes and telemetry collection architecture (Proposed)

Owner: Architecture lead; security design reviewer: Security reviewer. Decisions: CA-DEC-001/003/004/007. Issues #3/#4/#9/#10. Trace: CA-FR-001/002/003/005/013/014; CA-NFR-003/004/009; CA-SEC-001/002/005/008/009/010. See [diagrams](diagrams.md) F3–F5 and [security tests](security.md).

## Collection topology and source plan

One collector identity reads one isolated namespace. Investigator input selects a reviewed scenario/query ID, not a cluster address, resource expression, PromQL/LogQL string or arbitrary URL. Endpoint registry binds cluster identity, CA trust, namespace, source kind and allowed query templates. Verify TLS and hostname; reject redirects and host changes. Metrics/log identities are separate read-only source credentials. Deployment metadata comes from pinned sanitized fixture content, not arbitrary repository URLs.

| Source | Allowed evidence | Query and coverage behavior |
|---|---|---|
| Kubernetes core v1 | Events, Pods, explicitly named synthetic ConfigMaps | Namespace path only; bounded list/watch for events/pods; ConfigMaps fetched by approved name and sampled at declared fixture checkpoints |
| Kubernetes apps/v1 | Deployments and ReplicaSets | Namespace list/watch; preserve UID, owner references, resourceVersion and relevant declared fields |
| Prometheus | Fixed query registry for error rate, volume and declared pool signals | Bounded range, step and sample counts; distinguish absent series, empty interval and failed query |
| Loki | Fixed workload/namespace selectors and declared log templates | Bounded range, line/byte count and pagination; truncation produces gap; no direct pods/log permission |
| Fixture/deployment metadata | Sanitized, versioned change references and configuration-consumption records | Verify digest before ingest; never treat author-supplied actor text as authenticated audit identity |

Collection minimizes fields before durable storage, but the collector necessarily receives API responses before filtering. Kubernetes RBAC cannot filter object fields; Pod/Deployment specs may contain inline sensitive values and ConfigMaps may contain sensitive text. Synthetic-only scope and source authorization are prerequisites, not a redaction guarantee. Skip unneeded environment/annotation fields and raw headers. Retain only declared sanitized representation and its integrity digest; record that original-source bytes were not retained.

## Proposed RBAC permission specification

The following is a review example, not an applied manifest or implementation artifact. An authorized environment maintainer would provision the ServiceAccount and namespace-scoped RoleBinding separately. RoleBindings reference only this Role and the collector account; no ClusterRoleBinding or default broad reader role is allowed.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cloud-autopsy-evidence-reader
  namespace: ca-synthetic
rules:
  - apiGroups: [""]
    resources: ["events", "pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["ca-scenario-001-config"]
    verbs: ["get"]
```

Explicitly absent: Secrets, namespaces/nodes, serviceaccounts/token, pods/log, pods/exec, pods/attach, pods/portforward, proxy subresources, RBAC objects, impersonation, bind, escalate, create, update, patch and delete. No wildcard resources, API groups, verbs or non-resource URLs. Base permissions do not include events.k8s.io; using that API group requires an explicitly reviewed compatibility amendment, not permission fallback.

ConfigMap name restriction is real object-level authorization for `get`. Do not add broad `list/watch` to emulate field filtering. A future named ConfigMap watch needs a matching name selector and version-specific authorization tests; the current proposal uses explicit checkpoint reads. [Kubernetes RBAC documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/) documents the resourceName selector limitation. Current snapshots do not recover past ConfigMap values; the synthetic fixture plan must capture before/after values and consumption evidence. Without those checkpoints, record a gap and abstain on that mechanism.

## List/watch continuity and clock evidence

For each supported resource stream: initial bounded list, capture collection resourceVersion, then watch from that opaque value. Persist cursor only with the corresponding durable ingest batch. Preserve source timestamps and observation/ingestion timestamps separately; resourceVersion is a concurrency cursor, never a numeric clock or cross-resource ordering key. Retry transient failures with bounded backoff and jitter; denied access fails closed, never escalates permissions. Coalesce duplicate delivery by source-qualified identity and version/digest.

On watch-history expiration (`410 Gone`), invalidate the stream cache, relist and restart the watch, while recording the unobserved interval as a continuity gap. A new snapshot cannot prove what changed during the gap. Bookmarks may advance observed continuity but are not guaranteed heartbeats. These handling requirements follow [Kubernetes API list/watch semantics](https://kubernetes.io/docs/reference/using-api/api-concepts/). Events are observations with finite source retention, not a complete audit log. Claims about authenticated actors require a separately approved audit source; ordinary Events do not establish actor identity.

Retry exhaustion, response too large, missing pagination, rate limiting and query timeout each produce typed partial/failure state and expected-source gaps. Explicit clean-empty responses preserve query scope and coverage. Compare expected sources against observed coverage before sealing; no silent partial success. The proposed run limits in CA-DEC-007 remain provisional and must be configured and tested before implementation evaluation; no unlimited fallback.

## Credential and network controls

Propose short-lived projected ServiceAccount credentials mounted only in the collector, with TLS validation and rotation/reconnect tests. Non-collector pods disable automatic ServiceAccount token mounting. No host networking, host mounts, privileged containers, shared write-capable kubeconfig, cloud metadata access or shell/exec tool endpoint. Runtime fixture acquisition has no write rights; fixture setup is a separately controlled human/evaluator operation outside the collector.

Collector egress permits only the declared API server and metrics/log endpoints plus explicitly necessary DNS. Model sandbox has no cluster route; the core API/engine cannot reach arbitrary internet destinations. A kind network configuration must actually enforce the chosen controls. Kubernetes NetworkPolicy depends on supporting networking enforcement and cannot alone express a domain/TLS provider policy; validate the effective route and use an approved egress proxy for any future external provider. See [Kubernetes NetworkPolicy scope](https://kubernetes.io/docs/concepts/services-networking/network-policies/).

CA-TEST-SEC-001 must prove positive allowed reads and negative mutations, secret/subresource reads, cross-namespace and RBAC escalation attempts with the actual collector credential. Separate CA-TEST-SEC-006 verifies blocked model internet access; CA-TEST-SEC-009 covers all input/retry bounds; CA-TEST-FR-005 covers continuity gaps. No RBAC or network test has been run.
