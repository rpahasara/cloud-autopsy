-- CA-P2-003b-1 review fix (provisional). Database-enforced intake freeze: run-scoped ingest rows
-- may be inserted only while their run is collecting. Before this, the rule lived only in the
-- Python ingest path, so ca_ingest could skip ca.ingest_lock_run and add batches, delivery
-- receipts or delivered evidence to a sealing or sealed run with direct INSERTs.
-- The check takes FOR SHARE on the run row, so it also serializes against the sealer's phase A
-- (FOR UPDATE): an insert either commits before the run leaves collecting or is refused after.
-- SECURITY DEFINER because row locks need UPDATE on ca.run, which ca_ingest does not hold (I7).
-- Trigger firing does not check EXECUTE, so EXECUTE is granted to no role.

CREATE FUNCTION ca.check_ingest_run_collecting() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  current_state ca.run_state;
BEGIN
  SELECT r.state INTO current_state FROM ca.run r WHERE r.run_id = NEW.run_id FOR SHARE;
  IF current_state IS DISTINCT FROM 'collecting'::ca.run_state THEN
    RAISE EXCEPTION 'ingest rows may only be added while their run is collecting'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION ca.check_ingest_run_collecting() FROM PUBLIC;

CREATE TRIGGER acquisition_batch_requires_collecting BEFORE INSERT ON ca.acquisition_batch
  FOR EACH ROW EXECUTE FUNCTION ca.check_ingest_run_collecting();
CREATE TRIGGER batch_delivery_requires_collecting BEFORE INSERT ON ca.batch_delivery
  FOR EACH ROW EXECUTE FUNCTION ca.check_ingest_run_collecting();
CREATE TRIGGER run_delivered_evidence_requires_collecting BEFORE INSERT ON ca.run_delivered_evidence
  FOR EACH ROW EXECUTE FUNCTION ca.check_ingest_run_collecting();
CREATE TRIGGER batch_evidence_requires_collecting BEFORE INSERT ON ca.batch_evidence
  FOR EACH ROW EXECUTE FUNCTION ca.check_ingest_run_collecting();
