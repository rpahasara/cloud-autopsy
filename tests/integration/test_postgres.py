"""CA-P2-003b-1 integration tests against a real disposable PostgreSQL 18.6 (synthetic data only).

Each test maps to a planned CA-IT case (docs/phase2/ca-p2-003/migrations-and-tests.md).
"""

import copy
import os
import random
import shutil
import stat
import tempfile
import threading
import unittest
from pathlib import Path

import _db

if _db.AVAILABLE:
    import _evidence_support as ES
    import _manifest_support as M
    from cloud_autopsy.contracts import canonical, frozen_input as fi
    from cloud_autopsy.db import bootstrap, ingest, migrate, seal
    from cloud_autopsy.db.adapter import DbError

ALL = ["configmaps", "deployments", "logs", "metrics", "alerts"]


def sqlstate(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except DbError as exc:
        return exc.sqlstate
    return None


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class PostgresCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        cls.planner = cls.fx.connect("ca_planner")
        cls.ingester = cls.fx.connect("ca_ingest")
        cls.sealer = cls.fx.connect("ca_sealer")
        cls.reader = cls.fx.connect("ca_reader")
        cls.owner = cls.fx.connect("ca_migrator")    # NOINHERIT: privileges only via SET ROLE ca_owner
        cls.auditor = cls.fx.connect("ca_sealer")    # read-only checks of run-scoped rows
        ingest.register_registry(cls.planner, M.REGISTRY)

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def plan(self, acquisitions=ALL, **limits):
        record = M.plan_record(acquisitions)
        record["limits"] = {**record["limits"], **limits}
        plan = M.pl.RunPlan.from_record(record, M.REGISTRY)
        ingest.register_plan(self.planner, plan)
        return plan

    def run_with(self, plan, names, attempts=None):
        run_id = ingest.create_run(self.planner, plan)
        results = [ingest.ingest_batch(self.ingester, run_id, M.batch_record(n, plan, attempt=(attempts or {}).get(n, 1)),
                                       plan, M.REGISTRY) for n in names]
        return run_id, results

    def count(self, table, run_id):
        return self.auditor.one(f"SELECT count(*) FROM ca.{table} WHERE run_id = CAST(:r AS uuid)", r=run_id)[0]

    def as_owner(self, sql, **params):
        """Run one statement as the schema owner (deliberately bypassing runtime grants)."""
        with self.owner.transaction():
            self.owner.run("SET LOCAL ROLE ca_owner")
            return self.owner.run(sql, **params)

    def state(self, run_id):
        return self.auditor.one("SELECT state FROM ca.run WHERE run_id = CAST(:r AS uuid)", r=run_id)[0]


class MigrationTests(PostgresCase):
    def test_migrations_applied_once_and_environment_checked(self):  # CA-IT-001, CA-IT-025, CA-IT-031
        self.assertEqual(self.fx.applied, [m.filename for m in migrate.discover()])
        self.assertEqual(len(self.fx.applied), 3)
        self.assertEqual(migrate.apply(self.owner), [])
        ingest.check_environment(self.reader)
        self.assertEqual(sqlstate(self.owner.run, "UPDATE ca.data_classification SET classification = 'x'"),
                         "42501")

    def test_changed_migration_is_refused(self):  # CA-IT-002
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for m in migrate.discover():  # every file present and only 0001 edited: the checksum is the reason
            (tmp / m.filename).write_bytes((migrate.MIGRATIONS_DIR / m.filename).read_bytes())
        (tmp / "0001_core.sql").write_bytes((tmp / "0001_core.sql").read_bytes() + b"\n-- edited\n")
        with self.assertRaisesRegex(migrate.MigrationError, "checksum"):
            migrate.apply(self.owner, tmp)

    def test_non_pinned_contract_version_rejected(self):  # CA-IT-031
        plan = self.plan(["configmaps"])
        run_id = ingest.create_run(self.planner, plan)
        code = sqlstate(self.as_owner,
                        "INSERT INTO ca.acquisition_batch (run_id, plan_digest, source_id, query_id, batch_key, "
                        "batch_digest, contract_version, sequence, outcome, coverage_start_ms, coverage_end_ms, "
                        "truncated, observation_count, canonical_size, record_bytes) VALUES (CAST(:r AS uuid), :p, "
                        "'k8s-api', 'k8s.configmaps', 'x', :d, 'ca-acquisition-batch/0.2-provisional', 1, 'empty', "
                        "1, 2, false, 0, 1, :b)", r=run_id, p=plan.digest, d=plan.digest, b=b"{}")
        self.assertEqual(code, "23514")


class IngestTests(PostgresCase):
    def test_identical_redelivery_is_idempotent(self):  # CA-IT-004
        plan = self.plan()
        run_id, results = self.run_with(plan, ["cm-1", "cm-1", "deploy-1", "cm-1"], attempts={"cm-1": 3})
        self.assertEqual([r.outcome for r in results],
                         [ingest.ACCEPTED, ingest.DUPLICATE, ingest.ACCEPTED, ingest.DUPLICATE])
        self.assertEqual(self.count("acquisition_batch", run_id), 2)
        self.assertEqual(self.count("batch_delivery", run_id), 4)
        self.assertEqual(self.count("run_delivered_evidence", run_id), 2)

    def test_conflicting_batch_content_is_retained(self):  # CA-IT-005
        plan = self.plan(["configmaps", "deployments"])
        run_id, results = self.run_with(plan, ["cm-1", "cm-1-conflict", "deploy-1", "deploy-2"])
        self.assertEqual(results[1].outcome, ingest.CONFLICTING_VARIANT)
        self.assertEqual(self.count("acquisition_batch", run_id), 4)
        conflicts = self.reader.run("SELECT batch_key, variant_count FROM ca.run_batch_conflict "
                                    "WHERE run_id = CAST(:r AS uuid)", r=run_id)
        self.assertEqual([tuple(c) for c in conflicts], [("cm-1", 2)])
        frozen = seal.seal_run(self.sealer, run_id, plan, M.REGISTRY)
        gaps = fi.collection_items(frozen, "gaps")
        self.assertTrue(any(g["subject"] == "batch" and "batch_conflict" in g["reasons"] for g in gaps))

    def test_conflicting_evidence_never_overwrites(self):  # CA-IT-006
        plan = self.plan(["deployments"])
        original = ES.build("deploy")
        before = self.auditor.one("SELECT record_bytes FROM ca.evidence_version WHERE evidence_id = :e AND "
                                "content_digest = :d", e=original.evidence_id, d=original.content_digest)
        run_id, _ = self.run_with(plan, ["deploy-1", "deploy-2", "deploy-3"])
        versions = self.auditor.run("SELECT content_digest, record_bytes FROM ca.evidence_version WHERE evidence_id = :e",
                                  e=original.evidence_id)
        self.assertEqual(len(versions), 2)
        stored = {row[0]: bytes(row[1]) for row in versions}
        self.assertEqual(stored[original.content_digest], canonical.canonical_bytes(original.to_record()))
        if before is not None:
            self.assertEqual(bytes(before[0]), stored[original.content_digest])
        conflict = self.reader.one("SELECT variant_count FROM ca.run_identity_conflict WHERE run_id = CAST(:r AS uuid) "
                                   "AND evidence_id = :e", r=run_id, e=original.evidence_id)
        self.assertEqual(conflict[0], 2)
        frozen = seal.seal_run(self.sealer, run_id, plan, M.REGISTRY)
        self.assertNotIn(original.evidence_id, {m["evidence_id"] for m in fi.collection_items(frozen, "evidence")})
        self.assertEqual(self.count("run_evidence", run_id), 0)

    def test_exact_limits_under_concurrent_ingestion(self):  # CA-IT-015
        plan = self.plan(["configmaps"], max_batch_deliveries=3)
        run_id = ingest.create_run(self.planner, plan)
        outcomes, lock = [], threading.Lock()

        def worker():
            db = self.fx.connect("ca_ingest")
            try:
                ingest.ingest_batch(db, run_id, M.batch_record("cm-1", plan), plan, M.REGISTRY)
                result = "ok"
            except ingest.LimitExceeded:
                result = "limit"
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(sorted(outcomes), ["limit"] * 5 + ["ok"] * 3)
        self.assertEqual(self.count("batch_delivery", run_id), 3)


class IsolationTests(PostgresCase):
    def test_cross_run_evidence_reference_rejected(self):  # CA-IT-007
        plan = self.plan(["configmaps", "deployments"])
        run_a, _ = self.run_with(plan, ["cm-1"])
        run_b, _ = self.run_with(plan, ["deploy-1"])
        cm = ES.build("cm")
        code = sqlstate(self.as_owner,
                        "INSERT INTO ca.batch_evidence (run_id, source_id, query_id, batch_key, batch_digest, evidence_id, "
                        "content_digest) SELECT CAST(:b AS uuid), source_id, query_id, batch_key, batch_digest, :e, :d "
                        "FROM ca.acquisition_batch WHERE run_id = CAST(:b AS uuid)",
                        b=run_b, e=cm.evidence_id, d=cm.content_digest)
        self.assertEqual(code, "23503")
        # A sealed member must have been delivered to the same run.
        seal.seal_run(self.sealer, run_b, plan, M.REGISTRY)
        code = sqlstate(self.as_owner, "INSERT INTO ca.run_evidence (run_id, evidence_id, content_digest, coverage, "
                        "batch_count) VALUES (CAST(:b AS uuid), :e, :d, 'verified', 1)",
                        b=run_b, e=cm.evidence_id, d=cm.content_digest)
        self.assertEqual(code, "23503")
        self.assertIsNotNone(run_a)


class SealTests(PostgresCase):
    def test_concurrent_sealers_publish_one_manifest(self):  # CA-IT-008
        plan = self.plan(["configmaps", "deployments"])
        run_id, _ = self.run_with(plan, ["cm-1", "deploy-1", "deploy-2"])
        results, lock = [], threading.Lock()
        barrier = threading.Barrier(4)

        def worker(i):
            db = self.fx.connect("ca_sealer")
            barrier.wait(10)
            try:
                frozen = seal.seal_run(db, run_id, plan, M.REGISTRY, worker=f"w{i}")
                result = ("ok", frozen.digest)
            except seal.SealConflict:
                result = ("conflict", None)
            with lock:
                results.append(result)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(sorted(r[0] for r in results), ["conflict"] * 3 + ["ok"])
        self.assertEqual(self.count("frozen_input", run_id), 1)
        self.assertEqual(self.state(run_id), "sealed")

    def test_ingest_after_sealing_is_rejected(self):  # CA-IT-009
        plan = self.plan(["configmaps"])
        run_id, _ = self.run_with(plan, ["cm-1"])
        seal.seal_run(self.sealer, run_id, plan, M.REGISTRY)
        with self.assertRaises(ingest.RunNotCollecting):
            ingest.ingest_batch(self.ingester, run_id, M.batch_record("cm-1", plan), plan, M.REGISTRY)

    def test_failed_publication_leaves_no_partial_manifest(self):  # CA-IT-011, CA-IT-010
        plan = self.plan(["configmaps", "deployments"])
        run_id, _ = self.run_with(plan, ["cm-1", "deploy-1", "deploy-2"])
        with self.assertRaises(seal.InjectedFailure):
            seal.seal_run(self.sealer, run_id, plan, M.REGISTRY, worker="crashing", lease_seconds=0,
                          fail_before_commit=True)
        for table in ("frozen_input", "manifest_page", "run_evidence", "run_gap", "run_coverage", "run_acquisition"):
            self.assertEqual(self.count(table, run_id), 0, table)
        self.assertEqual(self.state(run_id), "sealing")
        frozen = seal.seal_run(self.sealer, run_id, plan, M.REGISTRY, worker="recovery")  # lease expired
        stored = seal.read_frozen_input(self.reader, run_id)
        self.assertEqual((stored.root_bytes, stored.page_bytes), (frozen.root_bytes, frozen.page_bytes))

    def test_replayed_input_is_byte_identical(self):  # CA-IT-016
        plan = self.plan()
        names = ["cm-1", "deploy-1", "deploy-2", "log-1", "metric-1", "alert-denied"]
        run_id, _ = self.run_with(plan, names + ["cm-1", "deploy-2"])
        sealed = seal.seal_run(self.sealer, run_id, plan, M.REGISTRY)
        stored = seal.read_frozen_input(self.reader, run_id)
        shuffled = [M.batch_record(n, plan, attempt=random.Random(i).randint(1, 9)) for i, n in enumerate(names * 2)]
        random.Random(3).shuffle(shuffled)
        replay = fi.verify_replay(stored.root(), stored.pages(), plan, M.REGISTRY, shuffled, sealed.digest)
        self.assertEqual((replay.root_bytes, replay.page_bytes), (stored.root_bytes, stored.page_bytes))
        self.assertEqual(stored.digest, sealed.digest)

    def test_state_and_manifest_triggers(self):  # CA-IT-023, CA-IT-029
        plan = self.plan(["configmaps"])
        run_id, _ = self.run_with(plan, ["cm-1"])
        frozen = fi.seal(plan, M.REGISTRY, [M.batch_record("cm-1", plan)])
        code = sqlstate(self.sealer.run, "INSERT INTO ca.frozen_input (run_id, plan_digest, contract_version, "
                        "manifest_digest, status, root_bytes) VALUES (CAST(:r AS uuid), :p, :v, :d, :s, :b)",
                        r=run_id, p=plan.digest, v=fi.FROZEN_INPUT_VERSION, d=frozen.digest, s=frozen.status,
                        b=frozen.root_bytes)
        self.assertEqual(code, "23514")  # run is collecting, not sealing
        for new_state, version in (("sealed", 1), ("collecting", 1), ("sealing", 5)):
            with self.subTest(new_state=new_state, version=version):
                code = sqlstate(self.sealer.run, "UPDATE ca.run SET state = CAST(:s AS ca.run_state), state_version = :v "
                                "WHERE run_id = CAST(:r AS uuid)", s=new_state, v=version, r=run_id)
                self.assertEqual(code, "23514")
        code = sqlstate(self.planner.run, "INSERT INTO ca.run (run_id, investigation_id, attempt, plan_digest, state) "
                        "SELECT gen_random_uuid(), investigation_id, 99, plan_digest, 'sealed' FROM ca.run "
                        "WHERE run_id = CAST(:r AS uuid)", r=run_id)
        self.assertEqual(code, "23514")


class ReviewRegressionTests(PostgresCase):
    def test_direct_ingest_rows_rejected_once_run_left_collecting(self):  # review finding R1
        # ca_ingest holds INSERT on these tables. Skipping ca.ingest_lock_run must not let it add rows
        # to a sealed run. Each insert reuses an existing row's keys, so only the state guard (a
        # BEFORE trigger, evaluated before key constraints) can refuse it with check_violation.
        plan = self.plan(["configmaps"])
        run_id, _ = self.run_with(plan, ["cm-1"])
        seal.seal_run(self.sealer, run_id, plan, M.REGISTRY)
        b = self.ingester.one(
            "SELECT source_id, query_id, batch_key, batch_digest, plan_digest, contract_version, sequence, outcome, "
            "coverage_start_ms, coverage_end_ms, truncated, observation_count, canonical_size "
            "FROM ca.acquisition_batch WHERE run_id = CAST(:r AS uuid)", r=run_id)
        e = self.ingester.one("SELECT evidence_id, content_digest FROM ca.run_delivered_evidence "
                              "WHERE run_id = CAST(:r AS uuid)", r=run_id)
        attempts = {
            "acquisition_batch": (
                "INSERT INTO ca.acquisition_batch (run_id, plan_digest, source_id, query_id, batch_key, batch_digest, "
                "contract_version, sequence, outcome, coverage_start_ms, coverage_end_ms, truncated, observation_count, "
                "canonical_size, record_bytes) VALUES (CAST(:r AS uuid), :p, :s, :q, 'late-batch', :d, :v, :n, :o, "
                ":cs, :ce, :t, :c, :z, :b)",
                dict(p=b[4], s=b[0], q=b[1], d=b[3], v=b[5], n=b[6], o=b[7], cs=b[8], ce=b[9], t=b[10], c=b[11],
                     z=b[12], b=b"{}")),
            "batch_delivery": (
                "INSERT INTO ca.batch_delivery (run_id, source_id, query_id, batch_key, batch_digest, delivery_no, "
                "attempt) VALUES (CAST(:r AS uuid), :s, :q, :k, :d, 999, 1)", dict(s=b[0], q=b[1], k=b[2], d=b[3])),
            "run_delivered_evidence": (
                "INSERT INTO ca.run_delivered_evidence (run_id, evidence_id, content_digest) "
                "VALUES (CAST(:r AS uuid), :e, :c)", dict(e=e[0], c=e[1])),
            "batch_evidence": (
                "INSERT INTO ca.batch_evidence (run_id, source_id, query_id, batch_key, batch_digest, evidence_id, "
                "content_digest) VALUES (CAST(:r AS uuid), :s, :q, :k, :d, :e, :c)",
                dict(s=b[0], q=b[1], k=b[2], d=b[3], e=e[0], c=e[1])),
        }
        for table, (sql, params) in attempts.items():
            with self.subTest(table=table):
                self.assertEqual(sqlstate(self.ingester.run, sql, r=run_id, **params), "23514")
        self.assertEqual(self.count("acquisition_batch", run_id), 1)
        self.assertEqual(self.count("batch_delivery", run_id), 1)

    def test_swallowed_error_is_never_reported_as_commit(self):  # review finding R2
        plan = self.plan(["configmaps"])
        marker = "swallowed-" + plan.digest[-8:]
        with self.assertRaises(DbError) as caught:
            with self.planner.transaction():
                self.planner.run("INSERT INTO ca.investigation (investigation_id, scenario_id, plan_digest) "
                                 "VALUES (gen_random_uuid(), :s, :p)", s=marker, p=plan.digest)
                self.assertEqual(sqlstate(self.planner.run, "SELECT 1 / 0"), "22012")  # caught by the caller
        self.assertEqual(caught.exception.sqlstate, "25P02")
        self.assertEqual(self.planner.one("SELECT count(*) FROM ca.investigation WHERE scenario_id = :s",
                                          s=marker)[0], 0)
        with self.planner.transaction():  # the connection stays usable
            self.assertEqual(self.planner.one("SELECT 1")[0], 1)


class PrivilegeTests(PostgresCase):
    def test_runtime_roles_cannot_write_outside_their_grants(self):  # CA-IT-003, CA-IT-014, CA-IT-028
        plan = self.plan(["configmaps"])
        run_id, _ = self.run_with(plan, ["cm-1"])
        cm = ES.build("cm")
        denied = [
            (self.ingester, "UPDATE ca.evidence_version SET payload_state = 'purged' WHERE evidence_id = :e",
             {"e": cm.evidence_id}),
            (self.ingester, "DELETE FROM ca.acquisition_batch WHERE run_id = CAST(:r AS uuid)", {"r": run_id}),
            (self.ingester, "UPDATE ca.run SET state = 'sealed' WHERE run_id = CAST(:r AS uuid)", {"r": run_id}),
            (self.ingester, "SELECT 1 FROM ca.run WHERE run_id = CAST(:r AS uuid) FOR UPDATE", {"r": run_id}),
            (self.ingester, "INSERT INTO ca.frozen_input (run_id, plan_digest, contract_version, manifest_digest, "
             "status, root_bytes) VALUES (CAST(:r AS uuid), 'x', 'x', 'x', 'complete', 'x')", {"r": run_id}),
            (self.reader, "INSERT INTO ca.investigation (investigation_id, scenario_id, plan_digest) "
             "VALUES (gen_random_uuid(), 'x', 'x')", {}),
            (self.reader, "SELECT record_bytes FROM ca.evidence_version", {}),
            (self.sealer, "UPDATE ca.run SET attempt = 7 WHERE run_id = CAST(:r AS uuid)", {"r": run_id}),
            (self.sealer, "SELECT ca.ingest_lock_run(CAST(:r AS uuid))", {"r": run_id}),
            (self.planner, "CREATE TABLE ca.rogue (x int)", {}),
            (self.planner, "CREATE TABLE public.rogue (x int)", {}),
            (self.ingester, "SET ROLE ca_owner", {}),
            (self.reader, "CREATE ROLE rogue", {}),
        ]
        for db, sql, params in denied:
            with self.subTest(user=db.user, sql=sql[:50]):
                self.assertEqual(sqlstate(db.run, sql, **params), "42501")

    def test_owner_cannot_mutate_append_only_rows(self):  # CA-IT-014
        plan = self.plan(["configmaps"])
        self.run_with(plan, ["cm-1"])
        cm = ES.build("cm")
        for sql in ("UPDATE ca.evidence_version SET payload_state = 'purged', record_bytes = NULL WHERE evidence_id = :e",
                    "DELETE FROM ca.evidence_identity WHERE evidence_id = :e"):
            with self.subTest(sql=sql[:40]):
                # The owner holds every privilege; the append-only trigger still refuses (ERRCODE 42501).
                self.assertEqual(sqlstate(self.as_owner, sql, e=cm.evidence_id), "42501")
        self.assertEqual(sqlstate(self.owner.run, "SELECT count(*) FROM ca.evidence_version"), "42501")

    def test_runtime_roles_are_not_privileged(self):  # CA-IT-028
        # Exactly the nine application roles, each with the designed attributes. The bootstrap
        # superuser also has a ca_ name, so the role set is asserted by name, not counted by prefix.
        expected = {role: (False, False, False, False, False, False, login)
                    for role, (login, _) in bootstrap.ROLES.items()}
        self.assertEqual(len(expected), 9)
        rows = self.owner.run(
            "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication, rolinherit, "
            "rolcanlogin FROM pg_roles WHERE rolname = ANY(CAST(:names AS text[]))", names=sorted(expected))
        self.assertEqual({r[0]: tuple(r[1:]) for r in rows}, expected)

        # The only membership involving an application role: ca_migrator may SET ROLE ca_owner, without
        # inheriting its privileges or administering it. No role is in a predefined pg_* role.
        members = self.owner.run(
            "SELECT m.rolname, g.rolname, a.admin_option, a.inherit_option, a.set_option FROM pg_auth_members a "
            "JOIN pg_roles m ON m.oid = a.member JOIN pg_roles g ON g.oid = a.roleid "
            "WHERE m.rolname = ANY(CAST(:names AS text[])) OR g.rolname = ANY(CAST(:names AS text[]))",
            names=sorted(expected))
        self.assertEqual([tuple(r) for r in members], [("ca_migrator", "ca_owner", False, False, True)])

        # Function EXECUTE: nothing for PUBLIC, and per role only ca_ingest may call the lock function.
        public_exec = self.owner.run(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'ca' "
            "AND has_function_privilege('public', p.oid, 'EXECUTE')")
        self.assertEqual(public_exec, [])
        for role in expected:
            if role == "ca_owner":
                continue
            with self.subTest(role=role):
                callable_ = self.owner.run(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'ca' AND has_function_privilege(:r, p.oid, 'EXECUTE') ORDER BY 1", r=role)
                self.assertEqual([r[0] for r in callable_], ["ingest_lock_run"] if role == "ca_ingest" else [])

        # SECURITY DEFINER: only the lock function and the intake-freeze trigger function, each owned by
        # the non-privileged ca_owner with a fixed search_path.
        definer = self.owner.run(
            "SELECT p.proname, p.proconfig, pg_get_userbyid(p.proowner) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'ca' AND p.prosecdef ORDER BY 1")
        self.assertEqual([r[0] for r in definer], ["check_ingest_run_collecting", "ingest_lock_run"])
        for name, config, owner in definer:
            with self.subTest(function=name):
                self.assertIn("search_path=pg_catalog, pg_temp", config)
                self.assertEqual(owner, "ca_owner")

    def test_bootstrap_credential_is_initialization_only(self):  # CA-IT-028
        boot = _db.bootstrap_user()
        self.assertNotIn(boot, bootstrap.ROLES)
        self.assertNotIn(boot, self.fx.passwords)
        # The bootstrap superuser owns neither the database nor any object in the ca schema.
        owner = self.owner.one("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")[0]
        self.assertEqual(owner, "ca_owner")
        foreign = self.owner.run(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'ca' AND pg_get_userbyid(c.relowner) <> 'ca_owner' "
            "UNION ALL SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'ca' AND pg_get_userbyid(p.proowner) <> 'ca_owner'")
        self.assertEqual(foreign, [])
        # Every runtime connection authenticated as its own role, never as the bootstrap user.
        for db in (self.planner, self.ingester, self.sealer, self.reader, self.owner):
            with self.subTest(role=db.user):
                self.assertEqual(db.one("SELECT session_user")[0], db.user)
                self.assertNotEqual(db.user, boot)

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_secret_files_are_private(self):
        secret_dir = Path(_db.SECRET_DIR)
        self.assertEqual(stat.S_IMODE(secret_dir.stat().st_mode) & 0o077, 0, "secret directory open to others")
        for role in self.fx.passwords:
            with self.subTest(role=role):
                self.assertEqual(stat.S_IMODE((secret_dir / f"{role}.password").stat().st_mode), 0o600)

if __name__ == "__main__":
    unittest.main()
