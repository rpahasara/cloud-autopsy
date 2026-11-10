-- CA-P2-006a (provisional): frozen clock declarations and immutable investigation results.
-- Local, disposable, synthetic-only databases under the pre-gate development authorization.
-- Design: docs/phase2/ca-p2-006/ca-p2-006a.md.
--
-- ca.run_clock_declaration  one ca-clock-declaration/0.1-provisional document per run, written by
--                           ca_planner while the run is still collecting, so the clock
--                           assumptions are fixed before the evidence is sealed. Append-only.
-- ca.investigation_result   one ca-investigation-result/0.2-provisional document per sealed run,
--                           written once by the new ca_result_writer role. Append-only: an
--                           identical retry is a no-op in the storage module, a different
--                           result for the same run is refused (primary key), never overwritten.
-- Bindings are enforced here, not only in Python: composite foreign keys tie a result to its own
-- run's investigation, plan, sealed manifest and clock declaration; a SECURITY DEFINER trigger
-- requires the run to be sealed, the plan to pin the result's versions, and the columns to equal
-- the fields inside the stored bytes; CHECK constraints recompute SHA-256 over the stored bytes.

-- Targets for the same-run composite foreign keys.
ALTER TABLE ca.run ADD CONSTRAINT run_investigation_key UNIQUE (run_id, investigation_id);
ALTER TABLE ca.frozen_input ADD CONSTRAINT frozen_input_manifest_key UNIQUE (run_id, manifest_digest);

CREATE TABLE ca.run_clock_declaration (
  run_id              uuid PRIMARY KEY,
  plan_digest         ca.digest NOT NULL,
  registry_digest     ca.digest NOT NULL,
  contract_version    ca.contract_version NOT NULL
                      CHECK (contract_version = 'ca-clock-declaration/0.1-provisional'),
  declaration_digest  ca.digest NOT NULL,
  declaration_bytes   bytea NOT NULL CHECK (octet_length(declaration_bytes) BETWEEN 2 AND 65536),
  FOREIGN KEY (run_id, plan_digest) REFERENCES ca.run (run_id, plan_digest),
  FOREIGN KEY (plan_digest, registry_digest) REFERENCES ca.run_plan (plan_digest, registry_digest),
  UNIQUE (run_id, declaration_digest),
  CHECK (declaration_digest = 'ca-clock-declaration-sha256/0.1-provisional:' || encode(sha256(declaration_bytes), 'hex'))
);

CREATE TABLE ca.investigation_result (
  run_id                    uuid PRIMARY KEY,
  investigation_id          uuid NOT NULL,
  plan_digest               ca.digest NOT NULL,
  manifest_digest           ca.digest NOT NULL,
  clock_declaration_digest  ca.digest NOT NULL,
  contract_version          ca.contract_version NOT NULL
                            CHECK (contract_version = 'ca-investigation-result/0.2-provisional'),
  result_digest             ca.digest NOT NULL
                            CHECK (result_digest LIKE 'ca-investigation-result-sha256/0.2-provisional:%'),
  engine_version            ca.contract_version NOT NULL,
  catalog_version           ca.contract_version NOT NULL,
  timeline_rules_version    ca.contract_version NOT NULL,
  outcome_status            text NOT NULL CHECK (outcome_status IN ('resolved', 'abstained')),
  result_bytes              bytea NOT NULL CHECK (octet_length(result_bytes) BETWEEN 2 AND 8388608),
  result_bytes_sha256       text NOT NULL CHECK (result_bytes_sha256 = encode(sha256(result_bytes), 'hex')),
  stored_at                 timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (run_id, investigation_id) REFERENCES ca.run (run_id, investigation_id),
  FOREIGN KEY (run_id, plan_digest) REFERENCES ca.run (run_id, plan_digest),
  FOREIGN KEY (run_id, manifest_digest) REFERENCES ca.frozen_input (run_id, manifest_digest),
  FOREIGN KEY (run_id, clock_declaration_digest) REFERENCES ca.run_clock_declaration (run_id, declaration_digest)
);

-- Declaration content: the document's own version and registry equal the columns, and it declares
-- exactly the clock domains bound to the registry's sources, each once. Invoker rights: ca_planner
-- already reads run_plan and registry_snapshot. (The run-state check reuses 0002's trigger.)
CREATE FUNCTION ca.check_clock_declaration() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  doc jsonb;
  registry jsonb;
  declared text[];
  registered text[];
BEGIN
  doc := convert_from(NEW.declaration_bytes, 'UTF8')::jsonb;
  IF doc->>'contract_version' IS DISTINCT FROM NEW.contract_version
     OR doc->>'registry_digest' IS DISTINCT FROM NEW.registry_digest
     OR jsonb_typeof(doc->'clock_domains') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'clock declaration fields differ from its columns' USING ERRCODE = 'check_violation';
  END IF;
  SELECT convert_from(s.record_bytes, 'UTF8')::jsonb INTO registry
    FROM ca.registry_snapshot s WHERE s.registry_digest = NEW.registry_digest;
  -- Duplicates stay in ``declared`` (so they cannot match); ``registered`` is distinct.
  declared := ARRAY(SELECT e->>'clock_domain_id' AS id FROM jsonb_array_elements(doc->'clock_domains') e
                    ORDER BY (e->>'clock_domain_id') COLLATE "C");
  registered := ARRAY(SELECT q.id FROM (SELECT DISTINCT d AS id FROM jsonb_array_elements(registry->'sources') s,
                                         jsonb_array_elements_text(s->'clock_domain_ids') d) q
                      ORDER BY q.id COLLATE "C");
  IF declared IS DISTINCT FROM registered THEN
    RAISE EXCEPTION 'a clock declaration must declare exactly the registry''s clock domains, once each'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION ca.check_clock_declaration() FROM PUBLIC;

CREATE TRIGGER run_clock_declaration_requires_collecting BEFORE INSERT ON ca.run_clock_declaration
  FOR EACH ROW EXECUTE FUNCTION ca.check_ingest_run_collecting();
CREATE TRIGGER run_clock_declaration_content BEFORE INSERT ON ca.run_clock_declaration
  FOR EACH ROW EXECUTE FUNCTION ca.check_clock_declaration();

-- Result binding. SECURITY DEFINER: ca_result_writer has no grant on ca.run or ca.run_plan.
-- ``sealed`` is terminal (0001 check_run_transition), so no row lock is needed.
-- Trigger firing does not check EXECUTE, so EXECUTE is granted to no role.
CREATE FUNCTION ca.check_investigation_result() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  run_state ca.run_state;
  rules jsonb;
  doc jsonb;
BEGIN
  SELECT r.state INTO run_state FROM ca.run r WHERE r.run_id = NEW.run_id;
  IF run_state IS DISTINCT FROM 'sealed'::ca.run_state THEN
    RAISE EXCEPTION 'a result may only be stored for a sealed run' USING ERRCODE = 'check_violation';
  END IF;
  SELECT convert_from(p.record_bytes, 'UTF8')::jsonb->'rule_versions' INTO rules
    FROM ca.run_plan p WHERE p.plan_digest = NEW.plan_digest;
  IF rules->>'investigation-result' IS DISTINCT FROM NEW.contract_version
     OR rules->>'investigation-engine' IS DISTINCT FROM NEW.engine_version
     OR rules->>'mechanism-catalog' IS DISTINCT FROM NEW.catalog_version
     OR rules->>'timeline-rules' IS DISTINCT FROM NEW.timeline_rules_version THEN
    RAISE EXCEPTION 'result versions differ from the versions pinned by the run''s plan'
      USING ERRCODE = 'check_violation';
  END IF;
  doc := convert_from(NEW.result_bytes, 'UTF8')::jsonb;
  IF doc->>'contract_version' IS DISTINCT FROM NEW.contract_version
     OR doc->>'result_digest' IS DISTINCT FROM NEW.result_digest
     OR doc->>'engine_version' IS DISTINCT FROM NEW.engine_version
     OR doc->'rule_versions'->>'mechanism-catalog' IS DISTINCT FROM NEW.catalog_version
     OR doc->'rule_versions'->>'timeline-rules' IS DISTINCT FROM NEW.timeline_rules_version
     OR doc->'inputs'->>'plan_digest' IS DISTINCT FROM NEW.plan_digest
     OR doc->'inputs'->>'manifest_digest' IS DISTINCT FROM NEW.manifest_digest
     OR doc->'inputs'->>'clock_declaration_digest' IS DISTINCT FROM NEW.clock_declaration_digest
     OR doc->'outcome'->>'status' IS DISTINCT FROM NEW.outcome_status THEN
    RAISE EXCEPTION 'result columns differ from the fields inside the stored bytes'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION ca.check_investigation_result() FROM PUBLIC;

CREATE TRIGGER investigation_result_binding BEFORE INSERT ON ca.investigation_result
  FOR EACH ROW EXECUTE FUNCTION ca.check_investigation_result();

CREATE TRIGGER run_clock_declaration_append_only BEFORE UPDATE OR DELETE ON ca.run_clock_declaration
  FOR EACH ROW EXECUTE FUNCTION ca.forbid_mutation();
CREATE TRIGGER run_clock_declaration_no_truncate BEFORE TRUNCATE ON ca.run_clock_declaration
  FOR EACH STATEMENT EXECUTE FUNCTION ca.forbid_mutation();
CREATE TRIGGER investigation_result_append_only BEFORE UPDATE OR DELETE ON ca.investigation_result
  FOR EACH ROW EXECUTE FUNCTION ca.forbid_mutation();
CREATE TRIGGER investigation_result_no_truncate BEFORE TRUNCATE ON ca.investigation_result
  FOR EACH STATEMENT EXECUTE FUNCTION ca.forbid_mutation();

-- Engine read path: sealed runs only, as for 0003.
CREATE VIEW ca.sealed_clock_declaration WITH (security_barrier) AS
  SELECT d.run_id, d.declaration_digest, d.declaration_bytes
  FROM ca.run_clock_declaration d JOIN ca.run r ON r.run_id = d.run_id
  WHERE r.state = 'sealed';

CREATE VIEW ca.sealed_investigation_result WITH (security_barrier) AS
  SELECT x.run_id, x.investigation_id, x.plan_digest, x.manifest_digest, x.clock_declaration_digest,
         x.contract_version, x.result_digest, x.engine_version, x.catalog_version, x.timeline_rules_version,
         x.outcome_status, x.result_bytes, x.result_bytes_sha256
  FROM ca.investigation_result x JOIN ca.run r ON r.run_id = x.run_id
  WHERE r.state = 'sealed';

-- Grants (least privilege).
GRANT SELECT, INSERT ON ca.run_clock_declaration TO ca_planner;
GRANT SELECT ON ca.sealed_clock_declaration, ca.sealed_investigation_result TO ca_engine;
GRANT USAGE ON SCHEMA ca TO ca_result_writer;
GRANT SELECT ON ca.data_classification, ca.contract_pin TO ca_result_writer;
GRANT SELECT, INSERT ON ca.investigation_result TO ca_result_writer;
