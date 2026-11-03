# Migration strategy and integration-test plan (CA-P2-003a, provisional)

Status: plan only. No migration exists or has been applied, and no database has been started.

## Versioned migrations

**Layout.** Migrations are plain SQL files `db/migrations/NNNN_short_name.sql`, numbered from `0001`. A small first-party runner (`src/cloud_autopsy/db/migrate.py`, CA-P2-003b) applies them through the chosen driver. There is no third-party migration framework.

**Ledger table:**
```sql
CREATE TABLE ca.schema_migration (
  version integer PRIMARY KEY, filename text NOT NULL, sha256 text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now(), applied_by text NOT NULL
);
```

**Rules:**
1. **One transaction per file.** PostgreSQL DDL is transactional, so a failing migration leaves no partial schema. Statements that can't run inside a transaction (for example `CREATE INDEX CONCURRENTLY`) are not used for the synthetic database.
2. **Never edit applied files.** The runner records each file's SHA-256 and refuses to proceed if an applied file has changed (checksum mismatch) or a version is missing or out of order. Corrections go in a new migration.
3. **Forward-only.** No down migrations are provided. Undoing a destructive change automatically can lose data or break digest verification.
4. **Contract changes don't rewrite stored bytes.** A new contract version adds tables or columns and writes new rows under the new version. Stored canonical bytes and digests are never transformed in place. Readers dispatch on the stored `contract_version`.
5. **Ownership.** Migrations run as `ca_migrator` (`SET ROLE ca_owner`). Runtime roles can't run DDL.
6. **Review.** Each migration is reviewed with the schema design and its privilege grants. The supply-chain check may later verify that every migration file is listed in the ledger order.

**Rollback limitations:**
- **Disposable synthetic databases:** rollback means dropping the database and re-applying migrations. That's the only supported path for CA-P2-003b.
- **Databases with retained data:** none exist yet. Recovery would need backups, which the lifecycle contract forbids until deletion propagation is designed. Until then, no environment may hold data that can't be regenerated from synthetic fixtures.
- **A failed migration** rolls back its own transaction. Earlier migrations stay applied, and the ledger shows exactly which ones.

## Local synthetic integration-test plan (for CA-P2-003b)

**Environment:**
- a disposable PostgreSQL container from the digest-pinned image, started per test session by the harness;
- loopback-only port and random per-session credentials;
- torn down afterwards;
- synthetic data only, from the CA-P2-002 vectors and generators.

The tests drive the database through the contract functions, never with hand-built rows, except in the tamper tests, which deliberately act as the owner.

| ID | Test | Expected result |
|---|---|---|
| CA-IT-001 | Apply all migrations to an empty database; re-run the runner | Schema matches; second run is a no-op; checksum ledger complete |
| CA-IT-002 | Edited applied migration | Runner refuses with a checksum mismatch |
| CA-IT-003 | Privilege matrix: every role × every table × insert, select, update, delete and truncate | Exactly the grants in the [security design](security.md); all other operations denied at runtime |
| CA-IT-004 | Duplicate batch delivery (same key, digest and observations), sequential and concurrent | One batch row, one version per identity, delivery receipts per attempt; seal output unchanged |
| CA-IT-005 | Conflicting batch content under one key | Both rows stored; `run_batch_conflict` reports it; seal emits a batch-conflict gap and excludes both |
| CA-IT-006 | Conflicting evidence content, including two concurrent sessions | Both versions stored; `run_identity_conflict` reports them; seal excludes the identity with an identity gap |
| CA-IT-007 | Cross-run access: insert `run_evidence` for evidence delivered only to another run; read another run's rows as `ca_reader` | Foreign-key violation; views return only permitted rows |
| CA-IT-008 | Concurrent sealing: two sealers on one run | Exactly one moves the run to `sealing`; one `frozen_input` row; the loser reports a lost race |
| CA-IT-009 | Ingest during and after sealing | Rejected with `run_not_collecting`; nothing written |
| CA-IT-010 | Crash between seal phases (connection dropped after phase A) | Lease expires; recovery publishes byte-identical root and pages |
| CA-IT-011 | Crash inside phase B (abort before commit) | Nothing published; a retry succeeds |
| CA-IT-012 | Tampered manifest page or root bytes in the database (owner) | `verify_full` fails with `page_digest_mismatch` or `manifest_digest_mismatch`; replay detects it |
| CA-IT-013 | Tampered `evidence_version.record_bytes` (owner) | `ObservedEvidence.from_record` fails with `content_digest_mismatch` |
| CA-IT-014 | Immutability: update, delete and truncate on append-only tables | Denied for runtime roles; trigger raises for the owner |
| CA-IT-015 | Plan limits in the database (deliveries, variants, bytes), including concurrent overshoot | `limit_exceeded`; the seal re-check rejects any overshoot |
| CA-IT-016 | Replay: re-seal from stored batches | Byte-identical to the stored `frozen_input` and pages |
| CA-IT-017 | 10,000-member run persisted and fully verified | Passes; timings recorded by the non-gating benchmark only |
| CA-IT-018 | Truth isolation | Every role except `ca_evaluator` is denied access to `ca_truth` |
| CA-IT-019 | Timeouts and retries (lock wait, deadlock) | Typed failure after bounded retries; no partial writes |
| CA-IT-020 | Canary hygiene | Credentials and canary values absent from logs, errors and stored manifests |

**CI:** a separate job uses a digest-pinned `services:` PostgreSQL container on the hosted runner. Adding it needs the workflow changes and the image approval in [dependencies](dependencies.md). The existing offline job stays unchanged and keeps gating independently.
