"""CA-P2-004d against a real disposable PostgreSQL: observation kinds 0.1 and 0.2 side by side.

- Migration 0006: the supported-version table is append-only and readable by the runtime roles;
  a plan row pinning an unsupported version is refused by the database itself.
- 0.1 runs (the scenario fixtures and a 0.1 conversion) and a 0.2 run of the same recording live in
  one database. Every result is stored, verified on read and equal to offline. Evidence for objects
  both runs observed is stored once, byte-identical, and never re-labelled.
- The same unchanged objects observed through an evolved registry binding seal and verify with records
  bound to their own registry (PR #31 review, migration 0007); the first stored bytes are never rewritten.
  A stored record that does not decode under the run's binding still fails the run at seal.
Synthetic data only.
"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import _db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser"))
import _cdp  # noqa: E402

BROWSER_OK = bool(_cdp.find_browser()) or os.environ.get("CA_BROWSER_REQUIRE") == "1"
RECORDINGS = _db.REPO / "examples" / "k8s-recordings"

if _db.AVAILABLE:
    from cloud_autopsy.app import bundle as B
    from cloud_autopsy.app import create as C
    from cloud_autopsy.app import create_cli, k8s_recording as K, pipeline
    from cloud_autopsy.contracts import canonical
    from cloud_autopsy.contracts import evidence as ev
    from cloud_autopsy.contracts import plan as pl
    from cloud_autopsy.contracts.sources import SourceRegistry
    from cloud_autopsy.db import ingest, results, seal
    from cloud_autopsy.db.adapter import DbError
    from test_bundles import FixtureDatabase


@unittest.skipUnless(_db.AVAILABLE, _db.SKIP_REASON)
class KindsV2DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _db.Fixture()
        cls.db = FixtureDatabase(cls.fx)
        cls.tmp = Path(tempfile.mkdtemp(prefix="ca-kinds-v2-it-"))
        # A 0.1 run created first, so the later 0.2 run meets its stored evidence.
        cls.scenario_run, _, _ = pipeline.persist_and_seal(cls.db.roles, "config-cause")
        cls.scenario_stored, cls.scenario_inv = pipeline.record_result(cls.db.roles["ca_engine"],
                                                                       cls.db.roles["ca_result_writer"], cls.scenario_run)
        cls.created = {}
        for kinds in (ev.KIND_REGISTRY_VERSION, ev.KIND_REGISTRY_VERSION_V2):
            conversion = K.convert(RECORDINGS / "snapshot-complete", kinds)
            out = cls.tmp / kinds[-15:-12]
            conversion.write_bundle(out)
            loaded = B.load(out)
            cls.created[kinds] = (loaded, C.create_in_database(cls.db.roles, loaded, verify_db=cls.fx.connect("ca_engine")))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.fx.close()

    def admin(self):
        admin = _db.superuser(self.fx.name)
        self.addCleanup(admin.close)
        return admin

    def test_the_environment_lists_exactly_the_supported_versions(self):
        for role in ("ca_planner", "ca_ingest", "ca_sealer", "ca_engine", "ca_result_writer"):
            with self.subTest(role=role):
                ingest.check_environment(self.fx.connect(role))
        rows = self.admin().run("SELECT contract_name, contract_version FROM ca.contract_version_supported")
        # Migration 0006 added kinds 0.2; migration 0008 (CA-P2-004f) adds batch 0.2 and kinds 0.3.
        from cloud_autopsy.contracts import ADDITIONAL_CONTRACT_VERSIONS
        expected = sorted((n, v) for n, vs in ADDITIONAL_CONTRACT_VERSIONS.items() for v in vs)
        self.assertEqual(sorted(tuple(r) for r in rows), expected)
        self.assertIn(("observation-kinds", ev.KIND_REGISTRY_VERSION_V2), expected)
        pins = dict(self.admin().run("SELECT contract_name, contract_version FROM ca.contract_pin"))
        self.assertEqual(pins["observation-kinds"], ev.KIND_REGISTRY_VERSION)  # the baseline pin is unchanged

    def test_the_supported_versions_are_append_only(self):
        owner = self.fx.connect("ca_migrator")
        for sql in ("UPDATE ca.contract_version_supported SET contract_version = contract_version",
                    "DELETE FROM ca.contract_version_supported", "TRUNCATE ca.contract_version_supported"):
            with self.subTest(sql=sql[:30]):
                try:
                    with owner.transaction():
                        owner.run("SET LOCAL ROLE ca_owner")
                        owner.run(sql)
                    self.fail("mutation was allowed")
                except DbError as exc:
                    self.assertIn(exc.sqlstate, {"42501", "P0001", "55000"})

    def test_the_database_refuses_a_plan_pinning_an_unsupported_version(self):
        loaded = self.created[ev.KIND_REGISTRY_VERSION_V2][0]
        record = loaded.plan.to_record()
        record["contract_versions"]["observation-kinds"] = "ca-observation-kinds/0.5-provisional"  # 0.4 exists since 0009
        record["plan_id"] = "unsupported-version"
        planner = self.fx.connect("ca_planner")
        with self.assertRaises(DbError) as ctx:
            with planner.transaction():
                planner.run("INSERT INTO ca.run_plan (plan_digest, plan_id, registry_digest, contract_version, "
                            "window_start_ms, window_end_ms, record_bytes) VALUES (:d, :p, :r, :v, :s, :e, :b)",
                            d=canonical.digest(record), p=record["plan_id"], r=loaded.plan.registry_digest,
                            v=record["contract_version"], s=loaded.plan.window_start_ms, e=loaded.plan.window_end_ms,
                            b=canonical.canonical_bytes(record))
        self.assertEqual(ctx.exception.sqlstate, "23514")

    def test_the_database_accepts_a_profile_4_plan_after_0009(self):
        # CA-P2-002e: migration 0009 makes profile 4 (observation kinds 0.4 with batch 0.3, M11) supported.
        loaded = self.created[ev.KIND_REGISTRY_VERSION_V2][0]
        record = loaded.plan.to_record()
        record["contract_versions"] = pl.required_contract_versions(ev.KIND_REGISTRY_VERSION_V4)
        record["plan_id"] = "profile-4-accepted"
        planner = self.fx.connect("ca_planner")
        with planner.transaction():
            planner.run("INSERT INTO ca.run_plan (plan_digest, plan_id, registry_digest, contract_version, "
                        "window_start_ms, window_end_ms, record_bytes) VALUES (:d, :p, :r, :v, :s, :e, :b)",
                        d=canonical.digest(record), p=record["plan_id"], r=loaded.plan.registry_digest,
                        v=record["contract_version"], s=loaded.plan.window_start_ms, e=loaded.plan.window_end_ms,
                        b=canonical.canonical_bytes(record))
        self.assertEqual(self.admin().one("SELECT count(*) FROM ca.run_plan WHERE plan_id = 'profile-4-accepted'")[0], 1)

    def test_0_1_and_0_2_runs_coexist_verified_and_equal_offline(self):
        for kinds, (loaded, inv) in self.created.items():
            with self.subTest(kinds=kinds):
                self.assertIs(inv.verified, True)
                self.assertEqual(inv.result_bytes, C.investigate_offline(loaded).result_bytes)
                again = results.load_verified_result(self.fx.connect("ca_engine"), inv.run_id)
                self.assertEqual(again.result_bytes, inv.result_bytes)
        kinds_in = lambda inv: {e["observation_kind"] for e in json.loads(inv.result_bytes)["timeline"]["entries"]}  # noqa: E731
        self.assertTrue({"k8s_event", "configmap_metadata"} <= kinds_in(self.created[ev.KIND_REGISTRY_VERSION_V2][1]))
        self.assertFalse({"k8s_event", "configmap_metadata"} & kinds_in(self.created[ev.KIND_REGISTRY_VERSION][1]))
        # the 0.1 scenario run stored before any 0.2 run still verifies byte-identically, at its pinned digest
        again = results.load_verified_result(self.fx.connect("ca_engine"), self.scenario_run)
        self.assertEqual(again.result_bytes, self.scenario_inv.result_bytes)
        self.assertTrue(again.result_digest.endswith("c95ad8038fada020162fa4add60429e500eabe1ced7687bf9b50e8b0868f58a5"))

    def test_shared_evidence_is_stored_once_and_never_relabelled(self):
        old = {(e["evidence_id"], e["content_digest"]) for e in self._sealed_members(self.created[ev.KIND_REGISTRY_VERSION][1].run_id)}
        new = {(e["evidence_id"], e["content_digest"]) for e in self._sealed_members(self.created[ev.KIND_REGISTRY_VERSION_V2][1].run_id)}
        shared = old & new
        self.assertEqual(len(shared), 5)  # 2 pods, 2 ReplicaSets, 1 rollout
        admin = self.admin()
        for evidence_id, digest in sorted(shared):
            rows = admin.run("SELECT record_bytes FROM ca.evidence_version WHERE evidence_id = :e AND content_digest = :d",
                             e=evidence_id, d=digest)
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(bytes(rows[0][0]))["kind_registry_version"], ev.KIND_REGISTRY_VERSION)
        new_only = admin.run("SELECT DISTINCT i.observation_kind FROM ca.run_evidence r JOIN ca.evidence_identity i "
                             "ON i.evidence_id = r.evidence_id WHERE r.run_id = CAST(:r AS uuid)",
                             r=self.created[ev.KIND_REGISTRY_VERSION_V2][1].run_id)
        self.assertLessEqual({"k8s_event", "configmap_metadata"}, {r[0] for r in new_only})

    def _sealed_members(self, run_id):
        rows = self.admin().run("SELECT evidence_id, content_digest FROM ca.run_evidence WHERE run_id = CAST(:r AS uuid)",
                                r=run_id)
        return [{"evidence_id": r[0], "content_digest": r[1]} for r in rows]

    def another_binding(self, tag):
        """The 0.1 conversion's plan and batches, re-bound to a registry that differs only in its query list."""
        loaded = self.created[ev.KIND_REGISTRY_VERSION][0]
        record = loaded.registry.to_record()
        record["registry_id"] = tag
        record["sources"][0]["query_ids"] = sorted(record["sources"][0]["query_ids"] + [f"k8s.{tag}"])
        registry = SourceRegistry.from_record(record)
        plan = pl.RunPlan.from_record({**loaded.plan.to_record(), "plan_id": tag, "registry_id": registry.registry_id,
                                       "registry_digest": registry.digest}, registry)
        return loaded, registry, plan, [{**b, "plan_digest": plan.digest} for b in loaded.batches]

    def test_the_same_objects_through_another_registry_binding_seal_and_verify(self):
        """PR #31 review (P1): stored evidence is keyed by (evidence_id, content_digest) but its bytes carry the
        source-binding digest. A later run observing the same unchanged objects through an evolved registry
        (one more query) must seal and verify with its own binding, not be rejected or read the first binding."""
        loaded, registry, plan, batches = self.another_binding("binding-b")
        run_id, _, _ = pipeline.persist_records(self.db.roles, plan, registry, list(loaded.clock_records), batches,
                                                "binding-b")
        stored, inv = pipeline.record_result(self.db.roles["ca_engine"], self.db.roles["ca_result_writer"], run_id)
        self.assertEqual(stored, results.STORED)
        again = results.load_verified_result(self.fx.connect("ca_engine"), run_id)
        self.assertEqual(again.result_bytes, inv.result_bytes)
        for record in again.evidence.values():  # this run reads records bound to its own registry
            self.assertEqual(record["record"]["source_binding_digest"], registry.sources[0].binding_digest)
        # the earlier runs are untouched and still read their own binding
        for _, (old_loaded, old_inv) in self.created.items():
            old = results.load_verified_result(self.fx.connect("ca_engine"), old_inv.run_id)
            self.assertEqual(old.result_bytes, old_inv.result_bytes)
            self.assertEqual({r["record"]["source_binding_digest"] for r in old.evidence.values()},
                             {old_loaded.registry.sources[0].binding_digest})
        # the first stored bytes are never rewritten
        admin = self.admin()
        first = loaded.registry.sources[0].binding_digest
        rows = admin.run("SELECT record_bytes FROM ca.evidence_version v JOIN ca.run_evidence r ON "
                         "r.evidence_id = v.evidence_id AND r.content_digest = v.content_digest "
                         "WHERE r.run_id = CAST(:r AS uuid)", r=run_id)
        self.assertTrue(rows)
        self.assertEqual({json.loads(bytes(r[0]))["source_binding_digest"] for r in rows}, {first})

    def test_a_poisoned_stored_record_still_fails_at_seal(self):
        """The seal-time guard stays: a stored record that does not decode under the run's binding fails the run."""
        loaded, registry, plan, batches = self.another_binding("binding-c")
        member = next(o for b in batches for o in b["observations"])
        evidence = ev.observe(member, source_id=registry.sources[0].source_id, registry=registry)
        forged = evidence.to_record()
        forged["evidence_class"] = "K8S-FORGED"  # same id and digest, inconsistent derived fields
        admin = self.admin()
        with admin.transaction():
            admin.run("INSERT INTO ca.evidence_binding_record (evidence_id, content_digest, source_binding_digest, "
                      "record_bytes) VALUES (:e, :d, :b, :x)", e=evidence.evidence_id, d=evidence.content_digest,
                      b=registry.sources[0].binding_digest, x=canonical.canonical_bytes(forged))
        progress = {}
        with self.assertRaises(seal.SealFailed) as ctx:
            pipeline.persist_records(self.db.roles, plan, registry, list(loaded.clock_records), batches,
                                     "binding-c", progress)
        self.assertEqual(ctx.exception.reason, "seal:record_inconsistent")
        state = admin.one("SELECT state FROM ca.run WHERE run_id = CAST(:r AS uuid)", r=progress["run_id"])
        self.assertEqual(state[0], "failed")

    def get(self, port, path, token):
        con = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        con.request("GET", path, headers={"Authorization": f"Bearer {token}"})
        response = con.getresponse()
        body = json.loads(response.read())
        con.close()
        return response.status, body

    @unittest.skipUnless(BROWSER_OK, "no Chromium-family browser installed (set CA_BROWSER)")
    def test_a_0_2_run_opens_in_the_existing_dashboard(self):
        inv = self.created[ev.KIND_REGISTRY_VERSION_V2][1]
        holder = {}
        create_cli.serve(self.db, [inv], self.tmp / "grant", 0, ready=lambda api, files: holder.update(api=api, files=files))
        api, files = holder["api"], holder["files"]
        threading.Thread(target=api.serve_forever, daemon=True).start()
        token = files.token_path.read_text(encoding="ascii")
        try:
            status, body = self.get(api.port, f"/v1/runs/{inv.run_id}/timeline", token)
            self.assertEqual(status, 200)
            self.assertIn("k8s_event", {e["observation_kind"] for e in body["data"]["entries"]})
            self.assertNotIn(b"Back-off", json.dumps(body).encode())
            b = _cdp.Browser(1440, 900)
            try:
                b.navigate(f"http://127.0.0.1:{api.port}/")
                b.js(f"document.querySelector('#token').value = {json.dumps(token)};"
                     "document.querySelector('#connect-form').requestSubmit(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'home' && "
                           "document.querySelector('.h-granted .m-value')?.textContent === '1'", 30)
                b.js("document.querySelector('[data-view=investigations]').click(); 1")
                b.wait_for(f"document.querySelector('.inv-row[data-run=\"{inv.run_id}\"] .inv-ver')?.textContent === 'Verified'", 30)
                b.js(f"document.querySelector('.inv-row[data-run=\"{inv.run_id}\"]').click(); 1")
                b.wait_for("document.querySelector('#app').dataset.page === 'run' && "
                           "document.querySelector('.verify-title')?.textContent === 'Byte-identical replay'", 30)
                self.assertEqual(b.console_errors(), [])
            finally:
                b.close()
        finally:
            api.shutdown()
            api.server_close()


if __name__ == "__main__":
    unittest.main()
