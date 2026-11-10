-- CA-P2-005a (provisional): read path for the deterministic engine.
-- ca_engine sees only runs in state 'sealed', and only through these views. It has no grant on
-- any base table, cannot see collecting, sealing or failed runs, and its database default is
-- read-only transactions (bootstrap). The design allowed the engine to run as ca_reader "or as a
-- dedicated engine role with the same reads"; ca_reader must not read record_bytes, which the
-- engine needs to re-verify evidence, so a dedicated role is used.
-- Views run with their owner's (ca_owner) privileges; security_barrier keeps the sealed-state
-- filter ahead of any caller-supplied predicate. ca_engine cannot create functions anywhere.

CREATE VIEW ca.sealed_run WITH (security_barrier) AS
  SELECT r.run_id, r.investigation_id, r.plan_digest, f.manifest_digest, p.registry_digest
  FROM ca.run r
  JOIN ca.frozen_input f ON f.run_id = r.run_id
  JOIN ca.run_plan p ON p.plan_digest = r.plan_digest
  WHERE r.state = 'sealed';

CREATE VIEW ca.sealed_run_configuration WITH (security_barrier) AS
  SELECT r.run_id, p.record_bytes AS plan_bytes, s.record_bytes AS registry_bytes
  FROM ca.run r
  JOIN ca.run_plan p ON p.plan_digest = r.plan_digest
  JOIN ca.registry_snapshot s ON s.registry_digest = p.registry_digest
  WHERE r.state = 'sealed';

CREATE VIEW ca.sealed_manifest_root WITH (security_barrier) AS
  SELECT f.run_id, f.manifest_digest, f.root_bytes
  FROM ca.frozen_input f JOIN ca.run r ON r.run_id = f.run_id
  WHERE r.state = 'sealed';

CREATE VIEW ca.sealed_manifest_page WITH (security_barrier) AS
  SELECT m.run_id, m.collection, m.page_index, m.page_bytes
  FROM ca.manifest_page m JOIN ca.run r ON r.run_id = m.run_id
  WHERE r.state = 'sealed';

-- Exactly the sealed members of a run (ca.run_evidence), never other variants of an identity.
CREATE VIEW ca.sealed_evidence_record WITH (security_barrier) AS
  SELECT e.run_id, e.evidence_id, e.content_digest, v.record_bytes
  FROM ca.run_evidence e
  JOIN ca.run r ON r.run_id = e.run_id
  JOIN ca.evidence_version v ON v.evidence_id = e.evidence_id AND v.content_digest = e.content_digest
  WHERE r.state = 'sealed';

GRANT USAGE ON SCHEMA ca TO ca_engine;
GRANT SELECT ON ca.data_classification, ca.contract_pin, ca.sealed_run, ca.sealed_run_configuration,
  ca.sealed_manifest_root, ca.sealed_manifest_page, ca.sealed_evidence_record TO ca_engine;
