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


H1, H2 = "1" * 64, "2" * 64
DIGEST = "d" * 64


def package(name, version="1.2.3", hashes=(H1,), import_names=(), allowed_paths=(), **over):
    c = component(name, type="python-package", name=name, version=version,
                  pin={"kind": "exact-version", "value": version}, scope="build-and-test",
                  hashes=list(hashes), import_names=list(import_names), allowed_paths=list(allowed_paths))
    c.update(over)
    return c


def image(cid="postgres", value=None, **over):
    c = component(cid, type="container-image", name="postgres", version="18.6-trixie", scope="ci-only",
                  pin={"kind": "image-digest", "value": value or f"postgres:18.6-trixie@sha256:{DIGEST}"})
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

    def test_secret_contexts_rejected_but_python_secrets_module_allowed(self):
        nl = chr(10)
        ok = GOOD_WORKFLOW + '      - run: python -c "import secrets; print(secrets.token_urlsafe(32))"' + nl
        self.assertEqual(self.rewrite(ok), [])
        for bad in ("${{ secrets.TOKEN }}", "${{secrets['TOKEN']}}", "${{ toJSON(secrets) }}"):
            with self.subTest(bad=bad):
                problems = self.rewrite(GOOD_WORKFLOW + "      - run: echo " + bad + nl)
                self.assertTrue(any("secrets" in p for p in problems))

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
        self.inv["components"].append(package("pkg", hashes=("0" * 64,)))
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



class Version02Tests(TreeCase):
    """ca-supply-chain/0.2: digest-pinned images and hash-pinned, path-restricted Python packages."""

    def add(self, *components, manifests=()):
        self.inv["components"] += list(components)
        self.inv["dependency_manifests"] = list(manifests)
        self.save(sbom=not sc.check_inventory(self.inv))  # the tool only builds SBOMs for valid inventories

    def test_python_package_component_validation(self):
        cases = [
            (package("a", pin={"kind": "exact-version", "value": "9.9"}), "exact-version pin equal to version"),
            (package("b", hashes=()), "sha256 artifact hashes"),
            (package("c", hashes=("xyz",)), "sha256 artifact hashes"),
            (package("d", hashes=(H1, H1)), "sha256 artifact hashes"),
            (package("e", import_names=("not-a-module",)), "import_names"),
            (package("f", import_names=("f",), allowed_paths=()), "needs at least one allowed path"),
            (package("g", import_names=("g",), allowed_paths=("../escape/",)), "allowed_paths"),
            (package("h", import_names=("h",), allowed_paths=("src/db",)), "allowed_paths"),
        ]
        for comp, needle in cases:
            with self.subTest(needle=needle, name=comp["name"]):
                self.inv = inventory()
                self.add(comp)
                self.assertTrue(any(needle in p for p in self.problems("inventory")), self.problems("inventory"))

    def test_manifest_must_match_inventory_versions_and_hashes(self):
        reqs = "requirements-db.txt"
        self.write(reqs, "PG8000==1.31.6 \\\n    --hash=sha256:" + H1 + " \\\n    --hash=sha256:" + H2 + "\n")
        self.add(package("pg8000", "1.31.6", (H1, H2), ("pg8000",), ("src/cloud_autopsy/db/",)), manifests=[reqs])
        self.assertEqual(self.problems("dependency-manifests"), [])
        self.write(reqs, "pg8000==1.31.5 --hash=sha256:" + H1 + " --hash=sha256:" + H2 + "\n")
        self.assertTrue(any("differs from inventory version" in p for p in self.problems("dependency-manifests")))
        self.write(reqs, "pg8000==1.31.6 --hash=sha256:" + H1 + "\n")
        self.assertTrue(any("hashes differ" in p for p in self.problems("dependency-manifests")))
        self.write(reqs, "pg8000==1.31.6 --hash=sha256:" + H1 + " --hash=sha256:" + H2
                   + "\nscramp==1.5.0 --hash=sha256:" + H1 + "\n")
        self.assertTrue(any("scramp is not an inventoried" in p for p in self.problems("dependency-manifests")))

    def test_inventoried_package_must_be_pinned_somewhere(self):
        self.add(package("six", "1.17.0"))
        self.assertTrue(any("six is not pinned" in p for p in self.problems("dependency-manifests")))

    def test_third_party_import_only_inside_allowed_paths(self):
        reqs = "requirements-db.txt"
        self.write(reqs, "pg8000==1.31.6 --hash=sha256:" + H1 + "\n")
        self.add(package("pg8000", "1.31.6", (H1,), ("pg8000",), ("src/cloud_autopsy/db/",)), manifests=[reqs])
        self.write("src/cloud_autopsy/db/adapter.py", "import pg8000.native\n")
        self.assertEqual(self.problems("imports"), [])
        self.write("src/cloud_autopsy/contracts/leak.py", "import pg8000\n")
        problems = self.problems("imports")
        self.assertEqual(len(problems), 1)
        self.assertIn("only allowed under src/cloud_autopsy/db/", problems[0])
        self.write("src/cloud_autopsy/db/other.py", "import scramp\n")  # indirect dependency, not importable
        self.assertTrue(any("'scramp' is not standard library" in p for p in self.problems("imports")))

    def test_container_image_pins(self):
        bad = [image(value="postgres:18.6-trixie"), image(value="postgres@sha256:" + "z" * 64),
               image(pin={"kind": "exact-version", "value": "18.6"}),
               component("x", pin={"kind": "image-digest", "value": f"postgres@sha256:{DIGEST}"})]
        for comp in bad:
            with self.subTest(pin=comp["pin"]):
                self.inv = inventory()
                self.add(comp)
                self.assertTrue(self.problems("inventory"))

    def test_image_references_must_be_digest_pinned_and_inventoried(self):
        ref = f"postgres:18.6-trixie@sha256:{DIGEST}"
        self.add(image())
        self.assertTrue(any("nothing references it" in p for p in self.problems("images")))
        self.write("db/test/compose.yaml", f"services:\n  postgres:\n    image: {ref}\n")
        self.assertEqual(self.problems("images"), [])
        cases = {
            "services:\n  db:\n    image: postgres:18.6\n": "is not pinned",
            "services:\n  db:\n    image: 'postgres:latest'\n": "is not pinned",
            f"services:\n  db:\n    image: postgres@sha256:{'e' * 64}\n": "does not match the inventory",
            f"services:\n  db:\n    image: mysql@sha256:{DIGEST}\n": "does not match the inventory",
        }
        for text, needle in cases.items():
            with self.subTest(text=text):
                self.write("db/test/other.yaml", text)
                self.assertTrue(any(needle in p for p in self.problems("images")), self.problems("images"))
        (self.root / "db/test/other.yaml").unlink()
        self.write("db/Dockerfile", "FROM postgres:18.6\n")
        self.assertTrue(any("db/Dockerfile" in p for p in self.problems("images")))
        self.write("db/Dockerfile", f"FROM {ref}\n")
        self.write(".github/workflows/ci.yml", GOOD_WORKFLOW + "      - uses: docker://postgres:18\n")
        problems = self.problems("images")
        self.assertTrue(any(".github/workflows/ci.yml" in p and "not pinned" in p for p in problems), problems)
        self.assertEqual(self.problems("workflows"), [])  # docker:// is checked as an image, not an action

    def test_sbom_carries_hashes_and_container_purl(self):
        reqs = "requirements-db.txt"
        self.write(reqs, "python_dateutil==2.9.0.post0 --hash=sha256:" + H2 + " --hash=sha256:" + H1 + "\n")
        self.write("db/test/compose.yaml", f"services:\n  postgres:\n    image: postgres:18.6-trixie@sha256:{DIGEST}\n")
        self.add(package("python-dateutil", "2.9.0.post0", (H2, H1)), image(), manifests=[reqs])
        self.assertEqual({k: v for k, v in sc.run_checks(self.root).items() if v}, {})
        doc = json.loads(sc.sbom_bytes(self.inv))
        by_ref = {c["bom-ref"]: c for c in doc["components"]}
        self.assertEqual(by_ref["python-dateutil"]["purl"], "pkg:pypi/python-dateutil@2.9.0.post0")
        self.assertEqual([h["content"] for h in by_ref["python-dateutil"]["hashes"]], [H1, H2])
        self.assertEqual(by_ref["postgres"]["type"], "container")
        self.assertEqual(by_ref["postgres"]["purl"], f"pkg:docker/library/postgres@sha256%3A{DIGEST}")

    def test_license_gate_still_applies_to_new_component_types(self):
        self.add(image(license={"spdx": "PostgreSQL", "source": "https://www.postgresql.org/about/licence/",
                                "review": "pending"}))
        self.assertTrue(any("requires an approved specialist review" in p for p in self.problems("inventory")))
        self.inv = inventory()
        self.add(package("scramp", "1.5.0", license={"spdx": "MIT-0", "source": "https://codeberg.org/x",
                                                       "review": "pending"}))
        self.assertTrue(any("MIT-0 requires an approved" in p for p in self.problems("inventory")))



class ProvisionalDispositionTests(TreeCase):
    """A recorded product-owner disposition admits non-permissive licenses for test-only scope only."""

    def lic(self, spdx, review="provisional", **extra):
        return {"spdx": spdx, "source": "https://example.invalid/LICENSE", "review": review, **extra}

    def problems_for(self, comp):
        self.inv = inventory()
        self.inv["components"].append(comp)
        self.save(sbom=False)
        return self.problems("inventory")

    def test_provisional_admits_test_only_non_permissive_licenses(self):
        comp = image(license=self.lic("PostgreSQL", disposition_record="docs/x.md"))
        self.assertEqual(self.problems_for(comp), [])

    def test_provisional_needs_a_record(self):
        comp = image(license=self.lic("PostgreSQL"))
        self.assertTrue(any("disposition_record" in p for p in self.problems_for(comp)))

    def test_provisional_never_covers_shipped_components_or_copyleft(self):
        shipped = package("x", scope="runtime-shipped", license=self.lic("MIT-0", disposition_record="d"))
        self.assertTrue(any("shipped" in p for p in self.problems_for(shipped)))
        lgpl = package("psycopg", license=self.lic("LGPL-3.0-only", disposition_record="d"))
        self.assertTrue(any("requires an approved specialist review" in p for p in self.problems_for(lgpl)))


if __name__ == "__main__":
    unittest.main()
