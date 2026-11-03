# Contract and data-model inconsistencies, and open decisions (CA-P2-003a)

These were found by comparing the [Phase 1C logical data model](../../architecture/phase1c/data-model.md), [CA-DEC-002](../../architecture/adr/CA-DEC-002.md), the [lifecycle contract](../../evidence-lifecycle.md) and the implemented CA-P2-002a–d contracts. Each must be resolved, or explicitly deferred with an owner, **before any migration is written**. The proposals are provisional.

| ID | Inconsistency | Proposal | Decider |
|---|---|---|---|
| <a id="i1-conflict-scope"></a>I1 | **Conflict scope.** The data model quarantines a differing digest for a source identity globally. The contract classifies conflicts per seal, among one run's deliveries. | Keep both: versions are global and append-only, and conflict *for membership* is evaluated per run (derived views). Add a global conflict view for reporting. A later run that sees a different version than an earlier sealed run doesn't change the earlier run. | Architecture + DB reviewer |
| I2 | **Observation versus evidence.** The data model has separate `observation` (raw) and `evidence` (normalized) relations. The contracts produce only sanitized `ObservedEvidence`; raw source bytes are never retained. | Drop the raw observation relation for the MVP and map `ObservedEvidence` to `evidence_identity` plus `evidence_version`. Record that sanitized ingress is the earliest retained form, which matches the data model's payload note. | Architecture |
| I3 | **Run identity in plan and manifest.** CA-CON-001 lists a run ID in the plan; the implemented plan excludes it so its digest stays stable. Identical inputs in two runs give the same `manifest_digest`. | The run ID lives only in `ca.run`. `manifest_digest` is never a key, and `frozen_input` is keyed by `run_id`. | Architecture |
| I4 | **Payload purge versus digest re-verification.** The lifecycle contract purges payloads after 30 days. Afterwards `ObservedEvidence.from_record` can't re-verify a content digest, and the digests of low-entropy values (for example ConfigMap values) may themselves need removal for privacy, while manifest pages hold content digests immutably. | After purge, verification is limited to manifest and page integrity plus a lifecycle overlay (`incomplete_expired`). Decide whether sensitive attributes are stored only as salted or keyed digests, or excluded from content, before real data. This needs a new evidence contract version. | Security/privacy + DB reviewer (CA-DEC-005) |
| I5 | **Acquisition granularity.** The data model has one `acquisition` row (UUID, status, cursor, coverage) per run and source. The contract has many batches per (source, query) with a cursor chain, and summarizes acquisitions only in the manifest. | Store batches (`acquisition_batch`) and derive acquisition status at seal. The data model's acquisition row becomes the manifest's acquisition summary. | Architecture |
| I6 | **Time representation.** The data model stores parsed UTC as `timestamptz`; the contract uses integer epoch-millisecond intervals and keeps raw text. | Store `bigint` epoch milliseconds and interval bounds, with `timestamptz` only in derived views. Raw text stays in the payload bytes. | Architecture |
| I7 | **Limit enforcement under concurrency.** Count-then-insert can overshoot by one batch per concurrent worker. | Accept the overshoot because the seal re-checks every limit, or serialize ingest per run with `FOR UPDATE` on the run row. Measure in CA-IT-015. | Architecture + DB reviewer |
| I8 | **Run states.** The data model has queued, collecting, sealed, assembling, deterministic_complete and partial; the schema proposes collecting, sealing, sealed, failed and cancelled. | Add the engine states with CA-P2-005; keep `sealing` as the explicit intermediate state needed for two-phase sealing. | Architecture |
| I9 | **Gap types and identity.** The data model's gap has types only. The contract adds a `subject` and digest-based `gap_id`s that repeat across runs. | The gap primary key is `(run_id, gap_id)`; `subject` is a column. `out_of_scope` and `expired` stay reserved until lifecycle and scope work produces them. | Architecture |
| I10 | **Membership duplication.** `run_evidence` rows duplicate the evidence page contents. | Insert both from the same sealed object in one transaction; a verification query compares them (CA-IT-016). | DB reviewer |
| I11 | **Key size.** Evidence IDs are about 100-character text keys rather than UUIDs. | Accept for the MVP: content-addressed keys make idempotency a constraint. Measure index size in CA-IT-017. | DB reviewer |
| I12 | **Provisional contracts.** Every CA-P2-002 contract is unreviewed. A change after migrations exist needs a migration and a version bump. | Review CA-P2-002a–d (and their vectors) before CA-P2-003b, or explicitly accept building on provisional versions. | Product + architecture reviewer |

## <a id="decisions"></a>Decisions needed

| ID | Decision | Recommendation |
|---|---|---|
| D-DB1 | PostgreSQL 18 line, exact minor and image digest (CA-DEC-002) | 18.x latest minor at start of CA-P2-003b, digest-pinned |
| D-DB2 | Python driver | pg8000 behind an adapter; psycopg 3 only after LGPL review ([dependencies](dependencies.md)) |
| D-DB3 | Lock-file tool and network access for hashing | pip-tools or uv, with one-time approved index access |
| D-DB4 | Conflict scope (I1) | Per-run membership, global reporting view |
| D-DB5 | Sensitive attribute handling versus digest retention (I4) | Decide before any non-synthetic data; new evidence contract version |
| D-DB6 | Limit overshoot policy (I7) | Accept, with the seal re-check |
| D-DB7 | Local disposable container and CI service container | Approve for synthetic data only |
| D-DB8 | Advisory scanning service (D6) | `pip-audit` for Python packages; image scanning optional |
