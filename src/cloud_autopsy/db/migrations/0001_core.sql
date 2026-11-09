-- CA-P2-003b-1 core schema (provisional). Applied once, in one transaction, by the migration
-- runner as ca_migrator with SET ROLE ca_owner. Never edit after it has been applied: the
-- runner verifies its SHA-256. Design: docs/phase2/ca-p2-003/schema.md (dispositions I1-I12).
-- Scope: local, disposable, synthetic-only databases (pre-gate development authorization).

CREATE SCHEMA ca;
REVOKE ALL ON SCHEMA ca FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ca_owner IN SCHEMA ca REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ca_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE DOMAIN ca.ident AS text CHECK (VALUE ~ '^[a-z0-9][a-z0-9._-]{0,63}$');
CREATE DOMAIN ca.digest AS text CHECK (VALUE ~ '^[a-z][a-z0-9-]*/[0-9]+[.][0-9]+[a-z0-9.-]*:[0-9a-f]{64}$');
CREATE DOMAIN ca.contract_version AS text
  CHECK (VALUE ~ '^[a-z][a-z0-9-]{0,62}/[0-9]+[.][0-9]+([.][0-9]+)?(-[a-z0-9][a-z0-9.]{0,31})?$');
CREATE DOMAIN ca.epoch_ms AS bigint CHECK (VALUE BETWEEN -9007199254740991 AND 9007199254740991);
CREATE TYPE ca.run_state AS ENUM ('collecting', 'sealing', 'sealed', 'failed', 'cancelled');

-- I4: synthetic-only database. I12: pinned provisional contract versions.
CREATE TABLE ca.data_classification (
  singleton         boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  classification    text NOT NULL CHECK (classification = 'synthetic')
);
INSERT INTO ca.data_classification (classification) VALUES ('synthetic');

CREATE TABLE ca.contract_pin (
  contract_name     text PRIMARY KEY,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version LIKE '%-provisional')
);
INSERT INTO ca.contract_pin (contract_name, contract_version) VALUES
  ('canonical-json', 'ca-jcs-profile/0.1-provisional'),
  ('canonical-digest', 'ca-jcs-profile-sha256/0.1-provisional'),
  ('time-interval', 'ca-time-interval/0.2-provisional'),
  ('source-registry', 'ca-source-registry/0.1-provisional'),
  ('observation', 'ca-observation/0.1-provisional'),
  ('observation-kinds', 'ca-observation-kinds/0.1-provisional'),
  ('evidence', 'ca-evidence/0.1-provisional'),
  ('evidence-id', 'ca-evidence-id-sha256/0.1-provisional'),
  ('evidence-content-digest', 'ca-evidence-content-sha256/0.1-provisional'),
  ('run-plan', 'ca-run-plan/0.2-provisional'),
  ('acquisition-batch', 'ca-acquisition-batch/0.1-provisional'),
  ('frozen-input', 'ca-frozen-input/0.2-provisional'),
  ('frozen-input-digest', 'ca-frozen-input-sha256/0.2-provisional'),
  ('gap-policy', 'ca-gap-policy/0.2-provisional'),
  ('frozen-input-page', 'ca-frozen-input-page/0.1-provisional'),
  ('frozen-input-page-digest', 'ca-frozen-input-page-sha256/0.1-provisional');

-- Configuration and plans: global, content-addressed, immutable.
CREATE TABLE ca.registry_snapshot (
  registry_digest   ca.digest PRIMARY KEY,
  registry_id       ca.ident NOT NULL,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version = 'ca-source-registry/0.1-provisional'),
  record_bytes      bytea NOT NULL CHECK (octet_length(record_bytes) <= 1048576)
);
CREATE TABLE ca.source_binding (
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
  UNIQUE (plan_digest, registry_digest)
);
CREATE TABLE ca.plan_acquisition (
  plan_digest       ca.digest NOT NULL REFERENCES ca.run_plan,
  source_id         ca.ident NOT NULL,
  query_id          ca.ident NOT NULL,
  mandatory         boolean NOT NULL,
  PRIMARY KEY (plan_digest, source_id, query_id)
);

-- Investigations and runs.
CREATE TABLE ca.investigation (
  investigation_id  uuid PRIMARY KEY,
  scenario_id       text NOT NULL CHECK (char_length(scenario_id) BETWEEN 1 AND 128),
  plan_digest       ca.digest NOT NULL REFERENCES ca.run_plan,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ca.run (
  run_id            uuid PRIMARY KEY,
  investigation_id  uuid NOT NULL REFERENCES ca.investigation,
  attempt           integer NOT NULL CHECK (attempt >= 1),
  parent_run_id     uuid REFERENCES ca.run,
  plan_digest       ca.digest NOT NULL REFERENCES ca.run_plan,
  state             ca.run_state NOT NULL DEFAULT 'collecting',
  state_version     bigint NOT NULL DEFAULT 0,
  lease_owner       text CHECK (lease_owner IS NULL OR char_length(lease_owner) <= 128),
  lease_expires_at  timestamptz,
  failure_reason    text CHECK (failure_reason IS NULL OR char_length(failure_reason) <= 256),
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (investigation_id, attempt),
  UNIQUE (run_id, plan_digest)
);

-- Acquisition batches and deliveries: run-scoped, append-only.
CREATE TABLE ca.acquisition_batch (
  run_id            uuid NOT NULL,
  plan_digest       ca.digest NOT NULL,
  source_id         ca.ident NOT NULL,
  query_id          ca.ident NOT NULL,
  batch_key         ca.ident NOT NULL,
  batch_digest      ca.digest NOT NULL,
  contract_version  ca.contract_version NOT NULL CHECK (contract_version = 'ca-acquisition-batch/0.1-provisional'),
  sequence          integer NOT NULL CHECK (sequence >= 1),
  outcome           text NOT NULL CHECK (outcome IN ('complete', 'empty', 'partial', 'failed', 'denied')),
  coverage_start_ms ca.epoch_ms,
  coverage_end_ms   ca.epoch_ms,
  truncated         boolean NOT NULL,
  observation_count integer NOT NULL CHECK (observation_count >= 0),
  canonical_size    integer NOT NULL CHECK (canonical_size BETWEEN 1 AND 1048576),
  record_bytes      bytea NOT NULL,
  PRIMARY KEY (run_id, source_id, query_id, batch_key, batch_digest),
  FOREIGN KEY (run_id, plan_digest) REFERENCES ca.run (run_id, plan_digest),
  FOREIGN KEY (plan_digest, source_id, query_id) REFERENCES ca.plan_acquisition,
  CHECK ((outcome IN ('failed', 'denied')) = (coverage_start_ms IS NULL)),
  CHECK ((coverage_start_ms IS NULL) = (coverage_end_ms IS NULL)),
  CHECK (coverage_start_ms IS NULL OR coverage_start_ms < coverage_end_ms),
  CHECK (NOT truncated OR outcome = 'partial')
);
CREATE TABLE ca.batch_delivery (
  run_id uuid NOT NULL, source_id ca.ident NOT NULL, query_id ca.ident NOT NULL,
  batch_key ca.ident NOT NULL, batch_digest ca.digest NOT NULL,
  delivery_no integer NOT NULL CHECK (delivery_no >= 1),
  attempt integer NOT NULL CHECK (attempt >= 1),
  received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, delivery_no),
  FOREIGN KEY (run_id, source_id, query_id, batch_key, batch_digest) REFERENCES ca.acquisition_batch
);

-- Evidence identities and versions: global, content-addressed, append-only (I1, I2).
CREATE TABLE ca.evidence_identity (
  evidence_id       ca.digest PRIMARY KEY,
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
  record_bytes      bytea,
  payload_state     text NOT NULL DEFAULT 'available' CHECK (payload_state IN ('available', 'purged')),
  PRIMARY KEY (evidence_id, content_digest),
  CHECK ((payload_state = 'available') = (record_bytes IS NOT NULL))
);
CREATE TABLE ca.evidence_time (
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

-- Run-scoped delivery and provenance (I1: conflicts are classified per run, by views).
CREATE TABLE ca.run_delivered_evidence (
  run_id            uuid NOT NULL REFERENCES ca.run,
  evidence_id       ca.digest NOT NULL,
  content_digest    ca.digest NOT NULL,
  PRIMARY KEY (run_id, evidence_id, content_digest),
  FOREIGN KEY (evidence_id, content_digest) REFERENCES ca.evidence_version
);
CREATE TABLE ca.batch_evidence (
  run_id uuid NOT NULL, source_id ca.ident NOT NULL, query_id ca.ident NOT NULL,
  batch_key ca.ident NOT NULL, batch_digest ca.digest NOT NULL,
  evidence_id ca.digest NOT NULL, content_digest ca.digest NOT NULL,
  PRIMARY KEY (run_id, source_id, query_id, batch_key, batch_digest, evidence_id, content_digest),
  FOREIGN KEY (run_id, source_id, query_id, batch_key, batch_digest) REFERENCES ca.acquisition_batch,
  FOREIGN KEY (run_id, evidence_id, content_digest) REFERENCES ca.run_delivered_evidence
);

-- Sealed frozen input: written once by the sealer (I3, I5, I9, I10).
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
CREATE TABLE ca.run_evidence (
  run_id            uuid NOT NULL REFERENCES ca.frozen_input,
  evidence_id       ca.digest NOT NULL,
  content_digest    ca.digest NOT NULL,
  coverage          text NOT NULL CHECK (coverage IN ('verified', 'unverified')),
  batch_count       integer NOT NULL CHECK (batch_count >= 1),
  PRIMARY KEY (run_id, evidence_id),
  FOREIGN KEY (run_id, evidence_id, content_digest) REFERENCES ca.run_delivered_evidence
);
CREATE TABLE ca.run_gap (
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
CREATE TABLE ca.run_coverage (
  run_id uuid NOT NULL REFERENCES ca.frozen_input,
  source_id ca.ident NOT NULL, query_id ca.ident NOT NULL,
  start_ms ca.epoch_ms NOT NULL, end_ms ca.epoch_ms NOT NULL CHECK (end_ms > start_ms),
  PRIMARY KEY (run_id, source_id, query_id, start_ms)
);
CREATE TABLE ca.run_acquisition (
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

CREATE INDEX acquisition_batch_chain ON ca.acquisition_batch (run_id, source_id, query_id, sequence);
CREATE INDEX batch_delivery_batch ON ca.batch_delivery (run_id, source_id, query_id, batch_key, batch_digest);
CREATE INDEX batch_evidence_evidence ON ca.batch_evidence (run_id, evidence_id, content_digest);
CREATE INDEX evidence_time_clock ON ca.evidence_time (clock_domain_id, epoch_ms);
CREATE INDEX evidence_identity_source ON ca.evidence_identity (source_id, source_version);
CREATE INDEX run_gap_type ON ca.run_gap (run_id, gap_type);
CREATE INDEX run_lease ON ca.run (state, lease_expires_at);
CREATE INDEX run_plan_ref ON ca.run (plan_digest);
CREATE INDEX investigation_plan ON ca.investigation (plan_digest);
CREATE INDEX frozen_input_manifest ON ca.frozen_input (manifest_digest);

-- Derived quarantine and progress views (I1, I5, I6).
CREATE VIEW ca.run_identity_conflict AS
  SELECT run_id, evidence_id, count(*) AS variant_count
  FROM ca.run_delivered_evidence GROUP BY run_id, evidence_id HAVING count(*) > 1;
CREATE VIEW ca.run_batch_conflict AS
  SELECT run_id, source_id, query_id, batch_key, count(*) AS variant_count
  FROM ca.acquisition_batch GROUP BY run_id, source_id, query_id, batch_key HAVING count(*) > 1;
CREATE VIEW ca.global_identity_versions AS
  SELECT evidence_id, count(*) AS version_count FROM ca.evidence_version
  GROUP BY evidence_id HAVING count(*) > 1;
CREATE VIEW ca.live_acquisition_progress AS
  SELECT run_id, source_id, query_id, count(*) AS batch_variants, sum(canonical_size) AS stored_bytes
  FROM ca.acquisition_batch GROUP BY run_id, source_id, query_id;
CREATE VIEW ca.evidence_time_utc AS
  SELECT evidence_id, content_digest, timestamp_kind, clock_domain_id, parse_status,
         timestamptz 'epoch' + epoch_ms * interval '1 millisecond' AS parsed_utc
  FROM ca.evidence_time;

-- Integrity triggers. Trigger functions run with the invoking role's privileges (not SECURITY DEFINER).
CREATE FUNCTION ca.forbid_mutation() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  RAISE EXCEPTION 'ca.% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE FUNCTION ca.check_run_created_collecting() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF NEW.state <> 'collecting' OR NEW.state_version <> 0 OR NEW.lease_owner IS NOT NULL
     OR NEW.lease_expires_at IS NOT NULL OR NEW.failure_reason IS NOT NULL THEN
    RAISE EXCEPTION 'a run must be created collecting at state_version 0 without a lease'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION ca.check_run_transition() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF (NEW.run_id, NEW.investigation_id, NEW.attempt, NEW.plan_digest, NEW.created_at)
     IS DISTINCT FROM (OLD.run_id, OLD.investigation_id, OLD.attempt, OLD.plan_digest, OLD.created_at)
     OR NEW.parent_run_id IS DISTINCT FROM OLD.parent_run_id THEN
    RAISE EXCEPTION 'run identity columns are immutable' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.state_version <> OLD.state_version + 1 THEN
    RAISE EXCEPTION 'state_version must increase by exactly 1' USING ERRCODE = 'check_violation';
  END IF;
  IF NOT ((OLD.state = 'collecting' AND NEW.state IN ('sealing', 'failed', 'cancelled'))
       OR (OLD.state = 'sealing' AND NEW.state IN ('sealing', 'sealed', 'failed'))) THEN
    RAISE EXCEPTION 'run state transition % -> % is not allowed', OLD.state, NEW.state
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION ca.check_run_is_sealing() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ca.run r WHERE r.run_id = NEW.run_id AND r.state = 'sealing'
                 AND r.plan_digest = NEW.plan_digest) THEN
    RAISE EXCEPTION 'a manifest may only be inserted while its run is sealing'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION ca.check_sealed_has_manifest() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF NEW.state = 'sealed' AND NOT EXISTS (SELECT 1 FROM ca.frozen_input f WHERE f.run_id = NEW.run_id) THEN
    RAISE EXCEPTION 'a sealed run must have exactly one manifest' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER run_insert_state BEFORE INSERT ON ca.run
  FOR EACH ROW EXECUTE FUNCTION ca.check_run_created_collecting();
CREATE TRIGGER run_state_transition BEFORE UPDATE ON ca.run
  FOR EACH ROW EXECUTE FUNCTION ca.check_run_transition();
CREATE TRIGGER frozen_input_requires_sealing BEFORE INSERT ON ca.frozen_input
  FOR EACH ROW EXECUTE FUNCTION ca.check_run_is_sealing();
CREATE CONSTRAINT TRIGGER sealed_run_has_manifest AFTER UPDATE OF state ON ca.run
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ca.check_sealed_has_manifest();
CREATE TRIGGER run_no_delete BEFORE DELETE ON ca.run FOR EACH ROW EXECUTE FUNCTION ca.forbid_mutation();
CREATE TRIGGER run_no_truncate BEFORE TRUNCATE ON ca.run FOR EACH STATEMENT EXECUTE FUNCTION ca.forbid_mutation();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['data_classification', 'contract_pin', 'registry_snapshot', 'source_binding',
    'run_plan', 'plan_acquisition', 'investigation', 'acquisition_batch', 'batch_delivery', 'evidence_identity',
    'evidence_version', 'evidence_time', 'run_delivered_evidence', 'batch_evidence', 'frozen_input',
    'manifest_page', 'run_evidence', 'run_gap', 'run_coverage', 'run_acquisition'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ca.%I FOR EACH ROW EXECUTE FUNCTION ca.forbid_mutation()',
                   t || '_append_only', t);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON ca.%I FOR EACH STATEMENT EXECUTE FUNCTION ca.forbid_mutation()',
                   t || '_no_truncate', t);
  END LOOP;
END $$;

-- I7: per-run ingest serialization without granting UPDATE on ca.run to ca_ingest.
CREATE FUNCTION ca.ingest_lock_run(p_run uuid) RETURNS ca.run_state
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
  AS $$ SELECT r.state FROM ca.run r WHERE r.run_id = p_run FOR UPDATE $$;
REVOKE ALL ON FUNCTION ca.ingest_lock_run(uuid) FROM PUBLIC;

-- Grants (least privilege; docs/phase2/ca-p2-003/security.md).
GRANT USAGE ON SCHEMA ca TO ca_planner, ca_ingest, ca_sealer, ca_reader;
GRANT SELECT ON ca.data_classification, ca.contract_pin TO ca_planner, ca_ingest, ca_sealer, ca_reader;

GRANT SELECT, INSERT ON ca.registry_snapshot, ca.source_binding, ca.run_plan, ca.plan_acquisition,
  ca.investigation, ca.run TO ca_planner;

GRANT SELECT ON ca.run, ca.run_plan, ca.plan_acquisition, ca.registry_snapshot, ca.source_binding,
  ca.acquisition_batch, ca.batch_delivery, ca.evidence_identity, ca.run_delivered_evidence TO ca_ingest;
GRANT INSERT ON ca.acquisition_batch, ca.batch_delivery, ca.evidence_identity, ca.evidence_version,
  ca.evidence_time, ca.run_delivered_evidence, ca.batch_evidence TO ca_ingest;
GRANT EXECUTE ON FUNCTION ca.ingest_lock_run(uuid) TO ca_ingest;

GRANT SELECT ON ca.run, ca.run_plan, ca.plan_acquisition, ca.registry_snapshot, ca.source_binding,
  ca.acquisition_batch, ca.batch_delivery, ca.evidence_identity, ca.evidence_version, ca.evidence_time,
  ca.run_delivered_evidence, ca.batch_evidence, ca.frozen_input, ca.manifest_page, ca.run_evidence,
  ca.run_gap, ca.run_coverage, ca.run_acquisition TO ca_sealer;
GRANT INSERT ON ca.frozen_input, ca.manifest_page, ca.run_evidence, ca.run_gap, ca.run_coverage,
  ca.run_acquisition TO ca_sealer;
GRANT UPDATE (state, state_version, lease_owner, lease_expires_at, failure_reason) ON ca.run TO ca_sealer;

GRANT SELECT ON ca.frozen_input, ca.manifest_page, ca.run_evidence, ca.run_gap, ca.run_coverage,
  ca.run_acquisition, ca.run_identity_conflict, ca.run_batch_conflict, ca.global_identity_versions,
  ca.live_acquisition_progress, ca.evidence_time_utc TO ca_reader;
