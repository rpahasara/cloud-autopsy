"""CA-P2-005a end-to-end tests against a real disposable PostgreSQL (synthetic data only).

Persist -> seal -> read as ca_engine -> investigate -> verify, for every synthetic variant, in
canonical and permuted delivery order, compared byte for byte with the database-free path.
Expected outcomes are developer-authored regression expectations, not independent evaluation.
"""

import unittest

import _db

if _db.AVAILABLE:
    from cloud_autopsy.app import pipeline
    from cloud_autopsy.db import ingest, read, seal
    from cloud_autopsy.db.adapter import DbError
    from cloud_autopsy.synthetic import scenario_001 as scenario

EXPECTED = {"config-cause": ("resolved", "config_limit_reduction"),
            "configmap-unavailable": ("abstained", None), "configmap-conflict": ("abstained", None),
            "clock-unknown": ("abstained", None), "symptom-before-change": ("abstained", None),
            "no-symptom": ("abstained", None)}


def sqlstate(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except DbError as exc:
        return exc.sqlstate
    return None


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        cls.roles = {r: cls.fx.connect(r) for r in ("ca_planner", "ca_ingest", "ca_sealer", "ca_engine")}
        cls.engine = cls.roles["ca_engine"]

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def test_every_variant_end_to_end_is_permutation_and_replay_stable(self):
        for variant, (status, mechanism) in EXPECTED.items():
            with self.subTest(variant=variant):
                domains = scenario.clock_domain_records(variant)
                run_a, manifest_a, _ = pipeline.persist_and_seal(self.roles, variant)
                run_b, manifest_b, outcomes_b = pipeline.persist_and_seal(self.roles, variant, seed=7)
                self.assertIn(ingest.DUPLICATE, outcomes_b)  # redeliveries were exercised
                res, bytes_a = pipeline.investigate_run(self.engine, run_a, domains)
                _, bytes_b = pipeline.investigate_run(self.engine, run_b, domains)
                _, replay = pipeline.investigate_run(self.engine, run_a, domains)
                _, offline = pipeline.offline_result(variant)
                self.assertEqual(manifest_a, manifest_b)
                self.assertEqual(bytes_a, bytes_b)
                self.assertEqual(bytes_a, replay)
                self.assertEqual(bytes_a, offline)
                self.assertEqual((res["outcome"]["status"], res["outcome"]["mechanism"]), (status, mechanism))
                self.assertEqual(res["inputs"]["manifest_digest"], manifest_a)

    def test_conflicting_redelivery_is_retained_and_reported(self):
        run_id, _, outcomes = pipeline.persist_and_seal(self.roles, "configmap-conflict")
        self.assertIn(ingest.CONFLICTING_VARIANT, outcomes)
        res, _ = pipeline.investigate_run(self.engine, run_id, scenario.clock_domain_records("configmap-conflict"))
        self.assertIn("batch_conflict", {r for g in res["gaps"] for r in g["reasons"]})
        self.assertEqual(res["outcome"]["status"], "abstained")

    def test_engine_reads_only_sealed_runs(self):
        plan = scenario.plan("config-cause")
        ingest.register_registry(self.roles["ca_planner"], scenario.registry())
        ingest.register_plan(self.roles["ca_planner"], plan)
        collecting = ingest.create_run(self.roles["ca_planner"], plan)
        with self.assertRaises(read.SealedRunUnavailable):
            read.load_sealed_run(self.engine, collecting)
        # A failed publication leaves the run sealing: still invisible to the engine.
        failing = ingest.create_run(self.roles["ca_planner"], plan)
        for record in scenario.batches("config-cause"):
            ingest.ingest_batch(self.roles["ca_ingest"], failing, record, plan, scenario.registry())
        with self.assertRaises(seal.InjectedFailure):
            seal.seal_run(self.roles["ca_sealer"], failing, plan, scenario.registry(), fail_before_commit=True)
        with self.assertRaises(read.SealedRunUnavailable):
            read.load_sealed_run(self.engine, failing)

    def test_engine_role_has_no_base_table_or_write_access(self):
        self.assertEqual(self.engine.one("SHOW default_transaction_read_only")[0], "on")
        for table in ("run", "evidence_version", "acquisition_batch", "frozen_input", "manifest_page", "run_plan",
                      "registry_snapshot", "run_evidence", "investigation"):
            with self.subTest(table=table):
                self.assertEqual(sqlstate(self.engine.run, f"SELECT 1 FROM ca.{table} LIMIT 1"), "42501")
        # No write privilege on any view it can read (checked directly, independent of updatability).
        writable = self.engine.run(
            "SELECT c.relname, p.priv FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) AS p(priv) "
            "WHERE n.nspname = 'ca' AND has_table_privilege('ca_engine', c.oid, p.priv)")
        self.assertEqual(writable, [])
        # Attempts are refused: insufficient privilege, read-only transaction, or (for join views)
        # not insertable at all (55000) -- each is a refusal before any row is written.
        for sql in ("INSERT INTO ca.sealed_evidence_record (run_id, evidence_id, content_digest, record_bytes) "
                    "VALUES (gen_random_uuid(), 'x', 'x', 'x')",
                    "SET ROLE ca_owner", "CREATE TABLE ca.rogue (x int)", "CREATE TEMP TABLE rogue (x int)",
                    "SELECT ca.ingest_lock_run(gen_random_uuid())"):
            with self.subTest(sql=sql[:40]):
                self.assertIn(sqlstate(self.engine.run, sql), {"42501", "25006", "55000"})


if __name__ == "__main__":
    unittest.main()
