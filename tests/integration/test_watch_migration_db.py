"""CA-P2-004f migration 0008 against a real disposable PostgreSQL: historical data is untouched.

One database is migrated to 0007 only and filled with the historical kinds of data: the six
scenario variants (stored, sealed, investigated, results written) and a 0.2 Kubernetes recording
run. Then 0008 is applied to that same database. Required by the F6 authorization:
- every row of every ``ca`` table is byte-identical before and after 0008;
- the ledger checksums of 0001-0007 equal the pinned values (the files are unchanged);
- every stored result still verifies on read, and the six result digests equal their pins;
- before 0008 a profile-3 plan is refused by the database; after it, it is accepted;
- CA-P2-002e: 0009 is then applied alone; it changes no historical row and makes profile-4 plans acceptable;
- the widened CHECK accepts batch 0.1 and 0.2 only, and the supported-version table lists exactly
  this package's additional versions.
Synthetic data only.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import _db

RECORDINGS = _db.REPO / "examples" / "k8s-recordings"
PINNED_0001_0007 = {
    "0001_core.sql": "00561d887386c907899f941caef564b3c67d310e50f09fc5ba6ab6283829aeaf",
    "0002_ingest_requires_collecting.sql": "e60c164187e1f6133f8d3b8d85ee0a58af3cb102d4c6e07f44e63b570533f82b",
    "0003_engine_read_views.sql": "30313c30dfa6f1e96974c5607bbf715c9277abe2c02b77cde582122b7ab255c0",
    "0004_investigation_results.sql": "ec67de3a864ae856c676ff4c3c394ed29141ef720901f5b0921c490449a85296",
    "0005_run_status_view.sql": "2ad2b919d42c4c1d08c69914cabad01ca9ca7b7035193266b0e67dcc61f25df6",
    "0006_kind_registry_versions.sql": "4b3032557699df73675bd6a535a2adfbac25e1c41623e688666baec1bcd5767d",
    "0007_evidence_binding_records.sql": "a27b2015be84dc9c38454e5e5a025f9b939476d0b6ae274c4860dfe47e34a825",
}
# The six pinned ca-investigation-result/0.2-provisional digests (tests/engine/test_cross_scope.py).
RESULT_DIGESTS = {
    "config-cause": "c95ad8038fada020162fa4add60429e500eabe1ced7687bf9b50e8b0868f58a5",
    "configmap-unavailable": "080a1cd3f47a11d1ce853e641a2d37cdd712c9ac554faf0eb2d456ebc158ecac",
    "configmap-conflict": "c9277c489fdd345455671ce8be5ddd49ffc332eddc0fe7ae3afbba22bea6d9b4",
    "clock-unknown": "f9934a8b3a8ce443c3bb4207127e505550f753f09f582f58b772910c98be46e7",
    "symptom-before-change": "98229e03cb56d1cbcaa3862cf0b234075c9a207b3883bd11d8d8919d980e1ae4",
    "no-symptom": "58e15e48f5dfc9067742bffb3bd5cdd29d30f7fd886898d175b223af1004c980",
}

if _db.AVAILABLE:
    from cloud_autopsy.app import bundle as B
    from cloud_autopsy.app import create as C
    from cloud_autopsy.app import k8s_recording as K, pipeline
    from cloud_autopsy.contracts import ADDITIONAL_CONTRACT_VERSIONS, canonical
    from cloud_autopsy.contracts import evidence as ev
    from cloud_autopsy.contracts import plan as pl
    from cloud_autopsy.db import migrate, results
    from cloud_autopsy.db.adapter import DbError
    from test_bundles import FixtureDatabase


def _snapshot(admin):
    """{table: md5 over every row's text, in a fixed order} for every base table in schema ca."""
    tables = [r[0] for r in admin.run("SELECT tablename FROM pg_tables WHERE schemaname = 'ca' ORDER BY tablename")]
    snap = {}
    for table in tables:
        row = admin.one(f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) "
                        f"FROM ca.{table} t")
        snap[table] = (row[0], row[1])
    return snap


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class Migration0008Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ca-0008-it-"))
        upto7 = cls.tmp / "migrations-0001-0007"
        upto7.mkdir()
        for name in PINNED_0001_0007:
            shutil.copyfile(migrate.MIGRATIONS_DIR / name, upto7 / name)
        cls.fx = _db.Fixture(migrations_dir=upto7)
        cls.db = FixtureDatabase(cls.fx)
        cls.applied_first = list(cls.fx.applied)
        # Historical data, created before 0008 exists.
        cls.runs = {}
        for variant in RESULT_DIGESTS:
            run_id, _, _ = pipeline.persist_and_seal(cls.db.roles, variant)
            pipeline.record_result(cls.db.roles["ca_engine"], cls.db.roles["ca_result_writer"], run_id)
            cls.runs[variant] = run_id
        conversion = K.convert(RECORDINGS / "snapshot-complete", ev.KIND_REGISTRY_VERSION_V2)
        conversion.write_bundle(cls.tmp / "k8s-v2")
        cls.k8s_loaded = B.load(cls.tmp / "k8s-v2")
        cls.k8s_inv = C.create_in_database(cls.db.roles, cls.k8s_loaded, verify_db=cls.fx.connect("ca_engine"))
        admin = _db.superuser(cls.fx.name)
        try:
            cls.before = _snapshot(admin)
            cls.profile3_before = cls._try_profile3_plan(admin, "profile3-before-0008")
        finally:
            admin.close()
        upto8 = cls.tmp / "migrations-0001-0008"
        shutil.copytree(upto7, upto8)
        shutil.copyfile(migrate.MIGRATIONS_DIR / "0008_watch_contract_versions.sql",
                        upto8 / "0008_watch_contract_versions.sql")
        cls.applied_second = migrate.apply(cls.fx.connect("ca_migrator"), upto8)
        admin = _db.superuser(cls.fx.name)
        try:
            cls.after = _snapshot(admin)
            cls.profile4_before = cls._try_plan(admin, "profile4-before-0009", ev.KIND_REGISTRY_VERSION_V4)
        finally:
            admin.close()
        # CA-P2-002e: then 0009 (every remaining migration) is applied to the same database.
        cls.applied_third = migrate.apply(cls.fx.connect("ca_migrator"))
        admin = _db.superuser(cls.fx.name)
        try:
            cls.after9 = _snapshot(admin)
        finally:
            admin.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.fx.close()

    @classmethod
    def _try_profile3_plan(cls, admin, plan_id):
        return cls._try_plan(admin, plan_id, ev.KIND_REGISTRY_VERSION_V3)

    @classmethod
    def _try_plan(cls, admin, plan_id, kinds):
        """Insert a plan row of the profile pinning ``kinds`` through the planner role; return the SQLSTATE or None."""
        record = cls.k8s_loaded.plan.to_record()
        record["contract_versions"] = pl.required_contract_versions(kinds)
        record["plan_id"] = plan_id
        planner = cls.fx.connect("ca_planner")
        try:
            with planner.transaction():
                planner.run("INSERT INTO ca.run_plan (plan_digest, plan_id, registry_digest, contract_version, "
                            "window_start_ms, window_end_ms, record_bytes) VALUES (:d, :p, :r, :v, :s, :e, :b)",
                            d=canonical.digest(record), p=plan_id, r=cls.k8s_loaded.plan.registry_digest,
                            v=record["contract_version"], s=cls.k8s_loaded.plan.window_start_ms,
                            e=cls.k8s_loaded.plan.window_end_ms, b=canonical.canonical_bytes(record))
            return None
        except DbError as exc:
            return exc.sqlstate

    def admin(self):
        admin = _db.superuser(self.fx.name)
        self.addCleanup(admin.close)
        return admin

    def test_0008_was_applied_alone_and_last(self):
        self.assertEqual(self.applied_first, list(PINNED_0001_0007))
        self.assertEqual(self.applied_second, ["0008_watch_contract_versions.sql"])

    def test_every_historical_row_is_byte_identical(self):
        changed = sorted(t for t in self.before if t != "contract_version_supported"
                         and self.before[t] != self.after[t])
        self.assertEqual(changed, [])
        self.assertEqual(set(self.before), set(self.after))  # no table added or dropped
        # The only table that grew is the supported-version list: exactly two rows were appended.
        self.assertEqual(self.after["contract_version_supported"][0], self.before["contract_version_supported"][0] + 2)

    def test_0009_was_applied_alone_after_0008_and_changes_no_historical_row(self):
        self.assertEqual(self.applied_third, ["0009_pod_log_kinds.sql"])
        changed = sorted(t for t in self.after if t != "contract_version_supported"
                         and self.after[t] != self.after9[t])
        self.assertEqual(changed, [])
        self.assertEqual(set(self.after), set(self.after9))
        self.assertEqual(self.after9["contract_version_supported"][0], self.after["contract_version_supported"][0] + 1)

    def test_profile_4_plans_need_0009(self):
        self.assertEqual(self.profile4_before, "23514")
        self.assertIsNone(self._try_plan(self.admin(), "profile4-after-0009", ev.KIND_REGISTRY_VERSION_V4))

    def test_the_ledger_pins_0001_to_0007_unchanged(self):
        rows = {r[1]: r[2] for r in self.admin().run("SELECT version, filename, sha256 FROM ca_meta.schema_migration")}
        for name, digest in PINNED_0001_0007.items():
            self.assertEqual(rows[name], digest)
        self.assertIn("0008_watch_contract_versions.sql", rows)

    def test_stored_results_still_verify_and_keep_their_pinned_digests(self):
        engine = self.fx.connect("ca_engine")
        for variant, run_id in self.runs.items():
            with self.subTest(variant=variant):
                verified = results.load_verified_result(engine, run_id)
                self.assertEqual(verified.result_digest.split(":")[1], RESULT_DIGESTS[variant])
        verified = results.load_verified_result(engine, self.k8s_inv.run_id)
        self.assertEqual(verified.result_digest, self.k8s_inv.result_digest)

    def test_profile_3_plans_need_0008(self):
        self.assertEqual(self.profile3_before, "23514")
        self.assertIsNone(self._try_profile3_plan(self.admin(), "profile3-after-0008"))

    def test_the_widened_check_accepts_batch_0_1_and_0_2_only(self):
        definition = self.admin().one(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = 'ca' AND t.relname = 'acquisition_batch' "
            "AND c.conname = 'acquisition_batch_contract_version_check'")[0]
        self.assertIn("ca-acquisition-batch/0.1-provisional", definition)
        self.assertIn("ca-acquisition-batch/0.2-provisional", definition)
        self.assertNotIn("0.3-provisional", definition)
        versions = [r[0] for r in self.admin().run("SELECT DISTINCT contract_version FROM ca.acquisition_batch")]
        self.assertEqual(versions, ["ca-acquisition-batch/0.1-provisional"])

    def test_supported_versions_are_exactly_this_packages(self):
        rows = sorted(tuple(r) for r in self.admin().run(
            "SELECT contract_name, contract_version FROM ca.contract_version_supported"))
        self.assertEqual(rows, sorted((n, v) for n, vs in ADDITIONAL_CONTRACT_VERSIONS.items() for v in vs))


if __name__ == "__main__":
    unittest.main()
