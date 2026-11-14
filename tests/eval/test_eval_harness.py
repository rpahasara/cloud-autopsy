"""CA-P2-007a harness: scenario rendering, truth isolation, run records and scoring (offline).

- Each frozen scenario renders from the reviewed manifest by changing only its three declared lines.
- Truth isolation: while a recording is converted, replayed, investigated and evaluated, no file of the
  evaluation's truth (tools/eval/scenarios.json) is opened; no product module refers to it.
- The scorer classifies every case the product owner named (correct, false cause, unsupported resolution,
  necessary and unnecessary abstention, harness failure) and applies the frozen thresholds exactly.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for p in (REPO / "src", REPO / "tools" / "eval", REPO / "tests" / "collector"):
    sys.path.insert(0, str(p))

import scenario as SC  # noqa: E402
import score as S  # noqa: E402

TRUTH = {f.resolve() for f in (REPO / "tools" / "eval").glob("*.json")}   # every scenario file: 0.1, 0.2, matrix


class Rendering(unittest.TestCase):
    def test_every_scenario_changes_only_its_declared_lines(self):
        doc, _ = SC.load()
        base = SC.MANIFEST.read_text(encoding="utf-8").splitlines()
        for s in doc["scenarios"]:
            with self.subTest(scenario=s["id"]):
                rendered = SC.render_manifest(s["initial"]).splitlines()
                changed = [(a, b) for a, b in zip(base, rendered) if a != b]
                self.assertEqual(len(base), len(rendered))
                self.assertLessEqual(len(changed), 3)
                self.assertTrue(all(a in SC.LINES.values() for a, _ in changed))

    def test_the_run_order_interleaves_and_covers_every_repetition(self):
        doc, _ = SC.load()
        order = SC.order(doc)
        self.assertEqual(len(order), sum(s["repetitions"] for s in doc["scenarios"]))
        self.assertEqual(order[:9], [f"{s['id']} 1" for s in doc["scenarios"]])

    def test_the_frozen_thresholds_are_the_approved_ones(self):
        doc, _ = SC.load()
        th = doc["thresholds"]
        self.assertEqual((th["P1"], th["P2"]), ({"min_correct_resolutions": 8, "repetitions": 10},) * 2)
        self.assertEqual((th["false_cause_selections"], th["planted_data_leaks"], th["citation_validity"]), (0, 0, 1.0))
        self.assertEqual({s["id"]: s["repetitions"] for s in doc["scenarios"]},
                         {"P1": 10, "P2": 10, **{f"N{i}": 3 for i in range(1, 8)}})


class TruthIsolation(unittest.TestCase):
    def test_no_product_module_refers_to_the_truth(self):
        for path in (REPO / "src" / "cloud_autopsy").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("scenarios.json", text, path)
            self.assertNotIn("timing-matrix", text, path)
            self.assertNotIn("tools/eval", text, path)

    def test_conversion_investigation_and_evaluation_never_open_the_truth(self):
        import _fake_api as F
        import _fake_podlogs as FL
        import evaluate_run as E
        from cloud_autopsy.collector import collect as co, podlogs as PLC, watch as wt
        tmp = Path(tempfile.mkdtemp(prefix="ca-eval-isolation-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        F.write_token(tmp)
        cluster = FL.LogCluster()
        self.addCleanup(cluster.stop_all)
        opened = []

        def hook(event, args):
            if event == "open" and args and isinstance(args[0], (str, bytes, Path)):
                try:
                    if Path(args[0] if not isinstance(args[0], bytes) else args[0].decode()).resolve() in TRUTH:
                        opened.append(event)
                except (OSError, ValueError):
                    pass
        sys.addaudithook(hook)
        cfg = co.CollectorConfig(server="https://127.0.0.1:6443", ca_file=tmp / "ca", token_file=tmp / "token",
                                 namespace=F.NAMESPACE, cluster_id="ca-kind-synthetic", recording_id="ca-eval-iso")
        co.run_watch(cfg, wt.WatchConfig(session_seconds=2.0, probe_interval_s=0.2, idle_timeout_s=0.5, final_wait_s=1.0),
                     tmp / "out", transport=cluster, rule_profile=3, incident_window=(0, 1), no_events=True,
                     pod_logs=PLC.LogConfig(rotation_s=0.25, drain_wait_s=1.0, idle_timeout_s=1.0))
        (tmp / "steps.txt").write_text("cluster ok\ncollector ok\n", encoding="ascii")
        args = type("A", (), {"scenario": "P1", "repetition": 1, "out": str(tmp / "out"), "steps": str(tmp / "steps.txt"),
                              "db_json": str(tmp / "missing.json"), "token_file": str(tmp / "token"),
                              "started": "2026-11-14T00:00:00Z", "records": str(tmp / "records")})
        record = E.evaluate(args)
        self.assertEqual(opened, [])                            # the truth was never opened
        self.assertEqual(record["harness"], "ok")
        self.assertTrue(record["replay_bundle_rederived"] and record["offline_deterministic"])
        self.assertEqual(record["leaks"], [])
        self.assertEqual(record["citations"]["invalid"], 0)
        self.assertFalse(record["database"]["matches_offline"])  # no database output here: recorded, not assumed


def rec(sid, rep=1, status="resolved", mechanism="rollout_limit_reduction", ns="ca-incident", name="checkout-api",
        change=("pool.maxConnections", "16", "4"), harness="ok"):
    r = {"scenario": sid, "repetition": rep, "harness": harness, "harness_failure": None if harness == "ok" else "cluster",
         "leaks": [], "replay_bundle_rederived": True, "offline_deterministic": True,
         "database": {"matches_offline": True}, "citations": {"invalid": 0},
         "coverage": {"narrowed": True, "narrowing_refused": []},
         "timing": {"rollout_lower_minus_window_start_ms": 30,
                    "rollouts": [{"namespace": ns, "name": name, "field_changes": [list(change)] if change else []}]}}
    if harness == "ok":
        r["outcome"] = {"status": status, "mechanism": mechanism if status == "resolved" else None, "reasons": []}
        r["resolved_change"] = {"mechanism": mechanism, "entity": {"kind": "Deployment", "namespace": ns, "name": name}} \
            if status == "resolved" else None
    return r


class Scoring(unittest.TestCase):
    def setUp(self):
        self.doc, _ = SC.load()
        self.s = {s["id"]: s for s in self.doc["scenarios"]}

    def test_each_classification(self):
        self.assertTrue(S.classify(rec("P1"), self.s["P1"])["correct_resolution"])
        self.assertTrue(S.classify(rec("P1", status="abstained"), self.s["P1"])["unnecessary_abstention"])
        self.assertTrue(S.classify(rec("P1", name="other-api"), self.s["P1"])["false_cause"])     # wrong entity
        self.assertTrue(S.classify(rec("P1", change=("pool.maxConnections", "4", "16")), self.s["P1"])["false_cause"])
        self.assertTrue(S.classify(rec("N1", change=None), self.s["N1"])["false_cause"])         # trap resolved
        self.assertTrue(S.classify(rec("N7", ns="ca-other"), self.s["N7"])["false_cause"])
        self.assertTrue(S.classify(rec("N5"), self.s["N5"])["unsupported_resolution"])             # cause, no evidence
        self.assertTrue(S.classify(rec("N4", status="abstained"), self.s["N4"])["necessary_abstention"])
        failed = S.classify(rec("P2", harness="failed"), self.s["P2"])
        self.assertEqual((failed["actual"], failed["correct_resolution"]), ("harness_failure", False))

    def full(self, p1_correct=10, negative_status="abstained"):
        rows = [S.classify(rec("P1", i, status="resolved" if i <= p1_correct else "abstained"), self.s["P1"])
                for i in range(1, 11)]
        rows += [S.classify(rec("P2", i), self.s["P2"]) for i in range(1, 11)]
        rows += [S.classify(rec(f"N{n}", i, status=negative_status, change=None), self.s[f"N{n}"])
                 for n in range(1, 8) for i in range(1, 4)]
        return S.summarize(rows, self.doc)

    def test_thresholds_are_applied_exactly(self):
        self.assertTrue(self.full()["all_met"])
        self.assertTrue(self.full(p1_correct=8)["criteria"]["P1_correct"]["met"])
        self.assertFalse(self.full(p1_correct=7)["criteria"]["P1_correct"]["met"])
        bad = self.full(negative_status="resolved")
        self.assertFalse(bad["criteria"]["every_negative_abstains"]["met"])
        self.assertFalse(bad["criteria"]["zero_false_causes"]["met"])
        self.assertFalse(bad["all_met"])

    def test_missing_repetitions_and_harness_failures_never_pass(self):
        doc = self.doc
        rows = [S.classify(rec("P1", i), self.s["P1"]) for i in range(1, 9)]   # only 8 of 10 attempted
        self.assertFalse(S.summarize(rows, doc)["criteria"]["P1_correct"]["met"])
        rows = [S.classify(rec("P1", i, harness="failed" if i == 1 else "ok"), self.s["P1"]) for i in range(1, 11)]
        summary = S.summarize(rows, doc)
        self.assertEqual(summary["scenarios"]["P1"]["harness_failures"], 1)
        self.assertFalse(summary["criteria"]["no_harness_failures"]["met"])


class Integrity(unittest.TestCase):
    """CA-P2-007b: scoring refuses anything but exactly the pre-registered run set."""

    def setUp(self):
        self.doc, _ = SC.load()
        self.dir = Path(tempfile.mkdtemp(prefix="ca-eval-integrity-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        lines = []
        for sid, n in sorted(SC.expected_runs(self.doc)):
            self.write(f"{sid}-{n:02d}.json", rec(sid, n))
            lines.append(f"{sid} {n} 2026-11-14T00:00:00Z")
        (self.dir / "attempts.log").write_text("\n".join(lines) + "\n", encoding="ascii")

    def write(self, name, record):
        (self.dir / name).write_text(json.dumps(record), encoding="utf-8")

    def refused(self, fragment):
        with self.assertRaises(S.IntegrityError) as ctx:
            S.check_run_set(self.dir, self.doc)
        self.assertTrue(any(fragment in p for p in ctx.exception.problems), ctx.exception.problems)

    def test_the_exact_run_set_is_accepted(self):
        self.assertEqual(len(S.check_run_set(self.dir, self.doc)), 41)

    def test_a_missing_run_is_refused(self):
        (self.dir / "P1-07.json").unlink()
        self.refused("P1-07: no record")

    def test_a_duplicate_run_is_refused(self):
        self.write("P1-99.json", rec("P1", 7))
        self.refused("P1-07: more than one record")

    def test_an_unexpected_scenario_or_extra_repetition_is_refused(self):
        self.write("X9-01.json", rec("X9", 1))
        self.refused("X9 repetition 1 is not pre-registered")
        (self.dir / "X9-01.json").unlink()
        self.write("N1-04.json", rec("N1", 4))
        self.refused("N1 repetition 4 is not pre-registered")

    def test_a_file_name_disagreeing_with_its_ids_is_refused(self):
        (self.dir / "P2-03.json").rename(self.dir / "P2-04x.json")
        self.refused("file name disagrees")

    def test_a_repeated_attempt_is_refused(self):
        with open(self.dir / "attempts.log", "a", encoding="ascii") as f:
            f.write("P2 5 2026-11-14T01:00:00Z\n")
        self.refused("P2-05: attempted 2 times")

    def test_a_missing_or_incomplete_attempt_log_is_refused(self):
        log = self.dir / "attempts.log"
        kept = [l for l in log.read_text(encoding="ascii").splitlines() if not l.startswith("N7 3 ")]
        log.write_text("\n".join(kept) + "\n", encoding="ascii")
        self.refused("N7-03: pre-registered but never attempted")
        log.unlink()
        self.refused("attempts.log: missing")

    def test_a_record_is_never_overwritten(self):
        import evaluate_run as E
        out = self.dir / "write"
        args = type("A", (), {"scenario": "P1", "repetition": 1, "out": str(self.dir / "none"), "steps": str(self.dir / "none"),
                              "db_json": str(self.dir / "none"), "token_file": str(self.dir / "none"),
                              "started": "x", "records": str(out), "config": None})
        record = E.evaluate(args)
        self.assertEqual(record["harness"], "failed")
        out.mkdir()
        (out / "P1-01.json").write_text("{}", encoding="utf-8")
        argv = ["evaluate_run.py", "--scenario", "P1", "--repetition", "1", "--out", str(self.dir / "none"),
                "--steps", str(self.dir / "none"), "--db-json", str(self.dir / "none"), "--token-file",
                str(self.dir / "none"), "--started", "x", "--records", str(out)]
        old = sys.argv
        sys.argv = argv
        try:
            with self.assertRaises(FileExistsError):
                E.main()
        finally:
            sys.argv = old
        self.assertEqual((out / "P1-01.json").read_text(encoding="utf-8"), "{}")


class Versions(unittest.TestCase):
    def test_the_original_0_1_scenario_file_is_unchanged(self):
        _, digest = SC.load()
        self.assertEqual(digest, "sha256:970f12fc9109da0c2ddef1ef17bd557cc27e01646a399e3b12e67001875d48e9")

    def test_0_2_differs_from_0_1_only_in_its_version_status_and_window_start(self):
        v1, _ = SC.load()
        v2, _ = SC.load(REPO / "tools" / "eval" / "scenarios-0.2.json")
        self.assertEqual(v2["collection"]["incident_window_seconds"], [10, 140])
        for doc in (v1, v2):
            doc.pop("version"), doc.pop("status")
        v2["collection"]["incident_window_seconds"] = v1["collection"]["incident_window_seconds"]
        self.assertEqual(v1, v2)

    def test_every_matrix_cell_renders_with_its_declared_timing_and_a_prediction(self):
        doc, _ = SC.load(REPO / "tools" / "eval" / "timing-matrix-0.1.json")
        tmp = Path(tempfile.mkdtemp(prefix="ca-matrix-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertEqual(len(SC.expected_runs(doc)), 45)
        for s in doc["scenarios"]:
            with self.subTest(cell=s["id"]):
                self.assertTrue(s["prediction"])
                SC.render(doc, s["id"], tmp)
                params = (tmp / "params.env").read_text(encoding="ascii")
                c = s["collection"]
                self.assertIn(f"PROBE_INTERVAL='{c['probe_interval_seconds']}'", params)
                self.assertIn(f"ACTION_AT='{c['action_at_seconds']}'", params)
                self.assertIn(f"WINDOW='{c['incident_window_seconds'][0]}:140'", params)


if __name__ == "__main__":
    unittest.main()
