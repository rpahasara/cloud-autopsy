"""Ground-truth isolation, no network/execution surface, and fixture hygiene."""

import ast
import builtins
import json
import pathlib
import unittest
from unittest import mock

from ca_spike.fixtures import load_scenario, read_json
from tests.helpers import FIXTURES, ROOT, RunTestCase

ENGINE_DIR = ROOT / "ca_spike"
FORBIDDEN_MODULES = {"ca_eval", "socket", "ssl", "http", "urllib", "requests", "subprocess", "ftplib", "smtplib",
                     "asyncio", "multiprocessing", "ctypes"}


class IsolationTests(RunTestCase):
    def test_engine_imports_no_evaluator_network_or_execution_modules(self):
        for path in sorted(ENGINE_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for name in names:
                    self.assertNotIn(name.split(".")[0], FORBIDDEN_MODULES, f"{path.name} imports {name}")
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("eval", "exec", "compile"):
                    self.fail(f"{path.name} calls {node.func.id}")

    def test_engine_refuses_truth_paths(self):
        with self.assertRaises(PermissionError):
            read_json(ROOT / "truth" / "ca-scenario-001" / "ground-truth.json")
        with self.assertRaises(PermissionError):
            load_scenario(ROOT / "truth" / "ca-scenario-001", "A")

    def test_no_truth_file_is_opened_during_a_run(self):
        opened = []
        real_open, real_read = builtins.open, pathlib.Path.read_bytes

        def spy_open(file, *a, **k):
            opened.append(str(file))
            return real_open(file, *a, **k)

        def spy_read(self_path):
            opened.append(str(self_path))
            return real_read(self_path)

        with mock.patch("builtins.open", spy_open), mock.patch.object(pathlib.Path, "read_bytes", spy_read):
            for v in "ABCDE":
                self.run_variant(v)
        self.assertTrue(opened)
        self.assertFalse([p for p in opened if "truth" in pathlib.Path(p).parts])

    def test_fixtures_carry_no_truth_labels(self):
        banned = {"ground_truth", "expected_cause", "expected_outcome", "causal_change", "false_cause",
                  "distractor", "is_cause", "root_cause"}

        def keys(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield k
                    yield from keys(v)
            elif isinstance(value, list):
                for v in value:
                    yield from keys(v)

        for path in FIXTURES.rglob("*.json"):
            found = banned & set(keys(json.loads(path.read_bytes())))
            self.assertFalse(found, f"{path.name}: {found}")

    def test_fixtures_contain_no_secret_like_material(self):
        text = "\n".join(p.read_text(encoding="utf-8") for p in FIXTURES.rglob("*.json")).lower()
        for marker in ("password", "secret_key", "api_key", "token=", "-----begin", "aws_access_key"):
            self.assertNotIn(marker, text)

    def test_engine_output_has_no_action_surface(self):
        prohibited = {"action", "actions", "command", "commands", "tool_calls", "approval", "approved"}
        for v in "ABCDE":
            _, store, bundle = self.run_variant(v)
            found = []

            def scan(value):
                if isinstance(value, dict):
                    found.extend(k for k in value if k.lower() in prohibited)
                    for x in value.values():
                        scan(x)
                elif isinstance(value, list):
                    for x in value:
                        scan(x)

            scan(bundle)
            scan(store.get("run.json"))
            self.assertEqual(found, [], v)
            self.assertEqual(store.get("run.json")["approval_status"], "not_approved")


if __name__ == "__main__":
    unittest.main()
