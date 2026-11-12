-- CA-P2-004d review fix (provisional): evidence records per source-registry binding.
-- Additive and forward-only. No existing row is changed; migrations 0001-0006 are unchanged.
--
-- ca.evidence_version is keyed by (evidence_id, content_digest), and its record_bytes keep the bytes
-- of the first delivery. Those bytes carry that delivery's source-binding digest (the registry's
-- query list and clock domains), which is neither identity nor content. A later run observing the
-- same unchanged object through an evolved registry therefore read a record bound to someone else's
-- registry, and could never verify. From this migration, ingest also stores the record as delivered
-- under each binding, and the engine's view returns the record bound to the run's own registry.
-- Runs ingested before this migration have no per-binding rows and read ca.evidence_version exactly
-- as before.

CREATE TABLE ca.evidence_binding_record (
  evidence_id            ca.digest NOT NULL,
  content_digest         ca.digest NOT NULL,
  source_binding_digest  ca.digest NOT NULL,
  record_bytes           bytea NOT NULL CHECK (octet_length(record_bytes) <= 1048576),
  PRIMARY KEY (evidence_id, content_digest, source_binding_digest),
  FOREIGN KEY (evidence_id, content_digest) REFERENCES ca.evidence_version (evidence_id, content_digest)
);
CREATE TRIGGER evidence_binding_record_append_only BEFORE UPDATE OR DELETE ON ca.evidence_binding_record
  FOR EACH ROW EXECUTE FUNCTION ca.forbid_mutation();
CREATE TRIGGER evidence_binding_record_no_truncate BEFORE TRUNCATE ON ca.evidence_binding_record
  FOR EACH STATEMENT EXECUTE FUNCTION ca.forbid_mutation();

-- Same columns as in 0003, now choosing the record bound to the run's own registry source; it falls
-- back to the first-stored record only when no per-binding row exists (runs ingested before 0007).
CREATE OR REPLACE VIEW ca.sealed_evidence_record WITH (security_barrier) AS
  SELECT e.run_id, e.evidence_id, e.content_digest, COALESCE(b.record_bytes, v.record_bytes) AS record_bytes
  FROM ca.run_evidence e
  JOIN ca.run r ON r.run_id = e.run_id
  JOIN ca.run_plan p ON p.plan_digest = r.plan_digest
  JOIN ca.evidence_identity i ON i.evidence_id = e.evidence_id
  JOIN ca.source_binding s ON s.registry_digest = p.registry_digest AND s.source_id = i.source_id
  JOIN ca.evidence_version v ON v.evidence_id = e.evidence_id AND v.content_digest = e.content_digest
  LEFT JOIN ca.evidence_binding_record b ON b.evidence_id = e.evidence_id AND b.content_digest = e.content_digest
    AND b.source_binding_digest = s.binding_digest
  WHERE r.state = 'sealed';

GRANT INSERT ON ca.evidence_binding_record TO ca_ingest;
GRANT SELECT ON ca.evidence_binding_record TO ca_sealer;
