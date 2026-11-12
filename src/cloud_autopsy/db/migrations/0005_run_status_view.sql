-- CA-P2-004b (provisional): read-only run lifecycle status for the local API.
-- Additive and forward-only: no table, column, trigger or earlier grant changes.
--
-- ca_engine (the API's role: read-only transactions, no base-table grants) may read the lifecycle
-- state of a run, and nothing else about an unsealed run. The view exposes exactly:
--   run_id          the run
--   state           collecting, sealing, sealed, failed or cancelled
--   failure_reason  for failed runs only: a fixed code of the form seal:<code>, or 'unspecified'
--                   when the stored text is not such a code (so free text is never exposed)
--   lease_expired   for sealing runs only: whether the current lease has expired
-- It never exposes evidence, plans, lease owners (worker identities), timestamps, state versions
-- or exception messages. The API restricts every lookup to run IDs named in the caller's grant;
-- the database cannot know the caller, so this view is not a listing endpoint by itself.
-- The view runs with its owner's (ca_owner) privileges; security_barrier keeps its projection
-- ahead of any caller-supplied predicate.

CREATE VIEW ca.run_status WITH (security_barrier) AS
  SELECT r.run_id,
         r.state::text AS state,
         CASE WHEN r.state = 'failed' THEN
           CASE WHEN r.failure_reason ~ '^seal:[a-z][a-z0-9_]{0,63}$' THEN r.failure_reason ELSE 'unspecified' END
         END AS failure_reason,
         CASE WHEN r.state = 'sealing' THEN r.lease_expires_at IS NULL OR r.lease_expires_at <= now() END
           AS lease_expired
  FROM ca.run r;

REVOKE ALL ON ca.run_status FROM PUBLIC;
GRANT SELECT ON ca.run_status TO ca_engine;
