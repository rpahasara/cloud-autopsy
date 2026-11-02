"""The product package must not reach the frozen prototype, the evaluator or ground truth."""

import ast
import subprocess
import sys
import unittest

import _support

FORBIDDEN_MODULES = {"ca_spike", "ca_eval", "cli", "fixture_tools", "prototype", "heldout_kit", "tests"}
FORBIDDEN_TEXT = ("prototype", "ca_spike", "ca_eval", "ground-truth", "truth-pins", "heldout")


class IsolationTests(unittest.TestCase):
    def python_files(self):
        files = sorted(_support.PACKAGE.rglob("*.py"))
        self.assertTrue(files)
        return files

    def test_imports_are_stdlib_relative_or_own_package(self):
        allowed = set(sys.stdlib_module_names) | {"cloud_autopsy"}
        for path in self.python_files():
            tree = ast.parse(path.read_bytes(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    top = name.split(".", 1)[0]
                    with self.subTest(file=path.name, module=name):
                        self.assertIn(top, allowed)
                        self.assertNotIn(top, FORBIDDEN_MODULES)

    def test_no_dynamic_import_or_file_access_to_prototype_or_truth(self):
        for path in self.python_files():
            text = path.read_text(encoding="utf-8")
            for needle in ("__import__", "importlib", "open(", "Path(") + FORBIDDEN_TEXT:
                with self.subTest(file=path.name, needle=needle):
                    code = "\n".join(line for line in text.splitlines()
                                     if not line.lstrip().startswith("#"))
                    body = _strip_docstrings(code)
                    self.assertNotIn(needle, body)

    def test_importing_the_package_loads_no_prototype_or_network_modules(self):
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "import cloud_autopsy.contracts, cloud_autopsy.contracts.canonical,"
            " cloud_autopsy.contracts.versioning;"
            "bad = {'ca_spike','ca_eval','socket','http','urllib.request','ssl','subprocess'} & set(sys.modules);"
            "print(sorted(bad))"
        )
        out = subprocess.run([sys.executable, "-I", "-c", script, str(_support.SRC)],
                             capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "[]")


def _strip_docstrings(code):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body[0].value.value = ""
    return ast.unparse(tree)


if __name__ == "__main__":
    unittest.main()
