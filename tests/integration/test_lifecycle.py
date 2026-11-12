"""CA-P2-004b: run lifecycle, R4 recovery and stale-worker fencing against a real PostgreSQL.

- R4: a deterministic seal failure moves the run to ``failed`` with a fixed reason code; it never
  stays ``sealing`` until a lease expires.
- A transient failure (a crashed worker) leaves the run ``sealing``; after the lease expires another
  worker takes over and seals byte-identical output. Lease acquisitions are counted durably in the
  database, so recovery is bounded across process crashes.
- A worker whose lease expired or was taken over can neither publish nor change the run's state.
Synthetic data only.
"""

import threading
import unittest

import _db

if _db.AVAILABLE:
    import _manifest_support as M
    from cloud_autopsy.contracts import errors as E
    from cloud_autopsy.contracts import frozen_input as fi
    from cloud_autopsy.db import results, seal
    from test_postgres import PostgresCase, sqlstate
else:  # keeps the module importable without the driver; every test is skipped
    PostgresCase = unittest.TestCase

TWO = ["configmaps", "deployments"]
NAMES = ["cm-1", "deploy-1", "deploy-2"]


def max_attempts():
    return getattr(seal, "MAX_SEAL_ATTEMPTS", 3)


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class LifecycleTests(PostgresCase):
    def row(self, run_id):
        return tuple(self.auditor.one(
            "SELECT state, state_version, lease_owner, failure_reason FROM ca.run WHERE run_id = CAST(:r AS uuid)",
            r=run_id))

    def fresh_run(self):
        plan = self.plan(TWO)
        run_id, _ = self.run_with(plan, NAMES)
        return plan, run_id

    def crash_after_phase_a(self, run_id, plan, worker, lease_seconds=0):
        """A worker that took the lease and died before publishing (its connection is gone)."""
        db = self.fx.connect("ca_sealer")
        try:
            return seal._phase_a(db, run_id, plan, worker, lease_seconds)
        finally:
            db.close()

    def reference_seal(self):
        plan, run_id = self.fresh_run()
        return seal.seal_run(self.sealer, run_id, plan, M.REGISTRY)

    # --- R4: deterministic failures end in 'failed' ---------------------------------------

    def test_a_deterministic_seal_failure_marks_the_run_failed(self):
        plan, run_id = self.fresh_run()
        real = seal.fi.seal

        def refuse(*a, **k):
            raise fi.ManifestError(E.LIMIT_EXCEEDED, "injected: a plan limit is exceeded at seal time")

        seal.fi.seal = refuse
        try:
            with self.assertRaises(Exception) as ctx:
                seal.seal_run(self.sealer, run_id, plan, M.REGISTRY, worker="det")
        finally:
            seal.fi.seal = real
        state, _, owner, reason = self.row(run_id)
        self.assertEqual(state, "failed", "R4: a deterministic seal failure left the run in " + state)
        self.assertEqual((owner, reason), (None, "seal:limit_exceeded"))
        self.assertEqual(type(ctx.exception).__name__, "SealFailed")
        self.assertEqual(ctx.exception.reason, "seal:limit_exceeded")
        for table in ("frozen_input", "manifest_page", "run_evidence"):
            self.assertEqual(self.count(table, run_id), 0, table)
        # terminal: no worker can reopen it, and it never gets a result
        with self.assertRaises(seal.SealConflict):
            seal.seal_run(self.sealer, run_id, plan, M.REGISTRY, worker="later")
        with self.assertRaises(results.StoredResultUnavailable):
            results.load_verified_result(self.fx.connect("ca_engine"), run_id)

    # --- stale workers are fenced ----------------------------------------------------------

    def test_a_worker_whose_lease_expired_cannot_publish(self):
        plan, run_id = self.fresh_run()
        db = self.fx.connect("ca_sealer")
        version = seal._phase_a(db, run_id, plan, "slow", 0)  # its lease expires at once
        frozen = fi.seal(plan, M.REGISTRY, seal._load_batches(db, run_id))
        with self.assertRaises(seal.SealConflict):
            seal._phase_b(db, run_id, plan, M.REGISTRY, "slow", version, frozen, False)
        self.assertEqual(self.row(run_id)[:2], ("sealing", 1))
        self.assertEqual(self.count("frozen_input", run_id), 0)

    def test_a_taken_over_worker_can_neither_publish_nor_fail_the_run(self):
        plan, run_id = self.fresh_run()
        stale = self.fx.connect("ca_sealer")
        version = seal._phase_a(stale, run_id, plan, "stale", 0)
        frozen = fi.seal(plan, M.REGISTRY, seal._load_batches(stale, run_id))
        new_version = seal._phase_a(self.sealer, run_id, plan, "fresh", 300)  # takeover after expiry
        self.assertEqual(new_version, version + 1)
        with self.assertRaises(seal.SealConflict):
            seal._phase_b(stale, run_id, plan, M.REGISTRY, "stale", version, frozen, False)
        with self.assertRaises(seal.SealConflict):
            seal._mark_failed(stale, run_id, "stale", version, "seal:limit_exceeded")
        self.assertEqual(self.row(run_id), ("sealing", 2, "fresh", None))

    def test_a_live_lease_blocks_other_workers(self):
        plan, run_id = self.fresh_run()
        self.crash_after_phase_a(run_id, plan, "holder", lease_seconds=300)
        with self.assertRaises(seal.SealConflict):
            seal.seal_run(self.sealer, run_id, plan, M.REGISTRY, worker="other")
        self.assertEqual(self.row(run_id)[:3], ("sealing", 1, "holder"))

    # --- transient failures recover, boundedly -------------------------------------------

    def test_a_crash_between_phases_is_recovered_byte_identically(self):
        reference = self.reference_seal()
        plan, run_id = self.fresh_run()
        self.crash_after_phase_a(run_id, plan, "crashed")
        frozen = seal.seal_run(self.sealer, run_id, plan, M.REGISTRY, worker="recovery")
        self.assertEqual((frozen.root_bytes, frozen.page_bytes), (reference.root_bytes, reference.page_bytes))
        self.assertEqual(self.row(run_id), ("sealed", 3, None, None))

    def test_concurrent_recovery_after_expiry_seals_once(self):
        plan, run_id = self.fresh_run()
        self.crash_after_phase_a(run_id, plan, "crashed")
        outcomes, lock, barrier = [], threading.Lock(), threading.Barrier(4)

        def worker(i):
            db = self.fx.connect("ca_sealer")
            barrier.wait(10)
            try:
                seal.seal_run(db, run_id, plan, M.REGISTRY, worker=f"r{i}")
                outcome = "ok"
            except seal.SealConflict:
                outcome = "conflict"
            finally:
                db.close()
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(sorted(outcomes), ["conflict"] * 3 + ["ok"])
        self.assertEqual(self.count("frozen_input", run_id), 1)
        self.assertEqual(self.row(run_id)[0], "sealed")

    def test_recovery_is_bounded_and_counted_durably_across_crashes(self):
        plan, run_id = self.fresh_run()
        for i in range(max_attempts()):  # every attempt crashes; each on its own, closed connection
            self.crash_after_phase_a(run_id, plan, f"crash-{i}")
            self.assertEqual(self.row(run_id)[:2], ("sealing", i + 1))
        with self.assertRaises(Exception) as ctx:
            seal.seal_run(self.sealer, run_id, plan, M.REGISTRY, worker="one-too-many")
        self.assertEqual(self.row(run_id), ("failed", max_attempts() + 1, None, "seal:attempts_exhausted"))
        self.assertEqual(type(ctx.exception).__name__, "SealFailed")
        self.assertEqual(self.count("frozen_input", run_id), 0)


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class RunStatusViewTests(PostgresCase):
    """Migration 0005: ``ca.run_status`` exposes lifecycle metadata only, to ca_engine only."""

    def setUp(self):
        from cloud_autopsy.db import status
        self.status = status
        self.engine = self.fx.connect("ca_engine")
        self.addCleanup(self.engine.close)

    def fresh_run(self):
        plan = self.plan(TWO)
        run_id, _ = self.run_with(plan, NAMES)
        return plan, run_id

    def look(self, run_id):
        found = self.status.load_status(self.engine, run_id)
        return found and found.to_record()

    def test_the_view_shows_each_lifecycle_state_and_nothing_else(self):
        columns = [r[0] for r in self.engine.run(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'ca' AND table_name = 'run_status' "
            "ORDER BY ordinal_position")]
        self.assertEqual(columns, ["run_id", "state", "failure_reason", "lease_expired"])
        plan, collecting = self.fresh_run()
        self.assertEqual(self.look(collecting), {"state": "collecting", "failure_reason": None, "lease_expired": None})
        _, live = self.fresh_run()
        seal._phase_a(self.sealer, live, plan, "secret-worker-name", 300)
        self.assertEqual(self.look(live), {"state": "sealing", "failure_reason": None, "lease_expired": False})
        _, expired = self.fresh_run()
        seal._phase_a(self.sealer, expired, plan, "secret-worker-name", 0)
        self.assertEqual(self.look(expired), {"state": "sealing", "failure_reason": None, "lease_expired": True})
        _, sealed = self.fresh_run()
        seal.seal_run(self.sealer, sealed, plan, M.REGISTRY)
        self.assertEqual(self.look(sealed), {"state": "sealed", "failure_reason": None, "lease_expired": None})
        self.assertIsNone(self.look("00000000-0000-4000-8000-000000000000"))
        # the worker identity never leaves the database through the view
        rows = self.engine.run("SELECT * FROM ca.run_status WHERE run_id = CAST(:r AS uuid)", r=live)
        self.assertNotIn("secret-worker-name", repr(rows))

    def test_free_text_failure_reasons_are_never_exposed(self):
        _, run_id = self.fresh_run()
        self.as_owner("UPDATE ca.run SET state = 'failed', state_version = state_version + 1, "
                      "failure_reason = :f WHERE run_id = CAST(:r AS uuid)",
                      f="Traceback: password=hunter2 at /home/x", r=run_id)
        self.assertEqual(self.look(run_id), {"state": "failed", "failure_reason": "unspecified", "lease_expired": None})

    def test_only_ca_engine_may_read_the_view_and_nothing_else_changed(self):
        from cloud_autopsy.db import bootstrap

        def has(role, priv):  # by OID from pg_class: ca_migrator has no USAGE on schema ca itself
            return self.owner.one(
                "SELECT has_table_privilege(:r, c.oid, :p) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'ca' AND c.relname = 'run_status'", r=role, p=priv)[0]

        readers = [role for role in sorted(bootstrap.ROLES) if has(role, "SELECT")]
        self.assertEqual([r for r in readers if r != "ca_owner"], ["ca_engine"])
        self.assertFalse(has("public", "SELECT"))
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            self.assertFalse(has("ca_engine", priv))
        # ca_engine still has no base-table access: the view is the only lifecycle read path
        self.assertEqual(sqlstate(self.engine.run, "SELECT lease_owner FROM ca.run LIMIT 1"), "42501")


if __name__ == "__main__":
    unittest.main()
