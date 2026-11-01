# CA-SCENARIO-001 spike fixture specification (`0.1.0-spike`)

Synthetic, offline fixture for [CA-SPIKE-001](../../../docs/spikes/CA-SPIKE-001.md). All names, UIDs, images and values are invented; `registry.invalid` is a reserved non-resolvable domain. No Secret, credential or real telemetry is present. Ground truth is **not** in this directory; it lives in `prototype/truth/` and only the scorer reads it.

## Workload and hot-reload mechanism

- Namespace `ca-demo`; Deployment `checkout-api` (2 replicas, RollingUpdate maxSurge 1 / maxUnavailable 0) under a constant declared load of about 120 requests/s.
- ConfigMap `checkout-db-pool` holds key `pool.maxConnections`. Every pod mounts it as a **directory volume** at `/etc/checkout/pool` **without `subPath`**. Kubelet therefore refreshes the projected file in place after a ConfigMap update (sync period plus cache delay, tens of seconds); a `subPath` mount would never be refreshed and is treated by the engine as not hot-reload eligible.
- The application polls `/etc/checkout/pool/pool.maxConnections` every 5 s. On a content change it rebuilds its DB connection pool **without restarting** (restart count stays 0) and logs template `CONFIG_RELOADED` with the parsed value and the SHA-256 of the file content. On start-up it logs `CONFIG_LOADED` in the same form.
- When the pool is saturated a request waits 5 s, fails and the app logs `POOL_EXHAUSTED`. At ~120 requests/s, 4 connections are insufficient; 50 are sufficient.

A consumption link is established by **content**, not by time: the ConfigMap change's `after_value_sha256` equals the `value_sha256` logged by the pod, the pod mounts that ConfigMap without `subPath`, and the log is not strictly earlier than the change.

## Causal change, correlated non-cause and ordering (reference clock, UTC, 2026-10-15)

| Time | Source / clock domain | Event |
|---|---|---|
| 07:00:03 | node-a, node-b logs | Old pods `-6d4b5-a1`/`-a2` (image 1.8.2) log `CONFIG_LOADED` value 50 |
| 08:10:00 | k8s-apiserver (1 s precision) | **Causal change:** ConfigMap `checkout-db-pool` resourceVersion 1001→1002, `pool.maxConnections` 50→4, actor `ops-config-sync` |
| 08:10:41 / 08:10:52 | node-a / node-b | Old pods hot-reload: `CONFIG_RELOADED` value 4 |
| 08:11:00 | k8s-apiserver | **Correlated non-cause:** Deployment revision 2 starts; only the container image changes (1.8.2→1.8.3, actor `ci-deployer`); ConfigMap references unchanged; new ReplicaSet `checkout-api-7c9f8` |
| 08:11:12 | k8s-apiserver | New pod `-7c9f8-b1` starts; 08:11:14 `CONFIG_LOADED` value 4 |
| 08:11:30 / 08:11:33 | node-a / node-b | **Old-revision** pods log `POOL_EXHAUSTED` — symptom on pods that never ran revision 2 |
| 08:11:45 | prometheus | `checkout_api:error_ratio` 0.004 → 0.182 (alert threshold 0.05) |
| 08:11:50, 08:12:40 | node-a, node-b | New pods also log `POOL_EXHAUSTED` |
| 08:12:25 / 08:12:45 | k8s-apiserver | Old pods terminated; rollout complete 08:12:40 |
| 08:13:45 | prometheus | Alert `CheckoutHighErrorRate` fires (active since 08:11:45, `for: 2m`) |

The rollout is the change closest before the error-rate onset (45 s versus 105 s), which makes it the attractive false cause for temporal correlation. It is contradicted because the symptom appears on old-revision pods and the rollout changed nothing mapped to pool exhaustion.

## Variants (overlays in `variants/`)

| Variant | Overlay |
|---|---|
| A | Base fixture; synthesis disabled |
| B | ConfigMap change observation withheld and `k8s.configmap-checkpoints` acquisition forced to `failed` (`connector_timeout`); reload logs remain |
| C | Adds an instruction-like log line in pod `-6d4b5-a2`; synthesis stub echoes the instruction, proposes an action and fabricates a citation |
| D | node-a clock becomes `unknown`; node-b declares +3 s ± 1 s offset; one log timestamp is non-RFC 3339; Deployment and new ReplicaSet share a 1 s tick |
| E | Base evidence; synthesis stub returns an invalid schema with a fabricated citation |

Clock declarations are fixture assumptions (`fixture-declared`), not measured skew. The ±250 ms node bound in A is a synthetic setting, not evidence about real clocks.
