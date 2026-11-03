# Proposed PostgreSQL schema (CA-P2-003a, provisional)

Status: design proposal for review, revised to apply the proposed [I1–I12 dispositions](inconsistencies.md). It is not a migration, it has not been run against any database, and it is not approval of CA-DEC-002. Every table, constraint and type here is provisional. Contract names refer to the CA-P2-002a–d contracts on PR #19 (`981b6cd`).

## Principles

- **Bytes are authoritative, columns are indexes.** Every contract record is stored as its exact canonical bytes (`bytea`), and digests are verified against those bytes. Decoded columns, and `jsonb` copies where useful, exist for constraints and queries only. PostgreSQL `jsonb` does not preserve key order, duplicate keys or number spelling (Phase 1C data model), so digests are never recomputed from `jsonb`.
- **Append-only evidence.** Contract records are inserted once and never updated or deleted by runtime roles. The only mutable rows are run state, leases and lifecycle overlays, and they change only through compare-and-swap.
- **Same-run isolation through composite keys.** Every run-scoped table carries `run_id` in its primary key, and it may reference only rows with the same `run_id`, via composite foreign keys. Global, content-addressed rows (registry, plan, evidence versions) are shared across runs but never imply membership.
- **Contract versions are columns.** A row records the exact contract version it was written under. A version change adds rows; it never rewrites stored bytes.

## Common types

```sql
CREATE SCHEMA ca;                       -- owned by ca_owner; no objects in public
CREATE DOMAIN ca.ident  AS text CHECK (VALUE ~ '^[a-z0-9][a-z0-9._-]{0,63}$');
CREATE DOMAIN ca.digest AS text CHECK (VALUE ~ '^[a-z][a-z0-9-]*/[0-9]+[.][0-9]+[a-z0-9.-]*:[0-9a-f]{64}$');
CREATE DOMAIN ca.contract_version AS text CHECK (VALUE ~ '^[a-z][a-z0-9-]{0,62}/[0-9]+[.][0-9]+([.][0-9]+)?(-[a-z0-9][a-z0-9.]{0,31})?$');
CREATE DOMAIN ca.epoch_ms AS bigint CHECK (VALUE BETWEEN -9007199254740991 AND 9007199254740991);
CREATE TYPE ca.run_state AS ENUM ('collecting', 'sealing', 'sealed', 'failed', 'cancelled');

-- I4: synthetic-only database, recorded once by the first migration and never changed.
CREATE TABLE ca.data_classification (
  singleton         boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  classification    text NOT NULL CHECK (classification = 'synthetic')
);
-- I12: pinned provisional contract versions; the adapter compares this with CONTRACT_VERSIONS.
CREATE TABLE ca.contract_pin (
  contract_name     text PRIMARY KEY,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version LIKE '%-provisional')
);
```

## Configuration and plans (global, content-addressed, immutable)

```sql
CREATE TABLE ca.registry_snapshot (
  registry_digest   ca.digest PRIMARY KEY,
  registry_id       ca.ident NOT NULL,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version = 'ca-source-registry/0.1-provisional'),
  record_bytes      bytea NOT NULL CHECK (octet_length(record_bytes) <= 1048576)
);
CREATE TABLE ca.source_binding (                       -- decoded from registry_snapshot
  registry_digest   ca.digest NOT NULL REFERENCES ca.registry_snapshot,
  source_id         ca.ident NOT NULL,
  source_kind       text NOT NULL CHECK (source_kind IN ('kubernetes_api', 'prometheus', 'loki')),
  cluster_id        ca.ident NOT NULL,
  namespace         text NOT NULL,
  binding_digest    ca.digest NOT NULL,
  PRIMARY KEY (registry_digest, source_id)
);
CREATE TABLE ca.run_plan (
  plan_digest       ca.digest PRIMARY KEY,
  plan_id           ca.ident NOT NULL,
  registry_digest   ca.digest NOT NULL REFERENCES ca.registry_snapshot,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version = 'ca-run-plan/0.2-provisional'),
  window_start_ms   ca.epoch_ms NOT NULL,
  window_end_ms     ca.epoch_ms NOT NULL CHECK (window_end_ms > window_start_ms),
  record_bytes      bytea NOT NULL CHECK (octet_length(record_bytes) <= 1048576),
  UNIQUE (plan_digest, registry_digest)                -- target for composite FKs
);
CREATE TABLE ca.plan_acquisition (                     -- decoded expected_acquisitions
  plan_digest       ca.digest NOT NULL REFERENCES ca.run_plan,
  source_id         ca.ident NOT NULL,
  query_id          ca.ident NOT NULL,
  mandatory         boolean NOT NULL,
  PRIMARY KEY (plan_digest, source_id, query_id)
);
```

## Investigations and runs

```sql
CREATE TABLE ca.investigation (
  investigation_id  uuid PRIMARY KEY,
  scenario_id       text NOT NULL,
  plan_digest       ca.digest NOT NULL REFERENCES ca.run_plan,
  created_at        timestamptz NOT NULL DEFAULT now()  -- volatile; never in a digest
);
CREATE TABLE ca.run (
  run_id            uuid PRIMARY KEY,
  investigation_id  uuid NOT NULL REFERENCES ca.investigation,
  attempt           integer NOT NULL CHECK (attempt >= 1),
  parent_run_id     uuid REFERENCES ca.run,
  plan_digest       ca.digest NOT NULL REFERENCES ca.run_plan,
  state             ca.run_state NOT NULL DEFAULT 'collecting',
  state_version     bigint NOT NULL DEFAULT 0,          -- compare-and-swap counter
  lease_owner       text,                               -- opaque worker id, no host names
  lease_expires_at  timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (investigation_id, attempt),
  UNIQUE (run_id, plan_digest)                          -- composite FK target
);
```

## Acquisition batches and delivered evidence (run-scoped, append-only)

```sql
CREATE TABLE ca.acquisition_batch (
  run_id            uuid NOT NULL,
  plan_digest       ca.digest NOT NULL,
  source_id         ca.ident NOT NULL,
  query_id          ca.ident NOT NULL,
  batch_key         ca.ident NOT NULL,
  batch_digest      ca.digest NOT NULL,                 -- canonical digest without delivery
  contract_version  ca.contract_version NOT NULL CHECK (contract_version = 'ca-acquisition-batch/0.1-provisional'),
  sequence          integer NOT NULL CHECK (sequence >= 1),
  outcome           text NOT NULL CHECK (outcome IN ('complete', 'empty', 'partial', 'failed', 'denied')),
  reason            text,
  coverage_start_ms ca.epoch_ms,
  coverage_end_ms   ca.epoch_ms,
  cursor_before     text,
  cursor_after      text,
  truncated         boolean NOT NULL,
  canonical_size    integer NOT NULL CHECK (canonical_size BETWEEN 1 AND 1048576),
  record_bytes      bytea NOT NULL,                     -- delivery.attempt stripped before storage
  PRIMARY KEY (run_id, source_id, query_id, batch_key, batch_digest),
  FOREIGN KEY (run_id, plan_digest) REFERENCES ca.run (run_id, plan_digest),
  FOREIGN KEY (plan_digest, source_id, query_id) REFERENCES ca.plan_acquisition,
  CHECK ((outcome IN ('failed', 'denied')) = (coverage_start_ms IS NULL)),
  CHECK ((coverage_start_ms IS NULL) = (coverage_end_ms IS NULL)),
  CHECK (coverage_start_ms IS NULL OR coverage_start_ms < coverage_end_ms),
  CHECK (NOT truncated OR outcome = 'partial')
);
CREATE TABLE ca.batch_delivery (                        -- volatile receipt log; excluded from digests
  run_id uuid NOT NULL, source_id ca.ident NOT NULL, query_id ca.ident NOT NULL,
  batch_key ca.ident NOT NULL, batch_digest ca.digest NOT NULL,
  attempt integer NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, source_id, query_id, batch_key, batch_digest, attempt),
  FOREIGN KEY (run_id, source_id, query_id, batch_key, batch_digest) REFERENCES ca.acquisition_batch
);
```

## Evidence identities and versions (global, content-addressed, append-only)

```sql
CREATE TABLE ca.evidence_identity (
  evidence_id       ca.digest PRIMARY KEY,              -- ca-evidence-id-sha256/0.1-provisional:...
  source_id         ca.ident NOT NULL,
  cluster_id        ca.ident NOT NULL,
  namespace         text NOT NULL,
  observation_kind  text NOT NULL,
  source_uid        text NOT NULL CHECK (char_length(source_uid) <= 256),
  source_version    text NOT NULL CHECK (char_length(source_version) <= 128),
  evidence_class    text NOT NULL,
  UNIQUE (source_id, cluster_id, namespace, observation_kind, source_uid, source_version)
);
CREATE TABLE ca.evidence_version (
  evidence_id       ca.digest NOT NULL REFERENCES ca.evidence_identity,
  content_digest    ca.digest NOT NULL,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version = 'ca-evidence/0.1-provisional'),
  record_bytes      bytea,                              -- NULL only after authorized payload purge
  payload_state     text NOT NULL DEFAULT 'available' CHECK (payload_state IN ('available', 'purged')),
  PRIMARY KEY (evidence_id, content_digest),
  CHECK ((payload_state = 'available') = (record_bytes IS NOT NULL))
);
CREATE TABLE ca.evidence_time (                         -- decoded SourceTimestamp records
  evidence_id       ca.digest NOT NULL,
  content_digest    ca.digest NOT NULL,
  timestamp_kind    ca.ident NOT NULL,
  clock_domain_id   ca.ident NOT NULL,
  parse_status      text NOT NULL CHECK (parse_status IN ('parsed', 'invalid', 'leap_second_unsupported')),
  epoch_ms          ca.epoch_ms,
  local_lower_ms    ca.epoch_ms,
  local_upper_ms    ca.epoch_ms,
  effective_precision_ns bigint,
  PRIMARY KEY (evidence_id, content_digest, timestamp_kind),
  FOREIGN KEY (evidence_id, content_digest) REFERENCES ca.evidence_version,
  CHECK ((parse_status = 'parsed') = (epoch_ms IS NOT NULL)),
  CHECK (local_lower_ms IS NULL OR local_lower_ms <= local_upper_ms)
);
```

`evidence_time` keeps decoded fields only. The raw timestamp text stays inside `record_bytes`, so it is purged with the payload.

## Run-scoped delivery, quarantine and membership

```sql
CREATE TABLE ca.run_delivered_evidence (                -- every (run, identity, version) delivered
  run_id            uuid NOT NULL REFERENCES ca.run,
  evidence_id       ca.digest NOT NULL,
  content_digest    ca.digest NOT NULL,
  PRIMARY KEY (run_id, evidence_id, content_digest),
  FOREIGN KEY (evidence_id, content_digest) REFERENCES ca.evidence_version
);
CREATE TABLE ca.batch_evidence (                        -- provenance: which batch delivered which version
  run_id uuid NOT NULL, source_id ca.ident NOT NULL, query_id ca.ident NOT NULL,
  batch_key ca.ident NOT NULL, batch_digest ca.digest NOT NULL,
  evidence_id ca.digest NOT NULL, content_digest ca.digest NOT NULL,
  PRIMARY KEY (run_id, source_id, query_id, batch_key, batch_digest, evidence_id, content_digest),
  FOREIGN KEY (run_id, source_id, query_id, batch_key, batch_digest) REFERENCES ca.acquisition_batch,
  FOREIGN KEY (run_id, evidence_id, content_digest) REFERENCES ca.run_delivered_evidence
);
CREATE VIEW ca.run_identity_conflict AS                 -- quarantine is derived, never stored state
  SELECT run_id, evidence_id, count(*) AS variant_count
  FROM ca.run_delivered_evidence GROUP BY run_id, evidence_id HAVING count(*) > 1;
CREATE VIEW ca.run_batch_conflict AS
  SELECT run_id, source_id, query_id, batch_key, count(*) AS variant_count
  FROM ca.acquisition_batch GROUP BY run_id, source_id, query_id, batch_key HAVING count(*) > 1;
```

Quarantine is a **derived view**, not a mutable flag. Every variant stays in `evidence_version` and `run_delivered_evidence`, matching the contract (every variant retained, none authoritative). Versions are global and conflicts are classified per run; see the proposed disposition of [I1](inconsistencies.md#i1-conflict-scope).

## Sealed frozen input (run-scoped, written once by the sealer)

```sql
CREATE TABLE ca.frozen_input (
  run_id            uuid PRIMARY KEY,
  plan_digest       ca.digest NOT NULL,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version = 'ca-frozen-input/0.2-provisional'),
  manifest_digest   ca.digest NOT NULL,
  status            text NOT NULL CHECK (status IN ('complete', 'incomplete')),
  root_bytes        bytea NOT NULL CHECK (octet_length(root_bytes) <= 1048576),
  FOREIGN KEY (run_id, plan_digest) REFERENCES ca.run (run_id, plan_digest)
);
CREATE TABLE ca.manifest_page (
  run_id            uuid NOT NULL REFERENCES ca.frozen_input,
  collection        text NOT NULL CHECK (collection IN ('batches', 'coverage', 'evidence', 'evidence_provenance', 'gaps')),
  page_index        integer NOT NULL CHECK (page_index >= 0),
  page_digest       ca.digest NOT NULL,
  item_count        integer NOT NULL CHECK (item_count BETWEEN 1 AND 1000),
  page_bytes        bytea NOT NULL CHECK (octet_length(page_bytes) <= 262144),
  PRIMARY KEY (run_id, collection, page_index),
  UNIQUE (run_id, page_digest)
);
CREATE TABLE ca.run_evidence (                          -- immutable membership, decoded from pages
  run_id            uuid NOT NULL REFERENCES ca.frozen_input,
  evidence_id       ca.digest NOT NULL,
  content_digest    ca.digest NOT NULL,
  coverage          text NOT NULL CHECK (coverage IN ('verified', 'unverified')),
  batch_count       integer NOT NULL CHECK (batch_count >= 1),
  PRIMARY KEY (run_id, evidence_id),                    -- one authoritative version per identity per run
  FOREIGN KEY (run_id, evidence_id, content_digest) REFERENCES ca.run_delivered_evidence
);
CREATE TABLE ca.run_gap (                              -- every ca-gap-policy/0.2 gap field (I9)
  run_id uuid NOT NULL REFERENCES ca.frozen_input,
  gap_id ca.digest NOT NULL,
  subject text NOT NULL CHECK (subject IN ('coverage', 'batch', 'identity')),
  gap_type text NOT NULL CHECK (gap_type IN ('missing', 'failed', 'truncated', 'unverifiable', 'out_of_scope', 'expired')),
  reasons text[] NOT NULL,
  source_id ca.ident, query_id ca.ident, evidence_id ca.digest,
  interval_start_ms ca.epoch_ms, interval_end_ms ca.epoch_ms,
  mandatory boolean,
  variant_count integer CHECK (variant_count IS NULL OR variant_count >= 2),
  batch_digests text[] NOT NULL,
  PRIMARY KEY (run_id, gap_id),
  CHECK ((subject = 'identity') = (evidence_id IS NOT NULL)),
  CHECK ((interval_start_ms IS NULL) = (interval_end_ms IS NULL))
);
CREATE TABLE ca.run_acquisition (                       -- decoded root acquisitions summary (I5)
  run_id uuid NOT NULL, plan_digest ca.digest NOT NULL,
  source_id ca.ident NOT NULL, query_id ca.ident NOT NULL,
  mandatory boolean NOT NULL,
  status text NOT NULL CHECK (status IN ('complete', 'empty', 'partial', 'failed', 'denied', 'missing', 'unverifiable')),
  batch_count integer NOT NULL, conflicting_batch_keys integer NOT NULL,
  observations_received integer NOT NULL, verified_ms bigint NOT NULL, gap_count integer NOT NULL,
  PRIMARY KEY (run_id, source_id, query_id),
  FOREIGN KEY (run_id) REFERENCES ca.frozen_input,
  FOREIGN KEY (run_id, plan_digest) REFERENCES ca.run (run_id, plan_digest),
  FOREIGN KEY (plan_digest, source_id, query_id) REFERENCES ca.plan_acquisition
);
CREATE TABLE ca.run_coverage (
  run_id uuid NOT NULL REFERENCES ca.frozen_input,
  source_id ca.ident NOT NULL, query_id ca.ident NOT NULL,
  start_ms ca.epoch_ms NOT NULL, end_ms ca.epoch_ms NOT NULL CHECK (end_ms > start_ms),
  PRIMARY KEY (run_id, source_id, query_id, start_ms)
);
```

The `run_evidence` foreign key to `run_delivered_evidence` is the **same-run isolation** guarantee: a run can only have members that were delivered to that same run. Later tables (hypothesis evidence, citations, CA-P2-005) reference `(run_id, evidence_id)` in `run_evidence`, never `evidence_identity`, so cross-run citation is impossible by construction.

## Run-state integrity, ingest locking and views (I3, I7, I8, I1, I5, I6)

```sql
-- I8: a run is created collecting, at state_version 0, with no lease.
CREATE TRIGGER run_insert_state BEFORE INSERT ON ca.run
  FOR EACH ROW EXECUTE FUNCTION ca.check_run_created_collecting();
-- I8: allowed transitions; each one increments state_version by exactly 1.
--   collecting -> sealing | failed | cancelled
--   sealing    -> sealing (lease takeover) | sealed | failed
--   sealed, failed, cancelled are terminal
CREATE TRIGGER run_state_transition BEFORE UPDATE ON ca.run
  FOR EACH ROW EXECUTE FUNCTION ca.check_run_transition();
-- I3: a manifest may be inserted only while its run is sealing ...
CREATE TRIGGER frozen_input_requires_sealing BEFORE INSERT ON ca.frozen_input
  FOR EACH ROW EXECUTE FUNCTION ca.check_run_is_sealing();
-- ... and a sealed run must have exactly one manifest at commit.
CREATE CONSTRAINT TRIGGER sealed_run_has_manifest AFTER UPDATE OF state ON ca.run
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ca.check_sealed_has_manifest();

-- I7: row lock for ingestion without granting UPDATE on ca.run to ca_ingest.
CREATE FUNCTION ca.ingest_lock_run(p_run uuid) RETURNS ca.run_state
  LANGUAGE sql SECURITY DEFINER SET search_path = ca, pg_catalog
  AS $$ SELECT state FROM ca.run WHERE run_id = p_run FOR UPDATE $$;
REVOKE ALL ON FUNCTION ca.ingest_lock_run(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ca.ingest_lock_run(uuid) TO ca_ingest;

CREATE VIEW ca.global_identity_versions AS             -- I1: monitoring only
  SELECT evidence_id, count(*) AS version_count FROM ca.evidence_version
  GROUP BY evidence_id HAVING count(*) > 1;
CREATE VIEW ca.live_acquisition_progress AS            -- I5: counts before sealing; never a status
  SELECT run_id, source_id, query_id, count(*) AS batch_variants, sum(canonical_size) AS stored_bytes
  FROM ca.acquisition_batch GROUP BY run_id, source_id, query_id;
CREATE VIEW ca.evidence_time_utc AS                    -- I6: exact, no floating point
  SELECT evidence_id, content_digest, timestamp_kind, clock_domain_id, parse_status,
         timestamptz 'epoch' + epoch_ms * interval '1 millisecond' AS parsed_utc
  FROM ca.evidence_time;
```

The trigger function bodies are left to CA-P2-003b. Their required behavior is defined by the acceptance tests CA-IT-023 and CA-IT-029.

## Lifecycle overlay (CA-P2-006, sketched only)

```sql
CREATE TABLE ca.lifecycle_event (
  event_id uuid PRIMARY KEY, run_id uuid REFERENCES ca.run,
  artifact_kind text NOT NULL, artifact_ref text NOT NULL,
  manifest_digest ca.digest, reason text NOT NULL, authorization_ref text NOT NULL,
  effective_at timestamptz NOT NULL, purge_state text NOT NULL
);
```

The manifest stays immutable, and the overlay records changed availability ([lifecycle contract](../../evidence-lifecycle.md)). Purging payload bytes conflicts with re-verifying content digests. That is deferred under I4: the database is synthetic-only (`data_classification`), and no role can purge until CA-P2-006 and a privacy review.

## Indexes beyond primary keys

| Index | Purpose |
|---|---|
| `acquisition_batch (run_id, source_id, query_id, sequence)` | Cursor-chain reconstruction during sealing |
| `batch_evidence (run_id, evidence_id, content_digest)` | Foreign-key support and provenance lookup |
| `run_delivered_evidence (run_id, evidence_id)` | Conflict view and sealing |
| `evidence_time (clock_domain_id, epoch_ms)` | Engine time queries (CA-P2-005) |
| `evidence_identity (source_id, source_version)` | Source lookups |
| `run_gap (run_id, gap_type)` | Gap reporting |
| `run (state, lease_expires_at)` | Recovery of expired leases |
| `frozen_input (manifest_digest)` (not unique) | Lookup by published digest; identical inputs in two runs may share it (I3) |
| `investigation (plan_digest)`, `run (plan_digest)` | Foreign-key support |

No GIN or full-text indexes. Indexes over raw text need measured justification (Phase 1C).

## Immutability enforcement

- **Statement triggers:** a trigger on every append-only table (`registry_snapshot`, `source_binding`, `run_plan`, `plan_acquisition`, `acquisition_batch`, `evidence_identity`, `evidence_version` except the lifecycle purge function, `evidence_time`, `run_delivered_evidence`, `batch_evidence`, `frozen_input`, `manifest_page`, `run_evidence`, `run_gap`, `run_coverage`, `run_acquisition`, `data_classification`, `contract_pin`) raises on `UPDATE`, `DELETE` and `TRUNCATE`.
- **Privileges:** runtime roles also lack those privileges (see [security design](security.md)).
- **Limits:** triggers and grants protect against application mistakes and compromised runtime credentials. They do not protect against the database owner or a superuser (CA-DEC-002 security implications).
