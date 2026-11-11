"""CA-P2-004a offline tests: evidence bundles, strict loading, offline investigation, CLI and grants.

No database and no network. The database path is tested in tests/integration/test_bundles.py.
"""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.api import grants as G  # noqa: E402
from cloud_autopsy.app import bundle as B  # noqa: E402
from cloud_autopsy.app import create as C  # noqa: E402
from cloud_autopsy.app import create_cli, offline  # noqa: E402
from cloud_autopsy.app import private_dir as P  # noqa: E402
from cloud_autopsy.contracts import canonical  # noqa: E402
from cloud_autopsy.synthetic import scenario_001 as scenario  # noqa: E402

EXAMPLES = REPO / "examples" / "bundles"
# Result digests of the six variants before this slice (also served by the API and dashboard).
EXPECTED = {
    "config-cause": ("resolved", "c95ad8038fada020162fa4add60429e500eabe1ced7687bf9b50e8b0868f58a5"),
    "configmap-unavailable": ("abstained", "080a1cd3f47a11d1ce853e641a2d37cdd712c9ac554faf0eb2d456ebc158ecac"),
    "configmap-conflict": ("abstained", "c9277c489fdd345455671ce8be5ddd49ffc332eddc0fe7ae3afbba22bea6d9b4"),
    "clock-unknown": ("abstained", "f9934a8b3a8ce443c3bb4207127e505550f753f09f582f58b772910c98be46e7"),
    "symptom-before-change": ("abstained", "98229e03cb56d1cbcaa3862cf0b234075c9a207b3883bd11d8d8919d980e1ae4"),
    "no-symptom": ("abstained", "58e15e48f5dfc9067742bffb3bd5cdd29d30f7fd886898d175b223af1004c980"),
}


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ca-bundle-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def copy(self, variant="config-cause"):
        target = self.tmp / f"b-{len(list(self.tmp.iterdir()))}"
        shutil.copytree(EXAMPLES / variant, target)
        return target

    def manifest(self, root):
        return json.loads((root / "bundle.json").read_bytes())

    def save_manifest(self, root, manifest):
        (root / "bundle.json").write_bytes(canonical.canonical_bytes(manifest))

    def rewrite(self, root, rel, record):
        """Replace a listed file with ``record`` (canonical) and update its manifest digest."""
        data = canonical.canonical_bytes(record)
        (root / rel).write_bytes(data)
        manifest = self.manifest(root)
        for key in ("registry", "plan", "clocks"):
            if manifest[key]["path"] == rel:
                manifest[key]["sha256"] = hashlib.sha256(data).hexdigest()
        for entry in manifest["batches"]:
            if entry["path"] == rel:
                entry["sha256"] = hashlib.sha256(data).hexdigest()
        self.save_manifest(root, manifest)

    def refused(self, root, code):
        with self.assertRaises(B.BundleError) as ctx:
            B.load(root)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception


class ExampleBundleTests(Workspace):
    def test_examples_are_exactly_the_exported_variants(self):
        """The committed examples hold only contract records and match a fresh export byte for byte."""
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        for variant in scenario.VARIANTS:
            B.export_variant(fresh / variant, variant)
        self.assertEqual(sorted(p.name for p in EXAMPLES.iterdir()), sorted(scenario.VARIANTS))
        for variant in scenario.VARIANTS:
            with self.subTest(variant=variant):
                self.assertEqual(tree(EXAMPLES / variant), tree(fresh / variant))

    def test_examples_carry_no_outcome_truth_or_secret(self):
        for variant in scenario.VARIANTS:
            for rel, data in tree(EXAMPLES / variant).items():
                text = data.decode("utf-8").lower()
                with self.subTest(variant=variant, file=rel):
                    for word in ("ground_truth", "expected_outcome", "resolved", "abstained", "password", "secret",
                                 "token", "begin private key"):
                        self.assertNotIn(word, text)

    def test_every_variant_reproduces_its_existing_result(self):
        for variant, (status, digest) in EXPECTED.items():
            with self.subTest(variant=variant):
                inv = C.investigate_offline(B.load(EXAMPLES / variant))
                _, reference = offline.offline_from_records(scenario.plan(variant), scenario.registry(),
                                                            scenario.batches(variant),
                                                            scenario.clock_domain_records(variant))
                self.assertEqual(inv.result_bytes, reference)
                self.assertEqual(inv.result["outcome"]["status"], status)
                self.assertEqual(inv.result_digest.split(":")[1], digest)
                self.assertIs(inv.verified, False)
                self.assertIn("not database-verified", inv.label)

    def test_delivery_order_does_not_change_the_result(self):
        root = self.copy("configmap-conflict")
        manifest = self.manifest(root)
        manifest["batches"].reverse()
        self.save_manifest(root, manifest)
        self.assertEqual(C.investigate_offline(B.load(root)).result_digest.split(":")[1], EXPECTED["configmap-conflict"][1])

    def test_conflicting_redelivery_is_evidence_not_a_refusal(self):
        loaded = B.load(EXAMPLES / "configmap-conflict")
        keys = [(b["source_id"], b["query_id"], b["batch_key"]) for b in loaded.batches]
        self.assertEqual(len(keys) - len(set(keys)), 1)  # two different batches under one key: kept
        self.assertEqual(C.investigate_offline(loaded).result["outcome"]["status"], "abstained")


class RefusalTests(Workspace):
    def test_manifest_shape_version_and_classification(self):
        root = self.copy()
        (root / "bundle.json").unlink()
        self.refused(root, "bundle_file_missing")
        for change, code in ((lambda m: m.update(extra=1), "bundle_manifest_invalid"),
                             (lambda m: m.update(contract_version="ca-investigation-bundle/0.2-provisional"),
                              "bundle_version_unsupported"),
                             (lambda m: m.update(data_classification="customer"), "bundle_classification_refused"),
                             (lambda m: m.update(bundle_id="Not An Id"), "bundle_manifest_invalid"),
                             (lambda m: m.update(batches=[]), "bundle_manifest_invalid"),
                             (lambda m: m["plan"].update(sha256="ABC"), "bundle_manifest_invalid")):
            with self.subTest(code=code):
                root = self.copy()
                manifest = self.manifest(root)
                change(manifest)
                self.save_manifest(root, manifest)
                self.refused(root, code)

    def test_unsafe_paths_are_refused(self):
        for bad in ("../plan.json", "/etc/passwd", "C:/x.json", "batches\\0001.json", "batches/../plan.json",
                    "batches/sub/0001.json", "Plan.json", ".hidden.json", "plan.txt", "bundle.json"):
            with self.subTest(path=bad):
                root = self.copy()
                manifest = self.manifest(root)
                manifest["plan"]["path"] = bad
                self.save_manifest(root, manifest)
                self.refused(root, "bundle_path_refused")

    def test_a_file_listed_twice_is_a_conflict(self):
        root = self.copy()
        manifest = self.manifest(root)
        manifest["batches"].append(dict(manifest["batches"][0]))
        self.save_manifest(root, manifest)
        self.refused(root, "bundle_manifest_conflict")

    def test_unlisted_files_and_directories_are_refused(self):
        for rel in ("ground-truth.json", "batches/notes.json", "notes"):
            with self.subTest(entry=rel):
                root = self.copy()
                target = root / rel
                if rel == "notes":
                    target.mkdir()
                else:
                    target.write_bytes(b"{}")
                self.refused(root, "bundle_unexpected_entry")

    def test_digest_mismatch_and_non_canonical_json(self):
        root = self.copy()
        data = bytearray((root / "batches/0001.json").read_bytes())
        data[-2:-1] = b" " if data[-2:-1] != b" " else b"x"
        (root / "batches/0001.json").write_bytes(bytes(data))
        self.refused(root, "bundle_digest_mismatch")
        root = self.copy()
        pretty = json.dumps(json.loads((root / "plan.json").read_bytes()), indent=2).encode()
        (root / "plan.json").write_bytes(pretty)
        manifest = self.manifest(root)
        manifest["plan"]["sha256"] = hashlib.sha256(pretty).hexdigest()
        self.save_manifest(root, manifest)
        self.refused(root, "bundle_not_canonical")
        root = self.copy()
        dup = b'{"clock_domains":[],"clock_domains":[]}'
        (root / "clocks.json").write_bytes(dup)
        manifest = self.manifest(root)
        manifest["clocks"]["sha256"] = hashlib.sha256(dup).hexdigest()
        self.save_manifest(root, manifest)
        self.refused(root, "bundle_json_invalid")

    def test_size_and_count_limits_are_checked_before_reading(self):
        root = self.copy()
        with open(root / "batches/0001.json", "r+b") as fh:
            fh.truncate(B.MAX_RECORD_BYTES + 1)  # sparse: oversized by metadata, never parsed
        self.refused(root, "bundle_file_too_large")
        root = self.copy()
        manifest = self.manifest(root)
        manifest["batches"] = [{"path": f"batches/{i:04d}.json", "sha256": "0" * 64} for i in range(1, B.MAX_BATCH_FILES + 2)]
        self.save_manifest(root, manifest)
        self.refused(root, "bundle_file_too_large")  # such a manifest already exceeds the 64 KiB manifest cap
        root = self.copy()
        saved, B.MAX_BATCH_FILES = B.MAX_BATCH_FILES, 4  # the count rule itself (5 batch files)
        try:
            self.refused(root, "bundle_manifest_invalid")
        finally:
            B.MAX_BATCH_FILES = saved

    def test_mismatched_records_are_refused(self):
        root = self.copy()
        plan = json.loads((root / "plan.json").read_bytes())
        plan["registry_digest"] = plan["registry_digest"][:-1] + ("0" if plan["registry_digest"][-1] != "0" else "1")
        self.rewrite(root, "plan.json", plan)
        self.refused(root, "bundle_record_invalid")
        root = self.copy()
        batch = json.loads((root / "batches/0001.json").read_bytes())
        batch["plan_digest"] = json.loads((EXAMPLES / "no-symptom" / "batches/0001.json").read_bytes())["plan_digest"]
        self.rewrite(root, "batches/0001.json", batch)
        self.assertIn("plan_mismatch", str(self.refused(root, "bundle_record_invalid")))
        root = self.copy()
        clocks = json.loads((root / "clocks.json").read_bytes())
        clocks["clock_domains"] = clocks["clock_domains"][1:]
        self.rewrite(root, "clocks.json", clocks)
        self.assertIn("clock_domain_missing", str(self.refused(root, "bundle_record_invalid")))
        root = self.copy()
        batch = json.loads((root / "batches/0002.json").read_bytes())
        batch["expected_outcome"] = "resolved"
        self.rewrite(root, "batches/0002.json", batch)
        self.refused(root, "bundle_record_invalid")

    def test_more_batches_than_the_plan_allows_are_refused(self):
        root = self.copy()
        plan = json.loads((root / "plan.json").read_bytes())
        plan["limits"]["max_batch_deliveries"] = 4  # the bundle has 5 batch files
        self.rewrite(root, "plan.json", plan)
        # every batch is bound to the old plan digest, but the count check comes first
        self.refused(root, "bundle_limit_exceeded")

    def test_links_and_reparse_points_are_refused(self):
        root = self.copy()
        os.link(root / "batches/0001.json", self.tmp / "hardlink.json")
        self.refused(root, "bundle_hard_link_refused")
        root = self.copy()
        outside = self.tmp / "outside.json"
        shutil.copy(root / "plan.json", outside)
        (root / "plan.json").unlink()
        try:
            os.symlink(outside, root / "plan.json")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks need privileges on this platform")
        self.refused(root, "bundle_link_refused")

    @unittest.skipUnless(os.name == "nt", "Windows junctions")
    def test_windows_junctions_are_refused(self):
        root = self.copy()
        real = self.tmp / "real-batches"
        shutil.move(str(root / "batches"), real)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "batches"), str(real)], check=True, capture_output=True)
        self.refused(root, "bundle_link_refused")
        root2 = self.copy()
        link = self.tmp / "junction-root"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(root2)], check=True, capture_output=True)
        self.refused(link, "bundle_link_refused")


class CliTests(Workspace):
    def test_database_mode_without_the_driver_fails_cleanly(self):
        if importlib.util.find_spec("pg8000"):
            self.skipTest("the driver is installed")
        with self.assertRaises(C.CreationFailed) as ctx:
            C.create_in_database({}, B.load(EXAMPLES / "config-cause"))
        self.assertEqual((ctx.exception.stage, ctx.exception.run_id), ("start", None))

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = create_cli.main(list(argv))
        return code, out.getvalue()

    def test_offline_cli_labels_results_and_reports_refusals(self):
        code, text = self.run_cli("--offline", str(EXAMPLES / "config-cause"), str(EXAMPLES / "no-symptom"))
        self.assertEqual(code, 0)
        self.assertEqual(text.count("not database-verified"), 2)
        self.assertNotIn("Verified on read", text)
        bad = self.copy()
        (bad / "extra.json").write_bytes(b"{}")
        code, text = self.run_cli("--offline", str(EXAMPLES / "config-cause"), str(bad), "--json")
        self.assertEqual(code, 1)
        rows = json.loads(text)
        self.assertEqual([r["status"] for r in rows], ["ok", "refused"])
        self.assertEqual(rows[1]["code"], "bundle_unexpected_entry")
        self.assertIs(rows[0]["verified"], False)

    def test_offline_cannot_issue_a_grant_or_serve(self):
        for extra in (["--serve"], ["--grant-dir", str(self.tmp / "g")]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit) as ctx, redirect_stdout(io.StringIO()):
                create_cli.main(["--offline", str(EXAMPLES / "config-cause"), *extra])
            self.assertEqual(ctx.exception.code, 2)
        self.assertFalse((self.tmp / "g").exists())

    @unittest.skipUnless(importlib.util.find_spec("pg8000"), "database mode needs the hash-locked driver tree")
    def test_a_database_failure_is_reported_with_its_stage_and_no_grant(self):
        class FakeDb:
            roles = {}
            host, port, name, passwords = "127.0.0.1", 1, "x", {"ca_engine": "x"}

            def connect(self, role):
                return Boom()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Boom:
            def __getattr__(self, name):
                raise RuntimeError("no database here")

        FakeDb.roles = {r: Boom() for r in ("ca_planner", "ca_ingest", "ca_sealer", "ca_engine", "ca_result_writer")}
        out = io.StringIO()
        with redirect_stdout(out):
            code = create_cli.main([str(EXAMPLES / "config-cause"), "--serve", "--json"], database_factory=FakeDb)
        self.assertEqual(code, 1)
        row = json.loads(out.getvalue())[0]
        self.assertEqual((row["status"], row["stage"], row["reason"], row["run_id"]), ("failed", "register", "RuntimeError", None))


class GrantTests(Workspace):
    def investigation(self):
        return C.DatabaseInvestigation("b", "0" * 64, "2b099131-bb6b-5ccf-a811-8d092a7ae1a4", "d", "r", b"{}")

    def test_grants_are_only_for_database_verified_runs(self):
        offline_only = C.investigate_offline(B.load(EXAMPLES / "config-cause"))
        for bad in ([], [offline_only], [self.investigation(), offline_only]):
            with self.subTest(n=len(bad)), self.assertRaises(TypeError):
                C.issue_private_grant(bad, self.tmp / "never")
        self.assertFalse((self.tmp / "never").exists())

    def test_a_grant_is_private_outside_git_and_accepted_by_the_api(self):
        files = C.issue_private_grant([self.investigation()], self.tmp / "grant")
        token = files.token_path.read_text(encoding="ascii")
        grants = G.load(files.grants_path)
        self.assertIsNotNone(grants.authenticate(f"Bearer {token}"))
        self.assertTrue(grants.authenticate(f"Bearer {token}").authorizes(self.investigation().run_id))
        self.assertNotIn(token, files.grants_path.read_text())  # only the hash is stored
        if os.name == "nt":
            trustees = P._dacl_trustees(files.directory, P._system32("icacls.exe"))
            self.assertLessEqual(trustees, {P._current_sid(), "SY", "BA", "OW", P.SYSTEM_SID,
                                            P.ADMINISTRATORS_SID, P.OWNER_RIGHTS_SID})
        else:
            self.assertEqual(os.stat(files.directory).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(files.token_path).st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            C.issue_private_grant([self.investigation()], self.tmp / "grant")  # never reuses a directory

    def test_secrets_are_never_written_inside_a_git_tree(self):
        inside = REPO / "out" / "never-a-grant-dir"
        with self.assertRaises(P.PrivateDirError):
            C.issue_private_grant([self.investigation()], inside)
        self.assertFalse(inside.exists())


if __name__ == "__main__":
    unittest.main()
