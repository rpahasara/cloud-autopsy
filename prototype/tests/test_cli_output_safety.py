"""Regression tests for PR #13 P0: demo output cleanup must never delete arbitrary directories."""

import os
import tempfile
import unittest
from pathlib import Path

import cli


class OutputSafetyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.out_root = self.tmp / "out"
        self.out_root.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def victim(self, path):
        path.mkdir(parents=True, exist_ok=True)
        (path / "valuable.txt").write_text("keep me", encoding="utf-8")
        return path

    def assertIntact(self, path):
        self.assertEqual((path / "valuable.txt").read_text(encoding="utf-8"), "keep me")

    def test_directory_outside_output_root_is_refused(self):
        victim = self.victim(self.tmp / "documents")
        with self.assertRaises(cli.UnsafeOutputPath):
            cli.prepare_output_dir(victim, out_root=self.out_root)
        self.assertIntact(victim)

    def test_output_root_itself_and_its_parents_are_refused(self):
        self.victim(self.out_root)
        for path in (self.out_root, self.tmp, self.tmp.parent):
            with self.subTest(path=path), self.assertRaises(cli.UnsafeOutputPath):
                cli.prepare_output_dir(path, out_root=self.out_root)
        self.assertIntact(self.out_root)

    def test_traversal_out_of_root_is_refused(self):
        victim = self.victim(self.tmp / "documents")
        with self.assertRaises(cli.UnsafeOutputPath):
            cli.prepare_output_dir(self.out_root / ".." / "documents", out_root=self.out_root)
        self.assertIntact(victim)

    def test_existing_directory_without_sentinel_is_refused(self):
        victim = self.victim(self.out_root / "demo")
        with self.assertRaises(cli.UnsafeOutputPath):
            cli.prepare_output_dir(victim, out_root=self.out_root)
        self.assertIntact(victim)

    def test_existing_file_is_refused(self):
        target = self.out_root / "demo"
        target.write_text("x", encoding="utf-8")
        with self.assertRaises(cli.UnsafeOutputPath):
            cli.prepare_output_dir(target, out_root=self.out_root)
        self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_symlinked_output_is_refused(self):
        victim = self.victim(self.tmp / "documents")
        link = self.out_root / "demo"
        try:
            os.symlink(victim, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        (victim / cli.OUTPUT_SENTINEL).write_text("forged", encoding="utf-8")
        with self.assertRaises(cli.UnsafeOutputPath):
            cli.prepare_output_dir(link, out_root=self.out_root)
        self.assertIntact(victim)

    def test_junction_in_output_path_is_refused(self):
        try:
            import _winapi
        except ImportError:
            self.skipTest("NTFS junctions are Windows-only")
        victim = self.victim(self.tmp / "documents")
        (victim / cli.OUTPUT_SENTINEL).write_text("forged", encoding="utf-8")
        link = self.out_root / "demo"
        _winapi.CreateJunction(str(victim), str(link))
        for target in (link, link / "nested"):
            with self.subTest(target=target), self.assertRaises(cli.UnsafeOutputPath):
                cli.prepare_output_dir(target, out_root=self.out_root)
        self.assertIntact(victim)
        self.assertFalse((victim / "nested").exists())

    def test_demo_owned_directory_is_recreated(self):
        first = cli.prepare_output_dir(self.out_root / "demo", out_root=self.out_root)
        (first / "stale.json").write_text("{}", encoding="utf-8")
        second = cli.prepare_output_dir(self.out_root / "demo", out_root=self.out_root)
        self.assertEqual(first, second)
        self.assertFalse((second / "stale.json").exists())
        self.assertTrue((second / cli.OUTPUT_SENTINEL).is_file())

    def test_demo_command_refuses_arbitrary_out_before_doing_anything(self):
        victim = self.victim(self.tmp / "documents")
        with self.assertRaises(cli.UnsafeOutputPath):
            cli.main(["demo", "--out", str(victim)])
        self.assertIntact(victim)


if __name__ == "__main__":
    unittest.main()
