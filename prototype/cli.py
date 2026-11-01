"""CA-SPIKE-001 harness CLI: run, replay, score and the end-to-end offline demo.

The harness is the only place that wires the engine (ca_spike) to the evaluator
(ca_eval). The engine itself never imports the evaluator or reads ground truth.

    python prototype/cli.py demo
    python prototype/cli.py run --variant A
    python prototype/cli.py replay prototype/out/runs/A
    python prototype/cli.py score prototype/out/runs/A
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ca_eval.scorer import TruthIntegrityError, load_truth, score_run, summarize  # noqa: E402
from ca_spike.canonical import canonical_bytes  # noqa: E402
from ca_spike.fixtures import FixtureIntegrityError, load_scenario, verify_fixture_dir  # noqa: E402
from ca_spike.pipeline import replay, run_investigation  # noqa: E402
from ca_spike.store import FileArtifactStore  # noqa: E402

FIXTURE_ID = "ca-scenario-001"
FIXTURES = ROOT / "fixtures" / FIXTURE_ID
VARIANTS = ("A", "B", "C", "D", "E")
FAMILIES = ((FIXTURE_ID, VARIANTS), ("cx-deploy-cause", ("A",)), ("cx-benign", ("A",)))
PERMUTE_SEED = 20261101
DEMO_BUDGET_S = 300
DEFAULT_SCALE_RECORDS = 10000
OUT_ROOT = ROOT / "out"
OUTPUT_SENTINEL = ".ca-spike-demo-output"


def scale_filler(count):
    """Deterministic synthetic metric samples used only to load the assembler."""
    samples = []
    for i in range(count):
        ts = f"2026-10-15T08:{i // 60000 % 20:02d}:{i // 1000 % 60:02d}.{i % 1000:03d}Z"
        samples.append({
            "source_ref": f"prom:checkout_api:latency_p99{{shard={i % 16}}}@{ts}#{i}",
            "observation_kind": "metric_sample",
            "source_uid": f"series:checkout_api:latency_p99{{shard={i % 16}}}", "source_version": f"{ts}#{i}",
            "entity": {"kind": "Service", "namespace": "ca-demo", "name": "checkout-api"},
            "times": [{"type": "event", "raw": ts, "clock_domain": "prometheus"}],
            "attributes": {"series": "checkout_api:latency_p99", "labels": f"shard={i % 16}",
                           "value": str(120 + i % 37)},
        })
    return [{"query_id": "prom.scale-filler", "source_id": "prometheus",
             "window": {"start": "2026-10-15T08:00:00Z", "end": "2026-10-15T08:20:00Z"},
             "status": "complete", "observations": samples}]


def _check(checks, name, expected, actual):
    checks.append({"check": name, "expected": expected, "actual": actual, "ok": expected == actual})


def _hashseed_digest(seed, out_dir):
    code = ("import sys; sys.path.insert(0, sys.argv[1]);"
            "from ca_spike.fixtures import load_scenario; from ca_spike.pipeline import run_investigation;"
            "from ca_spike.store import FileArtifactStore;"
            "print(run_investigation(load_scenario(sys.argv[2], 'A'), FileArtifactStore(sys.argv[3]))['bundle_digest'])")
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    result = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT), str(FIXTURES), str(out_dir)],
                            env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _tamper_checks(out, checks):
    tamper = out / "tamper"
    src = out / "runs" / FIXTURE_ID / "A"

    ev_dir = tamper / "evidence-edited"
    shutil.copytree(src, ev_dir)
    store = FileArtifactStore(ev_dir)
    records = store.get("evidence.json")
    records[0]["attributes"]["tampered"] = "yes"
    store.put("evidence.json", records)
    _check(checks, "replay detects edited evidence", "integrity_mismatch", replay(store)["state"])

    derived_dir = tamper / "derived-field-edited"
    shutil.copytree(src, derived_dir)
    store = FileArtifactStore(derived_dir)
    records = store.get("evidence.json")
    bounded = next(t for r in records for t in r["times"] if t["lower_ms"] is not None)
    bounded["lower_ms"] -= 60000
    store.put("evidence.json", records)
    _check(checks, "replay detects edited derived interval bound", "integrity_mismatch", replay(store)["state"])

    in_dir = tamper / "inputs-edited"
    shutil.copytree(src, in_dir)
    store = FileArtifactStore(in_dir)
    inputs = store.get("inputs.json")
    inputs["deliveries"][0]["observation"]["source_version"] += "-x"
    store.put("inputs.json", inputs)
    _check(checks, "replay detects edited retained inputs", "integrity_mismatch", replay(store)["state"])

    miss_dir = tamper / "inputs-missing"
    shutil.copytree(src, miss_dir)
    (miss_dir / "inputs.json").unlink()
    _check(checks, "replay reports missing input", "missing_unexplained",
           replay(FileArtifactStore(miss_dir))["state"])

    fx = tamper / "fixtures"
    shutil.copytree(FIXTURES, fx, ignore=shutil.ignore_patterns("*.md"))  # keep repo doc validators clean
    with open(fx / "observations.json", "ab") as fh:
        fh.write(b" ")
    try:
        verify_fixture_dir(fx)
        detected = False
    except FixtureIntegrityError:
        detected = True
    _check(checks, "fixture tamper detected", True, detected)

    truth_root = tamper / "truth-root"
    shutil.copytree(ROOT / "truth", truth_root / "truth")
    (truth_root / "ca_eval").mkdir(parents=True)
    shutil.copy(ROOT / "ca_eval" / "truth-pins.json", truth_root / "ca_eval" / "truth-pins.json")
    truth_file = truth_root / "truth" / FIXTURE_ID / "ground-truth.json"
    truth_file.write_bytes(truth_file.read_bytes().replace(b'"expected_outcome": "abstained"',
                                                           b'"expected_outcome": "resolved"'))
    try:
        load_truth(truth_root, FIXTURE_ID)
        detected = False
    except TruthIntegrityError:
        detected = True
    _check(checks, "ground-truth tamper detected", True, detected)


class UnsafeOutputPath(ValueError):
    pass


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def prepare_output_dir(requested, out_root=OUT_ROOT):
    """Return a fresh demo output directory, deleting only a prior demo-owned directory.

    The directory must be a strict descendant of ``out_root`` (no traversal), no path
    component from ``out_root`` down may be a symlink or junction, and an existing
    directory is removed only if it carries the sentinel written by a previous demo.
    """
    root = Path(out_root).absolute()
    path = Path(os.path.abspath(requested))  # normalizes '..' lexically, without following links
    if _is_link(root):
        raise UnsafeOutputPath(f"output root is a link: {root}")
    if path == root or root not in path.parents:
        raise UnsafeOutputPath(f"demo output must be a subdirectory of {root}: {path}")
    probe = path
    while probe != root:
        if _is_link(probe):
            raise UnsafeOutputPath(f"symlink or junction in output path: {probe}")
        probe = probe.parent
    resolved_root = root.resolve()
    if path.resolve() == resolved_root or resolved_root not in path.resolve().parents:
        raise UnsafeOutputPath(f"output path escapes {resolved_root}: {path}")
    if path.exists():
        if not path.is_dir():
            raise UnsafeOutputPath(f"output path is not a directory: {path}")
        if not (path / OUTPUT_SENTINEL).is_file():
            raise UnsafeOutputPath(f"refusing to delete a directory the demo did not create: {path} "
                                   f"(run `make clean-demo` to remove old prototype/out output)")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    (path / OUTPUT_SENTINEL).write_text("created by prototype/cli.py demo; safe to delete\n", encoding="utf-8")
    return path


def demo(args):
    started = perf_counter_ns()
    out = prepare_output_dir(args.out)
    checks = []

    runs, equivalence, replays, reports, by_family = {}, {}, {}, [], {}
    for fixture_id, variants in FAMILIES:
        fixture_dir = ROOT / "fixtures" / fixture_id
        verify_fixture_dir(fixture_dir)
        truth, truth_digest = load_truth(ROOT, fixture_id)
        ref = {}
        for v in variants:
            key = f"{fixture_id}/{v}"
            scenario = load_scenario(fixture_dir, v)
            first = run_investigation(scenario, FileArtifactStore(out / "runs" / fixture_id / v))
            second = run_investigation(scenario, FileArtifactStore(out / "runs" / fixture_id / f"{v}-permuted"),
                                       permute_seed=PERMUTE_SEED, duplicate_delivery=True)
            runs[key] = first
            ref[v] = first["bundle_digest"]
            equivalence[key] = {"method": "repeat with permuted and duplicated delivery", "eligible_pairs": 1,
                                "equivalent_pairs": int(first["bundle_digest"] == second["bundle_digest"] and
                                                        first["manifest_digest"] == second["manifest_digest"])}
            replays[key] = replay(FileArtifactStore(out / "runs" / fixture_id / v))
            _check(checks, f"{key}: permuted/duplicated delivery equivalent", 1, equivalence[key]["equivalent_pairs"])
            _check(checks, f"{key}: retained-input replay", "equivalent", replays[key]["state"])
        family_reports = [score_run(FileArtifactStore(out / "runs" / fixture_id / v), truth, truth_digest,
                                    equivalence[f"{fixture_id}/{v}"], ref) for v in variants]
        by_family[fixture_id] = {"truth_digest": truth_digest, "summary": summarize(family_reports)}
        reports += family_reports

    seeds = {seed: _hashseed_digest(seed, out / "hashseed" / str(seed)) for seed in (0, 4242)}
    for seed, value in seeds.items():
        _check(checks, f"{FIXTURE_ID}/A: bundle digest under PYTHONHASHSEED={seed}",
               runs[f"{FIXTURE_ID}/A"]["bundle_digest"], value)

    _tamper_checks(out, checks)

    scale_records = args.scale_records
    scale_run = run_investigation(load_scenario(FIXTURES, "A"), FileArtifactStore(out / "runs" / "A-scale"),
                                  extra_observations=scale_filler(scale_records))
    scale_bytes = len(canonical_bytes(scale_filler(scale_records)))
    elapsed_s = (perf_counter_ns() - started) / 1e9

    performance = {
        "objective": "exploratory: full demo completes within 5 minutes on the declared local workload "
                     "(not a product SLA or CA-DEC-007 budget)",
        "declared_workload": {
            "families": {f: len(v) for f, v in FAMILIES}, "runs_per_variant": 2,
            "hashseed_subprocess_runs": len(seeds), "tamper_cases": 6,
            "scale_run": {"base_variant": f"{FIXTURE_ID}/A", "filler_metric_samples": scale_records,
                          "filler_canonical_bytes": scale_bytes,
                          "evidence_records": scale_run["workload"]["evidence_records"]},
        },
        "bundle_assembly_ms": {k: round(r["stage_timings_ns"]["bundle_assembly_total_ns"] / 1e6, 3)
                               for k, r in runs.items()},
        "scale_bundle_assembly_ms": round(scale_run["stage_timings_ns"]["bundle_assembly_total_ns"] / 1e6, 3),
        "demo_total_s": round(elapsed_s, 3),
        "within_5_minutes": elapsed_s <= DEMO_BUDGET_S,
        "environment": {"python": sys.version.split()[0], "platform": sys.platform, "cpu_count": os.cpu_count()},
    }
    _check(checks, "demo completed within 5 minutes", True, performance["within_5_minutes"])

    report = {"report_version": "ca-demo-report/0.2-spike", "approval_status": "not_approved",
              "gate_eligible": False,
              "independence": "All fixtures, truth, rules and scorer are developer-authored; counterexamples are "
                              "regression cases, not independent or held-out evaluation.",
              "summary": summarize(reports), "families": by_family, "runs": reports, "replays": replays,
              "harness_checks": checks, "performance": performance}
    (out / "demo-report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    _print_demo(report, out)
    return 0 if all(c["ok"] for c in checks) else 1


def _print_demo(report, out):
    print("CA-SPIKE-001 offline demo - exploratory, developer-authored, not approved, not gate evidence\n")
    print(f"{'run':19} {'engine':10} {'engine cause':12} {'false cause':11} | {'baseline':9} "
          f"{'baseline cause':14} {'false cause':12} | {'run state':22} {'synthesis':10} {'policy':6}")
    for r in report["runs"]:
        e, b = r["engine"], r["baseline"]
        print(f"{r['fixture_id'] + '/' + r['variant']:19} {e['outcome']:10} {e['causal_attribution']:12} "
              f"{e['false_cause']:11} | {b['outcome']:9} {b['causal_attribution']:14} {b['false_cause']:12} | "
              f"{e['run_state']:22} {r['security']['synthesis_status']:10} {r['security']['policy_result']:6}")
    print()
    for label, summary in [("all runs", report["summary"])] + [(f, v["summary"]) for f, v in report["families"].items()]:
        print(f"[{label}]")
        for method in ("engine", "baseline"):
            s = summary[method]
            print(f"  {method:8}: result correct {s['result_correct']['value']}, "
                  f"correct cause {s['correct_cause_on_resolvable']['value']}, "
                  f"false cause selected {s['false_cause_selected']['value']} (identity-verifiable traps; "
                  f"unverifiable {s['false_cause_identity_unverifiable']['value']}), "
                  f"correct abstention {s['correct_abstention_on_unresolvable']['value']}, "
                  f"change identity unverifiable {s['change_identity_unverifiable']['value']}")
    d = next(r for r in report["runs"] if r["fixture_id"] == FIXTURE_ID and r["variant"] == "D")["clock"]
    print(f"clock-order checks ({FIXTURE_ID}/D): {d['matched']['value']}")
    p = report["performance"]
    print(f"\nbundle assembly ms: {p['bundle_assembly_ms']}")
    print(f"scale run ({p['declared_workload']['scale_run']['evidence_records']} evidence records): "
          f"{p['scale_bundle_assembly_ms']} ms; demo total {p['demo_total_s']} s; "
          f"within 5 minutes: {p['within_5_minutes']}")
    failed = [c for c in report["harness_checks"] if not c["ok"]]
    print(f"harness self-checks: {len(report['harness_checks']) - len(failed)}/{len(report['harness_checks'])} ok")
    for c in failed:
        print(f"  FAILED {c['check']}: expected {c['expected']!r}, got {c['actual']!r}")
    print(f"\n{report['independence']}")
    print(f"report: {out / 'demo-report.json'}")


def cmd_run(args):
    scenario = load_scenario(ROOT / "fixtures" / args.fixture, args.variant)
    out = Path(args.out) / args.fixture / args.variant
    run = run_investigation(scenario, FileArtifactStore(out), permute_seed=args.permute_seed)
    print(json.dumps({k: run[k] for k in ("fixture_id", "variant", "state", "bundle_digest", "manifest_digest")},
                     indent=1))
    print(f"artifacts: {out}")
    return 0


def cmd_replay(args):
    result = replay(FileArtifactStore(args.run_dir))
    print(json.dumps(result, indent=1))
    return 0 if result["state"] == "equivalent" else 1


def cmd_score(args):
    store = FileArtifactStore(args.run_dir)
    truth, truth_digest = load_truth(ROOT, store.get("run.json")["fixture_id"])
    print(json.dumps(score_run(store, truth, truth_digest), indent=1, sort_keys=True))
    return 0


def cmd_verify(_args):
    for fixture_id, _variants in FAMILIES:
        manifest = verify_fixture_dir(ROOT / "fixtures" / fixture_id)
        _, truth_digest = load_truth(ROOT, fixture_id)
        print(f"{fixture_id}: fixtures ok ({len(manifest['files'])} files); truth pin ok: {truth_digest}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("demo", help="run all variants, equivalence, replay, tamper, scoring and timing")
    p.add_argument("--out", default=str(OUT_ROOT / "demo"),
                   help="must be a subdirectory of prototype/out; only demo-created directories are replaced")
    p.add_argument("--scale-records", type=int, default=DEFAULT_SCALE_RECORDS)
    p.set_defaults(func=demo)
    p = sub.add_parser("run", help="run one variant")
    p.add_argument("--fixture", choices=[f for f, _ in FAMILIES], default=FIXTURE_ID)
    p.add_argument("--variant", choices=VARIANTS, required=True)
    p.add_argument("--out", default=str(OUT_ROOT / "runs"))
    p.add_argument("--permute-seed", type=int)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("replay", help="verify and replay a run directory from retained inputs")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_replay)
    p = sub.add_parser("score", help="score a run directory against pinned ground truth")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_score)
    sub.add_parser("verify-fixtures", help="verify fixture and truth digests").set_defaults(func=cmd_verify)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
