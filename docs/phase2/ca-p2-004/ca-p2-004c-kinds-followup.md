# Proposed follow-up: `k8s_event` and `configmap_metadata` as first-class observation kinds

**Status:** implemented in [CA-P2-004d](ca-p2-004d.md) (draft, unreviewed); this plan is kept as written. Proposed at the time, not started and not approved. This plan comes from [CA-P2-004c](ca-p2-004c.md), where Kubernetes Events and ConfigMap metadata are validated and counted but classified `unsupported_conversion`, because `ca-observation-kinds/0.1-provisional` has no kind for them. It needs a separate product-owner decision and an independent contract review before any implementation.

## Why this is a contract change, not an adapter change

- **Every plan pins the kind registry version.** Adding kinds means a new kind-registry version (`ca-observation-kinds/0.2-provisional`). Every run plan pins all contract versions (`contract_versions`), so new plans get new digests, and so do their frozen inputs and results.
- **The database checks contract pins.** It holds the contract pins (`ca.contract_pin`, migration `0001`), and `check_environment` refuses a database whose pins differ from the package.
- **The six scenario-001 result digests would change** if their plans are re-issued under 0.2.

## Proposed kinds (draft)

| Kind | Class | Source kind | Entity | Attributes (draft) | Times |
|---|---|---|---|---|---|
| `k8s_event` | `K8S-EVENT` | `kubernetes_api` | The involved object | `involved_kind`, `involved_name`, `type` (Normal/Warning), `reason` (bounded identifier), `count`, `reporting_component`. **No free-text message**, or only a hashed, length-bounded one | `event` (`eventTime`/`lastTimestamp`), optional `first_seen` |
| `configmap_metadata` | `K8S-CONFIG` | `kubernetes_api` | ConfigMap | `resource_version`, `data_key_names` (set; credential-like names refused), `binary_key_names`, `immutable`. **No values and no value digests** (a digest of a low-entropy value reveals it) | `event` (`creationTimestamp` or the observed change time) |

**Open questions for review:**
- whether a `configmap_metadata` sequence may stand in for `configmap_change` in mechanisms (it cannot show what changed);
- how Warning events may enter hypotheses (corroboration only, never a cause by themselves);
- message handling;
- event deduplication (`count`, series).

## Compatibility with existing 0.1 investigations

- **Old evidence keeps its version.** Stored 0.1 evidence, frozen inputs and results are **never reinterpreted**. A run sealed under 0.1 is replayed and verified under 0.1 only, with its stored plan and pinned versions.
- **The package must support both versions.** It must replay 0.1 runs (verify-on-read) and create 0.2 runs. Either the evidence contract keeps both kind registries, chosen by the plan's pinned version, or a versioned compatibility module is added. The engine must accept only the kinds its plan's registry version defines.
- **Results never mix versions.** No result may combine evidence from two registry versions.
- **Pinned results stay pinned.** The six scenario-001 regression digests stay pinned for their 0.1 plans. New 0.2 fixtures get their own, separately reviewed pins.

## Migration planning (database)

- **Migration `0006`** (forward-only, checksummed) changes the contract-pin model so that one database can hold runs under more than one pinned kind-registry version. It might, for example, store the supported versions and check each plan's pins against them, instead of exactly one pin per contract.
- **The environment check changes too.** `check_environment` must accept a database that supports the package's versions, without silently treating 0.1 rows as 0.2.
- **No backfill and no rewriting.** Existing rows keep their bytes and digests.

## Independent contract tests (required before acceptance)

- **Golden vectors** for both new kinds, covering identity, content digest and refused credential-like key names, reviewed independently of the implementer.
- **Cross-version tests:**
  - 0.1 runs replay byte-identically after the change;
  - 0.2 plans refuse 0.1-only kinds where required, and the reverse;
  - mixing versions is refused.
- **Adapter tests:** events and ConfigMap metadata become evidence only under 0.2 plans, still never with values, and still never with coverage for failed or unrecorded responses.
- **Database tests:** migration `0006` applies over a database holding 0.1 runs, leaves them verifiable, and refuses unknown versions.

## Out of scope for that follow-up

- live collectors (CA-P2-004d, which needs separate approval);
- AI synthesis;
- any change to how existing 0.1 results are displayed.
