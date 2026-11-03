# Contract and data-model inconsistencies: proposed dispositions (CA-P2-003a)

Status: every disposition is **proposed and provisional**. Product-owner preferences (2026-11-03) were given for I1, I3, I4, I5, I7 and I12. The rest are engineering proposals. No specialist approval has been recorded for any item, and no SSDLC gate is passed. Sources: [Phase 1C data model](../../architecture/phase1c/data-model.md), [CA-DEC-002](../../architecture/adr/CA-DEC-002.md), [lifecycle contract](../../evidence-lifecycle.md) and the CA-P2-002a–d contracts on PR #19 (`981b6cd`).

**Migration-blocking contradictions remaining:** none in the design. I4 is a deliberate **deferral**: real data stays blocked, and synthetic-only use is enforced. The approvals listed under each item and in the [CA-P2-003b blockers](README.md#ca-p2-003b-blockers) are still outstanding.

**Roles named below:**
- **Architecture lead** (design owner);
- **DB reviewer** (database and architecture specialist);
- **Security reviewer**;
- **Privacy/lifecycle reviewer**;
- **Licensing reviewer**;
- **Product authority**.

Under CA-DEC-008 no person is appointed to any of these yet.

## <a id="i1-conflict-scope"></a>I1 — Conflict scope

1. **Resolution (owner preference):** evidence versions are global and append-only (`evidence_version`, primary key `(evidence_id, content_digest)`). Conflicts are classified per run from that run's deliveries only (`run_identity_conflict` view), exactly as the contract's per-seal ledger does. A global `global_identity_versions` view reports identities with several versions across runs, for monitoring only. It never changes a sealed run or another run's classification.
2. **Compatibility:** none. This matches `EvidenceLedger` and `seal` (gap policy 0.2). The Phase 1C phrase "differing digest quarantines conflict" is read as per-run quarantine; that wording needs the DB reviewer's acceptance.
3. **Constraints:**
   - primary key `evidence_version (evidence_id, content_digest)` and foreign key to `evidence_identity`;
   - no unique constraint on `evidence_id` alone;
   - `run_evidence` primary key `(run_id, evidence_id)` allows one member version per run;
   - views as described.
4. **Acceptance tests:**
   - CA-IT-006: a per-run conflict excludes the identity, including when written by two concurrent sessions;
   - CA-IT-021: run A seals with version v1, run B later receives v2, run A's rows and manifest are unchanged, run B is classified only on its own deliveries, and the global view lists both versions.
5. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I2 — Raw observation versus normalized evidence

1. **Resolution:**
   - Drop the separate raw `observation` relation for the MVP.
   - `ObservedEvidence` maps to `evidence_identity` (identity columns) plus `evidence_version` (canonical record bytes and content digest).
   - Sanitized, normalized ingress is the earliest retained form, and the system never claims to hold original source bytes. The Phase 1C payload note already says retained bytes are sanitized ingress.
2. **Compatibility:** no contract change. The data model's observation uniqueness rule (source identity, version and kind) is carried by the `evidence_identity` unique key. "Raw/derived separation" is preserved as observed versus derived evidence; derived evidence remains a later contract.
3. **Constraints:**
   - `evidence_identity` unique on `(source_id, cluster_id, namespace, observation_kind, source_uid, source_version)`;
   - `evidence_version.record_bytes` holds the exact `ca-evidence/0.1-provisional` bytes;
   - no raw-payload column anywhere.
4. **Acceptance tests:**
   - CA-IT-022: every stored version decodes through `ObservedEvidence.from_record` with the pinned registry, giving identical ID and digest;
   - a schema introspection test confirms there is no raw observation table or column.
5. **Consequence:** replay cannot reach bytes the source sent before sanitization; it reproduces only from sanitized evidence. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer and security reviewer, who must confirm that sanitized-only retention is acceptable.

## I3 — Run identity, plan and manifest

1. **Resolution (owner preference):** the run ID stays out of the reusable `RunPlan`, so the plan digest is stable across retries. Database constraints tie the manifest to a run:
   - `frozen_input.run_id` is the primary key with a foreign key `(run_id, plan_digest)` to `run (run_id, plan_digest)`, so a manifest can belong only to a run of the same plan;
   - an insert trigger allows a `frozen_input` row only while that run is in state `sealing`;
   - a deferred constraint trigger requires every `sealed` run to have exactly one `frozen_input` row.

   `manifest_digest` is never a key, because two runs with identical inputs may produce the same digest.
2. **Compatibility:** none. The manifest root's `plan_digest` must equal the run's `plan_digest`, which phase B checks before inserting.
3. **Constraints:**
   - the primary key and composite foreign key above;
   - the trigger `frozen_input_requires_sealing`;
   - the deferred constraint trigger `sealed_run_has_manifest`;
   - the run-state transition trigger (see I8);
   - `manifest_digest` indexed but not unique.
4. **Acceptance tests:**
   - CA-IT-008, concurrent sealers;
   - CA-IT-023: insert a manifest for a `collecting` or `sealed` run, or with another plan's digest, and the insert is rejected;
   - CA-IT-024: two runs of one plan with identical batches give equal manifest digests and two `frozen_input` rows.
5. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I4 — Payload purge, sensitive values and low-entropy digests (deferral)

1. **Resolution (owner preference): explicit deferral.**
   - **Scope:** synthetic data only. Retaining real data, storing sensitive ConfigMap values and exposing digests of short, guessable values all stay blocked until a privacy review.
   - **Enforcement:**
     - a single-row, immutable `ca.data_classification` table holds `'synthetic'`, created by the first migration;
     - the CA-P2-003b adapter refuses to start unless it reads `'synthetic'`;
     - no migration may change the value (the immutability trigger enforces this).
   - **Not designed yet:** the payload-purge path (`payload_state = 'purged'`) is in the schema for future use, but no role can trigger it until CA-P2-006.
2. **Compatibility:**
   - **No current change.** The current `ca-evidence/0.1-provisional` contract stores ConfigMap before and after values, and their SHA-256, in clear. That is acceptable only for synthetic data.
   - **Before real data:** a new evidence contract version must decide on keyed or salted digests, or on excluding such fields. Manifest pages hold content digests immutably, so after a purge, verification is limited to manifest integrity plus a lifecycle overlay (`incomplete_expired`).
3. **Constraints:**
   - `data_classification` with a single-row `CHECK (classification = 'synthetic')`;
   - `evidence_version` purge consistency `CHECK`;
   - no `UPDATE` grant on `evidence_version` for any runtime role.
4. **Acceptance tests:**
   - CA-IT-025: the classification row exists, can't be updated or deleted, and the adapter refuses a database without it;
   - CA-IT-014: immutability.
5. **Responsible:** Product authority (scope) and Architecture lead. **Outstanding approval:** privacy/lifecycle reviewer and security reviewer (CA-DEC-005), before any non-synthetic data.

## I5 — Acquisition granularity

1. **Resolution (owner preference):** persist every acquisition batch (`acquisition_batch`) and derive acquisition summaries.
   - **After sealing:** the summaries are copied from the manifest root into an immutable `run_acquisition` table in the seal's phase B.
   - **Before sealing:** the `live_acquisition_progress` view gives counts only, and never a status.

   The data model's single acquisition row with status and cursor becomes the manifest's acquisition summary. Cursor provenance stays in batch rows.
2. **Compatibility:** none. This matches `AcquisitionBatch` 0.1 and the 0.2 seal.
3. **Constraints:**
   - `acquisition_batch` primary key `(run_id, source_id, query_id, batch_key, batch_digest)`, with foreign keys to `run (run_id, plan_digest)` and `plan_acquisition`;
   - `run_acquisition` primary key `(run_id, source_id, query_id)`, with foreign keys to `frozen_input` and `plan_acquisition`;
   - a status `CHECK` covering the contract's statuses.
4. **Acceptance tests:**
   - CA-IT-026: `run_acquisition` equals the root's `acquisitions` for every scenario vector;
   - CA-IT-004 and CA-IT-005 for batches.
5. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I6 — Time representation

1. **Resolution:**
   - Store `bigint` epoch milliseconds and interval bounds (`evidence_time`) exactly as the time contract derives them, with `NULL` for unparsed timestamps.
   - Raw text stays only in the canonical record bytes.
   - `timestamptz` appears only in the read view `evidence_time_utc`, computed exactly as `timestamptz 'epoch' + epoch_ms * interval '1 millisecond'`, never through floating point.
2. **Rationale:** the contract's ordering rules work on integer intervals, so `timestamptz` adds nothing but rounding risk. **Consequence:** queries by wall time go through the view.
3. **Constraints:**
   - the `ca.epoch_ms` domain (±(2^53−1));
   - `CHECK ((parse_status = 'parsed') = (epoch_ms IS NOT NULL))`;
   - `CHECK (local_lower_ms <= local_upper_ms)`.
4. **Acceptance tests:**
   - CA-IT-027: every time vector round-trips with identical integers, the view matches `format_utc_ms` exactly for years 0000–9999, and invalid or leap-second rows have `NULL` times.
5. **Compatibility:** none. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I7 — Limit enforcement under concurrency

1. **Resolution (owner preference):** serialize ingestion per run.
   - Each ingest transaction first locks the run row with `FOR UPDATE`, through `ca.ingest_lock_run(run_id)`. Plan-limit counts are then exact, with no overshoot.
   - The seal's phase A takes the same lock, so sealing and ingestion are mutually exclusive.
   - PostgreSQL requires `UPDATE` privilege to take a row lock. `ca_ingest` therefore gets no `UPDATE` on `run`; it gets `EXECUTE` on a `SECURITY DEFINER` function owned by `ca_owner`, which locks the row and returns the run state. The row lock lasts until the caller's transaction ends.
2. **Consequence:**
   - batches for one run are written one at a time; different runs still proceed in parallel;
   - throughput per run is unmeasured (CA-DEC-007).
3. **Constraints:**
   - function `ca.ingest_lock_run(uuid) RETURNS ca.run_state`, declared `SECURITY DEFINER`, with `SET search_path = pg_catalog, pg_temp` and a schema-qualified body, `REVOKE ALL ... FROM PUBLIC`, and default privileges revoking function `EXECUTE` from `PUBLIC` (role review R2 and R3 in the [CA-P2-003b checkpoint](ca-p2-003b-checkpoint.md));
   - `GRANT EXECUTE` to `ca_ingest` only;
   - limit checks inside T1;
   - the seal still re-checks every limit through the contract code.
4. **Acceptance tests:**
   - CA-IT-015: concurrent ingestion at a limit, with exactly the allowed number committed and the rest rejected with `limit_exceeded`;
   - CA-IT-028: `ca_ingest` can't `UPDATE ca.run` or take a lock directly, but can call the function;
   - CA-IT-019: lock timeouts.
5. **Compatibility:** none. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer and security reviewer, for the `SECURITY DEFINER` function.

## I8 — Run states

1. **Resolution:**
   - `run.state` covers collection and sealing only: `collecting`, `sealing`, `sealed`, `failed` and `cancelled`.
   - Engine assembly states from Phase 1C (`assembling`, `deterministic_complete`, `partial`) go in a separate `run_assembly` table, added with CA-P2-005, so engine outcomes never change sealing invariants.
   - `queued` is omitted, because a run row is created when collection starts.
   - Allowed transitions are enforced by a trigger:
     - `collecting` → `sealing`, `failed` or `cancelled`;
     - `sealing` → `sealing` (lease takeover, with `state_version + 1`), `sealed` or `failed`;
     - `sealed`, `failed` and `cancelled` are terminal.
   - Every transition must increment `state_version` by exactly 1.
2. **Compatibility:** none for the contracts. It refines the Phase 1C state list, which needs Architecture lead sign-off.
3. **Constraints:**
   - the `ca.run_state` enum;
   - the `run_insert_state` trigger (new runs are `collecting`, at `state_version` 0, with no lease);
   - the `run_state_transition` trigger;
   - the I3 triggers;
   - column-level `UPDATE` for `ca_sealer` only.
4. **Acceptance tests:**
   - CA-IT-029: every illegal transition is rejected, a skipped or reused `state_version` is rejected, and inserting a run in any state other than `collecting` is rejected;
   - CA-IT-010 and CA-IT-011 cover recovery paths.
5. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I9 — Gap identity and columns

1. **Resolution:**
   - The `run_gap` primary key is `(run_id, gap_id)`. `gap_id` is a content digest and repeats across runs.
   - It stores every contract gap field: `subject`, `gap_type`, `reasons text[]`, `source_id`, `query_id`, the interval, `mandatory`, `evidence_id`, `variant_count` and `batch_digests text[]`.
   - `out_of_scope` and `expired` stay allowed but unused until scope and lifecycle work produces them.
2. **Compatibility:** none. This mirrors `ca-gap-policy/0.2-provisional` gap items. It is also an internal consistency fix: the first draft omitted four fields.
3. **Constraints:**
   - `subject` and `gap_type` checks;
   - `CHECK ((subject = 'identity') = (evidence_id IS NOT NULL))`;
   - `CHECK ((interval_start_ms IS NULL) = (interval_end_ms IS NULL))`;
   - a foreign key to `frozen_input`.
4. **Acceptance tests:** CA-IT-026 checks that `run_gap` equals the `gaps` page items for every scenario vector, field for field.
5. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I10 — Membership stored both as pages and as rows

1. **Resolution:**
   - **The pages are authoritative.** The decoded tables `run_evidence`, `run_gap`, `run_coverage` and `run_acquisition` are written in phase B from the same `FrozenInput` object, in the same transaction.
   - **The rows serve integrity and queries.** `run_evidence` carries the same-run foreign key and is the citation target for CA-P2-005.
   - **Comparison:** a verification query, run as the last step of phase B and again by the integration tests, compares the rows with the page items and aborts the transaction on any difference.
2. **Consequence:** more storage, and a second copy that is checked, never trusted alone.
3. **Constraints:**
   - foreign keys from every decoded table to `frozen_input`;
   - `run_evidence` foreign key to `run_delivered_evidence`;
   - the immutability triggers.
4. **Acceptance tests:**
   - CA-IT-026, decoded rows equal pages;
   - CA-IT-030: a deliberately mismatched decoded row aborts phase B.
5. **Compatibility:** none. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I11 — Text primary keys

1. **Resolution:** accept text keys (evidence IDs of about 100 characters, digests of about 110) for the MVP. Content-addressed keys make idempotency a plain unique constraint, and IDs keep their algorithm label. A surrogate `bigint` key may be added later by migration, keeping the text key unique, if measurements justify it.
2. **Consequence:** larger indexes, which is acceptable at the provisional 100,000-record ceiling.
3. **Constraints:** the `ca.digest` and `ca.ident` domains bound the format and length.
4. **Acceptance tests:** CA-IT-017 records table and index sizes for a 10,000-member run. This is non-gating and goes in the benchmark output.
5. **Compatibility:** none. **Responsible:** Architecture lead. **Outstanding approval:** DB reviewer.

## I12 — Provisional contracts

1. **Resolution (owner preference):** bounded preparatory work may target **explicitly pinned** provisional contract versions, without treating them as stable or production-approved.
   - The first migration pins each contract version in a `contract_version` `CHECK` on every table that stores contract bytes. For example, `acquisition_batch.contract_version = 'ca-acquisition-batch/0.1-provisional'`.
   - Changing a pinned version needs a new migration and a new review.
   - The adapter refuses plans whose `contract_versions` differ from the pinned set.
2. **Compatibility:** pins to the PR #19 head (`981b6cd`):

   | Contract | Version |
   |---|---|
   | canonical JSON | `ca-jcs-profile/0.1-provisional` |
   | time interval | `ca-time-interval/0.2-provisional` |
   | source registry | `ca-source-registry/0.1-provisional` |
   | observation | `ca-observation/0.1-provisional` |
   | observation kinds | `ca-observation-kinds/0.1-provisional` |
   | evidence | `ca-evidence/0.1-provisional` |
   | evidence ID | `ca-evidence-id-sha256/0.1-provisional` |
   | content digest | `ca-evidence-content-sha256/0.1-provisional` |
   | run plan | `ca-run-plan/0.2-provisional` |
   | acquisition batch | `ca-acquisition-batch/0.1-provisional` |
   | frozen input and digest | `ca-frozen-input/0.2-provisional`, `ca-frozen-input-sha256/0.2-provisional` |
   | page and page digest | `ca-frozen-input-page/0.1-provisional`, `ca-frozen-input-page-sha256/0.1-provisional` |
   | gap policy | `ca-gap-policy/0.2-provisional` |

   The suffix `-provisional` stays visible in every stored row.
3. **Constraints:**
   - per-table `contract_version` checks;
   - a `ca.contract_pin` table, written once by the migration, that the adapter compares with the package's `CONTRACT_VERSIONS`.
4. **Acceptance tests:**
   - CA-IT-031: a row with any other version is rejected;
   - the adapter refuses a plan or package version mismatch;
   - the pin table equals `CONTRACT_VERSIONS`.
5. **Responsible:** Product authority (scope) and Architecture lead. **Outstanding approval:** independent review of CA-P2-002a–d (architecture and security), still required before anything is called stable.

## Internal consistency fixes made in this revision

| ID | Contradiction in the first draft (`52d8c23`) | Fix |
|---|---|---|
| C1 | T1 locked `ca.run` with `FOR SHARE`, but PostgreSQL requires `UPDATE` privilege for row locks, and `ca_ingest` had only `SELECT` | `ca.ingest_lock_run` `SECURITY DEFINER` function (I7) |
| C2 | `run_gap` lacked `reasons`, `mandatory`, `variant_count` and `batch_digests` | Columns added (I9) |
| C3 | No persisted acquisition summary | `run_acquisition` table written in phase B (I5) |
| C4 | Nothing stopped manifest insertion outside `sealing`, or illegal state changes | `frozen_input_requires_sealing`, `sealed_run_has_manifest` and `run_state_transition` triggers (I3, I8) |
| C5 | Contract versions not pinned | Per-table checks and `contract_pin` (I12) |
| C6 | `ca_sealer` lacked `INSERT` on the new decoded tables | Grants updated ([security](security.md)) |
| C7 | Limit overshoot accepted in T1 | Per-run serialization (I7); [transaction model](transactions.md) updated |
| C8 | `ca_planner` could insert a run already `sealed` or with a lease | `run_insert_state` trigger (I8) |

## <a id="decisions"></a>Decisions still needed (not engineering)

| ID | Decision | Recommendation | Decider |
|---|---|---|---|
| D-DB1 | PostgreSQL 18 minor and image digest | **Proposed:** 18.6, `postgres:18.6-trixie@sha256:3a4264520e121176619f54ff867d12774bc81e95e7b84db58d63bccdb6144b81`, re-checked when CA-P2-003b starts ([D-DB1 record](d-db1-postgresql-pin.md)) | DB reviewer + security reviewer |
| D-DB2 | Python driver | **Proposed disposition:** pg8000 1.31.6, scramp 1.5.0, asn1crypto 1.5.1, python-dateutil 2.9.0.post0 and six 1.17.0, behind an adapter; psycopg 3 only after LGPL review ([D-DB2 decision](d-db2-driver-decision.md)) | Licensing reviewer + architecture lead + product authority |
| D-DB3 | Lock-file tool and one-time package-index access | pip-tools or uv | Repository maintainer + security reviewer |
| D-DB7 | Local disposable container and CI service container | Approve for synthetic data only | Product authority + security reviewer |
| D-DB8 | Advisory scanning service (D6) | `pip-audit` | Security reviewer |
| D-DB5 | Sensitive attributes and digests (I4) | Decide before any non-synthetic data | Privacy/lifecycle reviewer |

D-DB4 (I1) and D-DB6 (I7) are no longer open as engineering questions; the product owner gave preferences. They still need the DB reviewer's approval, which is recorded under I1 and I7.
