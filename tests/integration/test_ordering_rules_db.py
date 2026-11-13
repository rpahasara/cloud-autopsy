"""CA-P2-005b T13 against a real disposable PostgreSQL: rule profiles 1 and 2 side by side.

The same synthetic profile-3 bundle is created twice in one database, once pinning rule profile 1
(timeline rules 0.1) and once pinning rule profile 2 (timeline rules 0.2). No migration is involved
(none exists for this slice). Both runs are stored once, verified on read by re-executing the engine
under the rules each pinned, and equal to their offline results; the two conclusions differ exactly
as the offline tests show (profile 1 abstains, profile 2 resolves the synthetic control). A stored
result forged to claim the other profile fails verification on read. Synthetic data only.
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import _db

sys.path.insert(0, str(_db.REPO / "tests" / "engine"))

if _db.AVAILABLE:
    import test_ordering_rules as T  # the offline T1 fixture
    from cloud_autopsy.app import bundle as B
    from cloud_autopsy.app import create as C
    from cloud_autopsy.contracts import canonical
    from cloud_autopsy.db import results
    from cloud_autopsy.engine import RESULT_DIGEST_ALGORITHM, TIMELINE_RULES_VERSION, TIMELINE_RULES_VERSION_V2
    from test_bundles import FixtureDatabase


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class RuleProfileCoexistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        cls.db = FixtureDatabase(cls.fx)
        cls.tmp = Path(tempfile.mkdtemp(prefix="ca-ordering-db-"))
        cls.runs = {}
        for profile, name in ((1, "p1"), (2, "p2"), ("forge", "p2-forge")):  # "forge": a profile-2 run to tamper with
            fx = T.Fixture(2 if profile == "forge" else profile)
            fx.plan_record["plan_id"] = f"ca-ordering-db-{name}"
            fx.plan = T.pl.RunPlan.from_record(fx.plan_record, fx.registry)
            out = cls.tmp / name
            B.write(out, f"ca-ordering-db-{name}", fx.registry_record, fx.plan_record, fx.clocks,
                    fx.batches(T.spec()))
            loaded = B.load(out)
            offline = C.investigate_offline(loaded)
            stored = C.create_in_database(cls.db.roles, loaded, verify_db=cls.fx.connect("ca_engine"))
            cls.runs[profile] = (offline, stored)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.fx.close()

    def test_both_profiles_are_stored_verified_and_equal_offline(self):
        engine = self.fx.connect("ca_engine")
        for profile in (1, 2):
            offline, stored = self.runs[profile]
            with self.subTest(profile=profile):
                self.assertTrue(stored.verified)
                self.assertEqual(stored.result_digest, offline.result_digest)
                verified = results.load_verified_result(engine, stored.run_id)
                self.assertEqual(verified.result_digest, offline.result_digest)

    def test_the_profiles_conclude_as_offline(self):
        self.assertEqual(self.runs[1][0].result["outcome"]["status"], "abstained")
        self.assertEqual(self.runs[2][0].result["outcome"]["status"], "resolved")

    def test_the_stored_rule_version_columns_follow_each_plan(self):
        admin = _db.superuser(self.fx.name)
        self.addCleanup(admin.close)
        for profile, version in ((1, TIMELINE_RULES_VERSION), (2, TIMELINE_RULES_VERSION_V2)):
            row = admin.one("SELECT timeline_rules_version, engine_version, catalog_version, contract_version "
                            "FROM ca.investigation_result WHERE run_id = CAST(:r AS uuid)", r=self.runs[profile][1].run_id)
            self.assertEqual(tuple(row), (version, "ca-engine/0.1-provisional", "ca-mechanism-catalog/0.1-provisional",
                                          "ca-investigation-result/0.2-provisional"))

    def test_a_result_forged_to_claim_the_other_profile_fails_on_read(self):
        run_id = self.runs["forge"][1].run_id
        admin = _db.superuser(self.fx.name)
        self.addCleanup(admin.close)
        raw = bytes(admin.one("SELECT result_bytes FROM ca.investigation_result WHERE run_id = CAST(:r AS uuid)",
                              r=run_id)[0])
        doc = canonical.loads(raw)
        body = {k: v for k, v in doc.items() if k != "result_digest"}
        body["rule_versions"]["timeline-rules"] = TIMELINE_RULES_VERSION
        body["timeline"]["rule_version"] = TIMELINE_RULES_VERSION
        body["result_digest"] = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
        forged = canonical.canonical_bytes(body)
        with admin.transaction():
            admin.run("SET LOCAL session_replication_role = replica")
            admin.run("UPDATE ca.investigation_result SET result_bytes = :b, result_bytes_sha256 = :h, "
                      "result_digest = :d, timeline_rules_version = :t WHERE run_id = CAST(:r AS uuid)",
                      b=forged, h=hashlib.sha256(forged).hexdigest(), d=body["result_digest"],
                      t=TIMELINE_RULES_VERSION, r=run_id)
        with self.assertRaises(results.StoredResultInvalid):
            results.load_verified_result(self.fx.connect("ca_engine"), run_id)


if __name__ == "__main__":
    unittest.main()
