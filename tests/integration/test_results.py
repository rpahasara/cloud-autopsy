"""CA-P2-006a: frozen clock declarations and immutable investigation results (real PostgreSQL).

Synthetic data only. Tampering is simulated with the container's bootstrap superuser, the only
identity that can bypass the append-only triggers (``session_replication_role = replica``);
it stands for an attacker with direct database access. Expected outcomes are developer-authored
regression expectations, not independent evaluation.
"""

import hashlib
import threading
import unittest

import _db

if _db.AVAILABLE:
    from cloud_autopsy.app import pipeline
    from cloud_autopsy.contracts import canonical
    from cloud_autopsy.db import ingest, results, seal
    from cloud_autopsy.db.adapter import DbError
    from cloud_autopsy.engine import RESULT_DIGEST_ALGORITHM, clocks, inputs
    from cloud_autopsy.synthetic import scenario_001 as scenario

WRITERS = 6


def sqlstate(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except DbError as exc:
        return exc.sqlstate
    return None


def forge(raw, mutate):
    """A self-consistent but different result: mutate the document and recompute its digest."""
    doc = canonical.loads(raw)
    body = {k: v for k, v in doc.items() if k != "result_digest"}
    mutate(body)
    body["result_digest"] = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
    return canonical.canonical_bytes(body)


def add_reason(body):
    body["outcome"]["reasons"] = sorted(set(body["outcome"]["reasons"]) | {"forged_reason"})


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class ResultStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        cls.roles = {r: cls.fx.connect(r) for r in ("ca_planner", "ca_ingest", "ca_sealer", "ca_engine",
                                                    "ca_result_writer", "ca_reader")}
        cls.engine, cls.writer = cls.roles["ca_engine"], cls.roles["ca_result_writer"]
        cls.owner = cls.fx.connect("ca_migrator")  # privileges only through SET ROLE ca_owner

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def sealed(self, variant="config-cause", seed=None):
        run_id, _, _ = pipeline.persist_and_seal(self.roles, variant, seed=seed)
        return run_id

    def as_owner(self, sql, **params):
        with self.owner.transaction():
            self.owner.run("SET LOCAL ROLE ca_owner")
            return self.owner.run(sql, **params)

    def tamper(self, sql, **params):
        """Bypass every trigger (foreign keys and append-only) as the bootstrap superuser."""
        admin = _db.superuser(self.fx.name)
        try:
            with admin.transaction():
                admin.run("SET LOCAL session_replication_role = replica")
                admin.run(sql, **params)
        finally:
            admin.close()

    def stored_count(self, run_id):
        return self.engine.one("SELECT count(*) FROM ca.sealed_investigation_result WHERE run_id = CAST(:r AS uuid)",
                               r=run_id)[0]

    def assert_invalid_on_read(self, run_id, code):
        fresh = self.fx.connect("ca_engine")
        with self.assertRaises(results.StoredResultInvalid) as caught:
            results.load_verified_result(fresh, run_id)
        self.assertEqual(caught.exception.code, code)

    # --- storage and replay -----------------------------------------------------------------

    def test_all_six_variants_store_once_and_replay_byte_identically_on_a_new_connection(self):
        for variant in scenario.VARIANTS:
            with self.subTest(variant=variant):
                run_id = self.sealed(variant)
                outcome, investigation = pipeline.record_result(self.engine, self.writer, run_id)
                self.assertEqual(outcome, results.STORED)
                fresh = self.fx.connect("ca_engine")
                verified = results.load_verified_result(fresh, run_id)
                _, offline = pipeline.offline_result(variant)
                self.assertEqual(verified.result_bytes, investigation.result_bytes)
                self.assertEqual(verified.result_bytes, offline)  # stored == replayed == database-free
                self.assertEqual(verified.result_digest, investigation.result["result_digest"])
                self.assertEqual(verified.result["inputs"]["clock_declaration_digest"],
                                 clocks.declare(scenario.registry(), scenario.clock_domain_records(variant)).digest)

    def test_identical_retry_is_idempotent(self):
        run_id = self.sealed()
        first, investigation = pipeline.record_result(self.engine, self.writer, run_id)
        again = results.store_result(self.writer, run_id, investigation.investigation_id, investigation.result_bytes)
        self.assertEqual((first, again), (results.STORED, results.IDENTICAL))
        self.assertEqual(self.stored_count(run_id), 1)

    def test_concurrent_writers_store_exactly_once(self):
        run_id = self.sealed()
        investigation = results.investigate(self.engine, run_id)
        writers = [self.fx.connect("ca_result_writer") for _ in range(WRITERS)]
        barrier, outcomes, errors = threading.Barrier(WRITERS), [], []

        def write(db):
            try:
                barrier.wait()
                outcomes.append(results.store_result(db, run_id, investigation.investigation_id,
                                                     investigation.result_bytes))
            except Exception as exc:  # noqa: BLE001 -- surfaced by the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(db,)) for db in writers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(outcomes), sorted([results.STORED] + [results.IDENTICAL] * (WRITERS - 1)))
        self.assertEqual(self.stored_count(run_id), 1)
        self.assertEqual(results.load_verified_result(self.engine, run_id).result_bytes, investigation.result_bytes)

    def test_conflicting_result_is_refused_and_the_first_stays_authoritative(self):
        run_id = self.sealed()
        _, investigation = pipeline.record_result(self.engine, self.writer, run_id)
        forged = forge(investigation.result_bytes, add_reason)
        with self.assertRaises(results.ResultConflict):
            results.store_result(self.writer, run_id, investigation.investigation_id, forged)
        self.assertEqual(results.load_verified_result(self.engine, run_id).result_bytes, investigation.result_bytes)

    def test_a_forged_first_result_is_stored_but_never_trusted(self):
        # The database checks bindings, not the reasoning: only re-execution can. A self-consistent
        # forgery written first is refused on every read.
        run_id = self.sealed()
        investigation = results.investigate(self.engine, run_id)
        forged = forge(investigation.result_bytes, add_reason)
        self.assertEqual(results.store_result(self.writer, run_id, investigation.investigation_id, forged),
                         results.STORED)
        self.assert_invalid_on_read(run_id, "replay_mismatch")

    def test_transaction_rollback_leaves_no_result(self):
        run_id = self.sealed()
        investigation = results.investigate(self.engine, run_id)
        row = results.result_row(run_id, investigation.investigation_id, investigation.result_bytes)
        with self.assertRaises(RuntimeError):
            with self.writer.transaction():
                self.assertTrue(self.writer.run(results.INSERT_RESULT, **row))
                raise RuntimeError("abort after the insert, before commit")
        self.assertEqual(self.stored_count(run_id), 0)
        self.assertEqual(results.store_result(self.writer, run_id, investigation.investigation_id,
                                              investigation.result_bytes), results.STORED)

    # --- same-run bindings ------------------------------------------------------------------

    def test_cross_run_references_are_refused_by_the_database(self):
        run_a, run_b = self.sealed("config-cause"), self.sealed("no-symptom")
        inv_a, inv_b = results.investigate(self.engine, run_a), results.investigate(self.engine, run_b)
        # B's result (B's plan, manifest and clock declaration) stored under run A.
        self.assertEqual(sqlstate(results.store_result, self.writer, run_a, inv_a.investigation_id,
                                  inv_b.result_bytes), "23503")
        # A's own result with another run's investigation ID.
        self.assertEqual(sqlstate(results.store_result, self.writer, run_a, inv_b.investigation_id,
                                  inv_a.result_bytes), "23503")
        # Columns that disagree with the bytes they describe.
        row = results.result_row(run_a, inv_a.investigation_id, inv_a.result_bytes)
        row["m"] = inv_b.result["inputs"]["manifest_digest"]
        self.assertEqual(sqlstate(self.writer.run, results.INSERT_RESULT, **row), "23514")
        self.assertEqual(self.stored_count(run_a), 0)

    def test_results_only_for_sealed_runs(self):
        plan, registry = scenario.plan("config-cause"), scenario.registry()
        run_id = ingest.create_run(self.roles["ca_planner"], plan)
        results.declare_clocks(self.roles["ca_planner"], run_id, plan, registry,
                               scenario.clock_domain_records("config-cause"))
        donor = results.investigate(self.engine, self.sealed())
        row = results.result_row(run_id, None, donor.result_bytes)
        row["i"] = self.roles["ca_planner"].one("SELECT CAST(investigation_id AS text) FROM ca.run "
                                                "WHERE run_id = CAST(:r AS uuid)", r=run_id)[0]
        self.assertEqual(sqlstate(self.writer.run, results.INSERT_RESULT, **row), "23514")

    # --- clock declarations -----------------------------------------------------------------

    def test_clock_declaration_is_bound_once_while_collecting(self):
        plan, registry = scenario.plan("config-cause"), scenario.registry()
        planner = self.roles["ca_planner"]
        domains = scenario.clock_domain_records("config-cause")
        run_id = ingest.create_run(planner, plan)
        self.assertEqual(results.declare_clocks(planner, run_id, plan, registry, domains)[0], results.STORED)
        self.assertEqual(results.declare_clocks(planner, run_id, plan, registry, domains)[0], results.IDENTICAL)
        altered = [dict(d, offset_ms=d["offset_ms"] + 1) if d["clock_domain_id"] == "node-a" else d for d in domains]
        with self.assertRaises(results.ClockDeclarationConflict):
            results.declare_clocks(planner, run_id, plan, registry, altered)
        # Never after the run leaves collecting.
        late = ingest.create_run(planner, plan)
        for record in scenario.batches("config-cause"):
            ingest.ingest_batch(self.roles["ca_ingest"], late, record, plan, registry)
        seal.seal_run(self.roles["ca_sealer"], late, plan, registry)
        self.assertEqual(sqlstate(results.declare_clocks, planner, late, plan, registry, domains), "23514")
        with self.assertRaises(inputs.InputError) as caught:  # and the engine refuses a run without one
            results.investigate(self.engine, late)
        self.assertEqual(caught.exception.code, "clock_declaration_missing")

    def test_database_refuses_incomplete_mismatched_or_inconsistent_declarations(self):
        plan, registry = scenario.plan("config-cause"), scenario.registry()
        planner = self.roles["ca_planner"]
        run_id = ingest.create_run(planner, plan)
        sql = ("INSERT INTO ca.run_clock_declaration (run_id, plan_digest, registry_digest, contract_version, "
               "declaration_digest, declaration_bytes) VALUES (CAST(:r AS uuid), :p, :g, :v, :d, :b)")

        def doc_bytes(domains, registry_digest=registry.digest):
            return canonical.canonical_bytes({"contract_version": clocks.CLOCK_DECLARATION_VERSION,
                                              "registry_digest": registry_digest, "clock_domains": domains})

        def attempt(raw, digest=None, registry_digest=registry.digest):
            digest = digest or f"{clocks.CLOCK_DECLARATION_ALGORITHM}:{hashlib.sha256(raw).hexdigest()}"
            return sqlstate(planner.run, sql, r=run_id, p=plan.digest, g=registry_digest,
                            v=clocks.CLOCK_DECLARATION_VERSION, d=digest, b=raw)

        domains = scenario.clock_domain_records("config-cause")
        self.assertEqual(attempt(doc_bytes(domains[1:])), "23514")                  # missing
        self.assertEqual(attempt(doc_bytes(domains + domains[:1])), "23514")        # duplicated
        stray = dict(domains[0], clock_domain_id="node-z")
        self.assertEqual(attempt(doc_bytes(domains + [stray])), "23514")            # unregistered
        good = doc_bytes(domains)
        self.assertEqual(attempt(good, digest="x" + "0" * 10), "23514")             # digest is not the bytes'
        other = canonical.canonical_bytes({"contract_version": clocks.CLOCK_DECLARATION_VERSION,
                                           "registry_digest": registry.digest.replace("a", "b", 1),
                                           "clock_domains": domains})
        self.assertEqual(attempt(other), "23514")                                   # fields disagree with columns
        self.assertIsNotNone(attempt(good, registry_digest=registry.digest.replace("a", "b", 1)))  # wrong registry
        self.assertIsNone(attempt(good))

    def test_altered_clock_declaration_is_detected_on_read(self):
        run_id = self.sealed()
        pipeline.record_result(self.engine, self.writer, run_id)
        stored = self.engine.one("SELECT declaration_bytes FROM ca.sealed_clock_declaration "
                                 "WHERE run_id = CAST(:r AS uuid)", r=run_id)[0]
        doc = canonical.loads(bytes(stored))
        for d in doc["clock_domains"]:
            if d["clock_domain_id"] == "node-a":
                d["offset_uncertainty_ms"] = 120_000  # widen the clock: changes every node-a ordering
        altered = canonical.canonical_bytes(doc)
        # With triggers active even the superuser cannot update it (append-only) ...
        admin = _db.superuser(self.fx.name)
        try:
            self.assertEqual(sqlstate(admin.run, "UPDATE ca.run_clock_declaration SET declaration_bytes = :b "
                                      "WHERE run_id = CAST(:r AS uuid)", b=altered, r=run_id), "42501")
        finally:
            admin.close()
        # ... with triggers bypassed, bytes that no longer match the recorded digest fail the CHECK ...
        self.assertEqual(sqlstate(self.tamper, "UPDATE ca.run_clock_declaration SET declaration_bytes = :b "
                                  "WHERE run_id = CAST(:r AS uuid)", b=altered, r=run_id), "23514")
        # ... and a consistent replacement (bytes and digest) made with every trigger bypassed is
        # caught on read: the result no longer matches the run's clock declaration.
        self.tamper("UPDATE ca.run_clock_declaration SET declaration_bytes = :b, declaration_digest = :d "
                    "WHERE run_id = CAST(:r AS uuid)", b=altered, r=run_id,
                    d=f"{clocks.CLOCK_DECLARATION_ALGORITHM}:{hashlib.sha256(altered).hexdigest()}")
        self.assert_invalid_on_read(run_id, "clock_declaration_mismatch")

    # --- tampering ----------------------------------------------------------------------------

    def test_tampered_stored_results_are_refused_on_read(self):
        def stored_run():
            run_id = self.sealed()
            _, investigation = pipeline.record_result(self.engine, self.writer, run_id)
            return run_id, investigation.result_bytes

        # Bytes changed without their SHA-256: refused by the database CHECK even with triggers bypassed.
        run_id, raw = stored_run()
        self.assertEqual(sqlstate(self.tamper, "UPDATE ca.investigation_result SET result_bytes = :b "
                                  "WHERE run_id = CAST(:r AS uuid)", b=raw + b" ", r=run_id), "23514")

        # A self-consistent forgery (digest, SHA-256 and columns all recomputed): replay refuses it.
        run_id, raw = stored_run()
        forged = forge(raw, add_reason)
        doc = canonical.loads(forged)
        self.tamper("UPDATE ca.investigation_result SET result_bytes = :b, result_bytes_sha256 = :h, "
                    "result_digest = :d WHERE run_id = CAST(:r AS uuid)", b=forged,
                    h=hashlib.sha256(forged).hexdigest(), d=doc["result_digest"], r=run_id)
        self.assert_invalid_on_read(run_id, "replay_mismatch")

        # Bytes edited without recomputing the document digest.
        run_id, raw = stored_run()
        doc = canonical.loads(raw)
        doc["outcome"]["reasons"] = ["edited"]
        edited = canonical.canonical_bytes(doc)
        self.tamper("UPDATE ca.investigation_result SET result_bytes = :b, result_bytes_sha256 = :h "
                    "WHERE run_id = CAST(:r AS uuid)", b=edited, h=hashlib.sha256(edited).hexdigest(), r=run_id)
        self.assert_invalid_on_read(run_id, "result_digest_mismatch")

        # A column rewritten to point at another run's manifest.
        run_id, raw = stored_run()
        other = results.investigate(self.engine, self.sealed("no-symptom"))
        self.tamper("UPDATE ca.investigation_result SET manifest_digest = :m WHERE run_id = CAST(:r AS uuid)",
                    m=other.result["inputs"]["manifest_digest"], r=run_id)
        self.assert_invalid_on_read(run_id, "result_columns_mismatch")

        # Another run's whole, valid result moved under this run.
        run_id, _ = stored_run()
        donor = other.result_bytes
        doc = canonical.loads(donor)
        self.tamper("UPDATE ca.investigation_result SET result_bytes = :b, result_bytes_sha256 = :h, "
                    "result_digest = :d, plan_digest = :p, manifest_digest = :m, outcome_status = :o "
                    "WHERE run_id = CAST(:r AS uuid)", b=donor, h=hashlib.sha256(donor).hexdigest(),
                    d=doc["result_digest"], p=doc["inputs"]["plan_digest"], m=doc["inputs"]["manifest_digest"],
                    o=doc["outcome"]["status"], r=run_id)
        self.assert_invalid_on_read(run_id, "result_binding_mismatch")

    # --- privileges ---------------------------------------------------------------------------

    def test_write_once_and_least_privilege(self):
        run_id = self.sealed()
        pipeline.record_result(self.engine, self.writer, run_id)
        writable = lambda role: [tuple(r) for r in self.owner.run(  # noqa: E731
            "SELECT c.relname, p.priv FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) AS p(priv) "
            "WHERE n.nspname = 'ca' AND has_table_privilege(:r, c.oid, p.priv) ORDER BY 1, 2", r=role)]
        self.assertEqual(writable("ca_result_writer"), [("investigation_result", "INSERT")])
        self.assertEqual(writable("ca_engine"), [])
        self.assertEqual(writable("ca_reader"), [])
        self.assertIn(("run_clock_declaration", "INSERT"), writable("ca_planner"))
        self.assertNotIn(("investigation_result", "INSERT"), writable("ca_planner"))
        for role, sql in (("ca_result_writer", "UPDATE ca.investigation_result SET outcome_status = 'resolved'"),
                          ("ca_result_writer", "DELETE FROM ca.investigation_result"),
                          ("ca_result_writer", "SELECT 1 FROM ca.run"),
                          ("ca_planner", "UPDATE ca.run_clock_declaration SET plan_digest = plan_digest"),
                          ("ca_reader", "SELECT 1 FROM ca.investigation_result"),
                          ("ca_engine", "DELETE FROM ca.sealed_investigation_result")):
            with self.subTest(role=role, sql=sql[:40]):
                self.assertIn(sqlstate(self.roles[role].run, sql), {"42501", "25006"})
        # Even the schema owner cannot rewrite or remove a stored result or declaration.
        for sql in ("UPDATE ca.investigation_result SET outcome_status = outcome_status WHERE run_id = CAST(:r AS uuid)",
                    "DELETE FROM ca.investigation_result WHERE run_id = CAST(:r AS uuid)",
                    "DELETE FROM ca.run_clock_declaration WHERE run_id = CAST(:r AS uuid)"):
            with self.subTest(owner=sql[:40]):
                self.assertEqual(sqlstate(self.as_owner, sql, r=run_id), "42501")
        self.assertEqual(sqlstate(self.as_owner, "TRUNCATE ca.investigation_result"), "42501")


if __name__ == "__main__":
    unittest.main()
