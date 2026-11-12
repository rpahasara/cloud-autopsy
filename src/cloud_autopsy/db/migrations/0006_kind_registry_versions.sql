-- CA-P2-004d (provisional): one database holds runs under more than one observation-kind registry.
-- Additive and forward-only. Migrations 0001-0005, ca.contract_pin and every stored row are unchanged.
--
-- ca.contract_pin keeps exactly one baseline version per contract (observation kinds 0.1). This
-- table lists the *additional* versions a plan may pin; a run plan pins one whole profile, and its
-- evidence is decoded under exactly that profile. Stored 0.1 evidence is never re-labelled: a
-- record carries the registry version that introduced its kind, so a 0.1 kind is byte-identical
-- under a 0.1 or a 0.2 plan and its deduplicated ca.evidence_version row is shared unchanged.

CREATE TABLE ca.contract_version_supported (
  contract_name     text NOT NULL REFERENCES ca.contract_pin (contract_name),
  contract_version  ca.contract_version NOT NULL CHECK (contract_version LIKE '%-provisional'),
  PRIMARY KEY (contract_name, contract_version)
);
INSERT INTO ca.contract_version_supported (contract_name, contract_version) VALUES
  ('observation-kinds', 'ca-observation-kinds/0.2-provisional');

CREATE TRIGGER contract_version_supported_append_only BEFORE UPDATE OR DELETE ON ca.contract_version_supported
  FOR EACH ROW EXECUTE FUNCTION ca.forbid_mutation();
CREATE TRIGGER contract_version_supported_no_truncate BEFORE TRUNCATE ON ca.contract_version_supported
  FOR EACH STATEMENT EXECUTE FUNCTION ca.forbid_mutation();

-- Defense in depth: a plan row may only pin versions this database supports (the baseline pin or an
-- additional supported version), checked from the stored plan bytes themselves. Runs as the
-- invoking role (ca_planner), which may read both tables; not SECURITY DEFINER.
CREATE FUNCTION ca.check_plan_contract_versions() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  pinned jsonb;
  item record;
BEGIN
  pinned := convert_from(NEW.record_bytes, 'UTF8')::jsonb -> 'contract_versions';
  IF pinned IS NULL OR jsonb_typeof(pinned) <> 'object' THEN
    RAISE EXCEPTION 'a plan must pin its contract versions' USING ERRCODE = 'check_violation';
  END IF;
  FOR item IN SELECT key, value FROM jsonb_each(pinned) LOOP
    IF jsonb_typeof(item.value) <> 'string' OR NOT (
         EXISTS (SELECT 1 FROM ca.contract_pin p
                 WHERE p.contract_name = item.key AND p.contract_version::text = item.value #>> '{}')
      OR EXISTS (SELECT 1 FROM ca.contract_version_supported s
                 WHERE s.contract_name = item.key AND s.contract_version::text = item.value #>> '{}')) THEN
      RAISE EXCEPTION 'a plan pins a contract version this database does not support'
        USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION ca.check_plan_contract_versions() FROM PUBLIC;
CREATE TRIGGER run_plan_contract_versions BEFORE INSERT ON ca.run_plan
  FOR EACH ROW EXECUTE FUNCTION ca.check_plan_contract_versions();

GRANT SELECT ON ca.contract_version_supported TO ca_planner, ca_ingest, ca_sealer, ca_reader, ca_engine,
  ca_result_writer;
