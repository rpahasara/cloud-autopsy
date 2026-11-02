"""Tests for the CA-P2-001 supply-chain checks. Synthetic temporary trees only; no network."""

import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import supply_chain as sc  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SHA_A = "a" * 40
SHA_B = "b" * 40

GOOD_WORKFLOW = f"""name: ci
on: [pull_request]
permissions:
  contents: read
jobs:
  t:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@{SHA_A} # v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@{SHA_B}
"""


def component(cid, **over):
    c = {"id": cid, "type": "github-action", "name": f"actions/{cid}", "version": "v1",
         "pin": {"kind": "git-commit", "value": SHA_A}, "scope": "ci-only", "purpose": "test",
         "license": {"spdx": "MIT", "source": "https://example.invalid/LICENSE", "review": "pending"},
         "upgrade_owner": "test owner"}
    c.update(over)
    return c


def inventory():
    return {"schema": sc.INVENTORY_SCHEMA, "status": "test", "dependency_manifests": [],
            "components": [component("checkout"),
                           component("setup-python", pin={"kind": "git-commit", "value": SHA_B})]}


class TreeCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.inv = inventory()
        self.write(".github/workflows/ci.yml", GOOD_WORKFLOW)
        self.write("tools/ok.py", "import json\nfrom pathlib import Path\nfrom . import x\n")
        self.save()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def save(self, sbom=True):
        self.write(sc.INVENTORY_PATH, json.dumps(self.inv))
        if sbom:
            (self.root / sc.SBOM_PATH).write_bytes(sc.sbom_bytes(self.inv))

    def problems(self, section):
        return sc.run_checks(self.root)[section]


class BaselineTests(TreeCase):
    def test_clean_synthetic_tree_passes_every_section(self):
        self.assertEqual({k: v for k, v in sc.run_checks(self.root).items() if v}, {})

    def test_repository_itself_passes(self):
        sections = sc.run_checks(REPO)
        self.assertEqual({k: v for k, v in sections.items() if v}, {})


class InventoryTests(TreeCase):
    def test_missing_and_duplicate_key_inventory_fail_closed(self):
        (self.root / sc.INVENTORY_PATH).unlink()
        self.assertIn("missing", sc.run_checks(self.root)["inventory"][0])
        self.write(sc.INVENTORY_PATH, '{"schema": "x", "schema": "y"}')
        self.assertIn("invalid JSON", sc.run_checks(self.root)["inventory"][0])

    def test_action_must_be_commit_pinned(self):
        self.inv["components"][0]["pin"] = {"kind": "exact-version", "value": "v4"}
        self.save()
        self.assertTrue(any("full commit SHA" in p for p in self.problems("inventory")))

    def test_short_sha_rejected(self):
        self.inv["components"][0]["pin"]["value"] = "abc123"
        self.save()
        self.assertTrue(any("40-hex" in p for p in self.problems("inventory")))

    def test_copyleft_or_unknown_license_needs_approved_review(self):
        for spdx in ("AGPL-3.0-only", "GPL-2.0-or-later", "MPL-2.0", "NOASSERTION", "Custom-EULA"):
            with self.subTest(spdx=spdx):
                self.inv = inventory()
                self.inv["components"][0]["license"]["spdx"] = spdx
                self.save()
                self.assertTrue(self.problems("inventory"))

    def test_approved_review_needs_record(self):
        self.inv["components"][0]["license"]["review"] = "approved"
        self.save()
        self.assertTrue(any("approval_record" in p for p in self.problems("inventory")))

    def test_shipped_component_needs_exact_pin_and_approved_review(self):
        self.inv["components"].append(component(
            "lib", type="python-package", name="lib", scope="runtime-shipped",
            pin={"kind": "version-line", "value": "1"}))
        self.save()
        problems = self.problems("inventory")
        self.assertTrue(any("exact or commit pin" in p for p in problems))
        self.assertTrue(any("without approved license review" in p for p in problems))

    def test_malformed_component_types_do_not_crash(self):
        self.inv["components"] = [7, {"id": 1, "pin": "x", "license": []}]
        self.save(sbom=False)
        sections = sc.run_checks(self.root)
        self.assertTrue(sections["inventory"])
        self.assertEqual(sections["sbom"], ["skipped: inventory invalid"])


class WorkflowTests(TreeCase):
    def rewrite(self, text):
        self.write(".github/workflows/ci.yml", text)
        return self.problems("workflows")

    def test_tag_pinned_action_rejected(self):
        problems = self.rewrite(GOOD_WORKFLOW.replace(f"actions/checkout@{SHA_A}", "actions/checkout@v4"))
        self.assertTrue(any("not pinned" in p for p in problems))

    def test_sha_not_in_inventory_rejected(self):
        problems = self.rewrite(GOOD_WORKFLOW.replace(f"checkout@{SHA_A}", f"checkout@{'c' * 40}"))
        self.assertTrue(any("does not match the inventory" in p for p in problems))

    def test_write_permission_secrets_and_pr_target_rejected(self):
        text = GOOD_WORKFLOW.replace("contents: read", "contents: write") \
            .replace("on: [pull_request]", "on:\n  pull_request_target:") \
            + "      - run: echo ${{ secrets.TOKEN }}\n"
        problems = " ".join(self.rewrite(text))
        for needle in ("write permission", "pull_request_target", "secrets"):
            self.assertIn(needle, problems)

    def test_missing_permissions_and_persisted_credentials_rejected(self):
        text = GOOD_WORKFLOW.replace("permissions:\n  contents: read\n", "") \
            .replace("persist-credentials: false", "persist-credentials: true")
        problems = " ".join(self.rewrite(text))
        self.assertIn("permissions block", problems)
        self.assertIn("persist-credentials", problems)

    def test_unused_inventory_action_reported(self):
        self.inv["components"].append(component("cache", pin={"kind": "git-commit", "value": "d" * 40}))
        self.save()
        self.assertTrue(any("actions/cache" in p for p in self.problems("workflows")))


class ManifestAndImportTests(TreeCase):
    def test_undeclared_dependency_manifest_rejected(self):
        for name in ("requirements.txt", "requirements-dev.in", "pyproject.toml", "uv.lock"):
            with self.subTest(name=name):
                self.write(name, "")
                self.assertTrue(any(name in p for p in self.problems("dependency-manifests")))
                (self.root / name).unlink()

    def test_declared_requirements_need_exact_hash_pins(self):
        self.inv["dependency_manifests"] = ["requirements.txt"]
        self.save()
        good = "pkg==1.2.3 --hash=sha256:" + "0" * 64 + "  # comment\n\n"
        self.write("requirements.txt", good)
        self.assertEqual(self.problems("dependency-manifests"), [])
        self.write("requirements.txt", good + "other>=2\n")
        self.assertTrue(any("requirements.txt:3" in p for p in self.problems("dependency-manifests")))

    def test_third_party_import_rejected_but_stdlib_and_first_party_allowed(self):
        self.write("prototype/pkg/__init__.py", "")
        self.write("prototype/pkg/mod.py", "import pkg.other\nimport hashlib\nfrom pkg import mod\n")
        self.assertEqual(self.problems("imports"), [])
        self.write("src/app.py", "import requests\nfrom yaml import safe_load\n")
        problems = self.problems("imports")
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("src/app.py" in p for p in problems))

    def test_unparseable_python_reported(self):
        self.write("tools/bad.py", "def (:\n")
        self.assertTrue(any("cannot parse" in p for p in self.problems("imports")))


class SecretAndSbomTests(TreeCase):
    def test_secret_shapes_reported_by_location_without_value(self):
        token = "gh" + "p_" + "Z" * 36
        key = "AKIA" + "Q" * 16
        self.write("docs/leak.md", f"ok\ntoken {token}\nid {key}\n")
        self.write("docs/pem.txt", "-----BEGIN " + "PRIVATE KEY-----\n")
        findings = self.problems("secrets")
        self.assertEqual(len(findings), 3)
        self.assertTrue(all(token not in f and key not in f for f in findings))
        self.assertIn("docs/leak.md:2", " ".join(findings))

    def test_binary_and_oversize_files_handled(self):
        (self.root / "img.png").write_bytes(b"\x89PNG" + b"AKIA" + b"Q" * 16)
        (self.root / "big.txt").write_bytes(b"x" * (sc.MAX_SCAN_BYTES + 1))
        findings = self.problems("secrets")
        self.assertEqual(len(findings), 1)
        self.assertIn("not scanned", findings[0])

    def test_sbom_is_deterministic_cyclonedx_and_drift_is_detected(self):
        first = sc.sbom_bytes(self.inv)
        self.assertEqual(first, sc.sbom_bytes(copy.deepcopy(self.inv)))
        doc = json.loads(first)
        self.assertEqual((doc["bomFormat"], doc["specVersion"]), ("CycloneDX", "1.6"))
        self.assertNotIn("timestamp", doc["metadata"])
        self.assertEqual(doc["components"][0]["purl"], f"pkg:github/actions/checkout@{SHA_A}")
        self.inv["components"][0]["version"] = "v9"
        self.write(sc.INVENTORY_PATH, json.dumps(self.inv))
        self.assertTrue(any("out of date" in p for p in self.problems("sbom")))

    def test_sbom_command_refuses_to_overwrite(self):
        out = self.root / "out.json"
        out.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            sc.main(["--root", str(self.root), "sbom", "--out", str(out)])
        self.assertEqual(out.read_bytes(), b"keep")

    def test_check_command_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sc.main(["--root", str(self.root), "check"]), 0)
            self.write("src/app.py", "import requests\n")
            self.assertEqual(sc.main(["--root", str(self.root), "check"]), 1)


if __name__ == "__main__":
    unittest.main()
