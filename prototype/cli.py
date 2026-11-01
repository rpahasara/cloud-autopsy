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
PERMUTE_SEED = 20261101
DEMO_BUDGET_S = 300
DEFAULT_SCALE_RECORDS = 10000


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
    src = out / "runs" / "A"

    ev_dir = tamper / "evidence-edited"
    shutil.copytree(src, ev_dir)
    store = FileArtifactStore(ev_dir)
    records = store.get("evidence.json")
    records[0]["attributes"]["tampered"] = "yes"
    store.put("evidence.json", records)
    _check(checks, "replay detects edited evidence", "integrity_mismatch", replay(store)["state"])

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


def demo(args):
    started = perf_counter_ns()
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    checks = []

    verify_fixture_dir(FIXTURES)
    truth, truth_digest = load_truth(ROOT, FIXTURE_ID)

    runs, equivalence, replays = {}, {}, {}
    for v in VARIANTS:
        scenario = load_scenario(FIXTURES, v)
        first = run_investigation(scenario, FileArtifactStore(out / "runs" / v))
        second = run_investigation(scenario, FileArtifactStore(out / "runs" / f"{v}-permuted"),
                                   permute_seed=PERMUTE_SEED, duplicate_delivery=True)
        runs[v] = first
        equivalence[v] = {"method": "repeat with permuted and duplicated delivery",
                          "eligible_pairs": 1,
                          "equivalent_pairs": int(first["bundle_digest"] == second["bundle_digest"] and
                                                  first["manifest_digest"] == second["manifest_digest"])}
        replays[v] = replay(FileArtifactStore(out / "runs" / v))
        _check(checks, f"{v}: permuted/duplicated delivery equivalent", 1, equivalence[v]["equivalent_pairs"])
        _check(checks, f"{v}: retained-input replay", "equivalent", replays[v]["state"])

    seeds = {seed: _hashseed_digest(seed, out / "hashseed" / str(seed)) for seed in (0, 4242)}
    for seed, value in seeds.items():
        _check(checks, f"A: bundle digest under PYTHONHASHSEED={seed}", runs["A"]["bundle_digest"], value)

    _tamper_checks(out, checks)

    ref = {v: r["bundle_digest"] for v, r in runs.items()}
    reports = [score_run(FileArtifactStore(out / "runs" / v), truth, truth_digest, equivalence[v], ref)
               for v in VARIANTS]
    summary = summarize(reports)

    scale_records = args.scale_records
    scale_run = run_investigation(load_scenario(FIXTURES, "A"), FileArtifactStore(out / "runs" / "A-scale"),
                                  extra_observations=scale_filler(scale_records))
    scale_bytes = len(canonical_bytes(scale_filler(scale_records)))
    elapsed_s = (perf_counter_ns() - started) / 1e9

    performance = {
        "objective": "exploratory: full demo completes within 5 minutes on the declared local workload "
                     "(not a product SLA or CA-DEC-007 budget)",
        "declared_workload": {
            "variants": len(VARIANTS), "runs_per_variant": 2, "hashseed_subprocess_runs": len(seeds),
            "tamper_cases": 5,
            "scale_run": {"base_variant": "A", "filler_metric_samples": scale_records,
                          "filler_canonical_bytes": scale_bytes,
                          "evidence_records": scale_run["workload"]["evidence_records"]},
        },
        "bundle_assembly_ms": {v: round(r["stage_timings_ns"]["bundle_assembly_total_ns"] / 1e6, 3)
                               for v, r in runs.items()},
        "scale_bundle_assembly_ms": round(scale_run["stage_timings_ns"]["bundle_assembly_total_ns"] / 1e6, 3),
        "demo_total_s": round(elapsed_s, 3),
        "within_5_minutes": elapsed_s <= DEMO_BUDGET_S,
        "environment": {"python": sys.version.split()[0], "platform": sys.platform, "cpu_count": os.cpu_count()},
    }
    _check(checks, "demo completed within 5 minutes", True, performance["within_5_minutes"])

    report = {"report_version": "ca-demo-report/0.1-spike", "approval_status": "not_approved",
              "gate_eligible": False, "truth_digest": truth_digest, "summary": summary,
              "variants": reports, "replays": replays, "harness_checks": checks, "performance": performance}
    (out / "demo-report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    _print_demo(report, out)
    return 0 if all(c["ok"] for c in checks) else 1


def _print_demo(report, out):
    print("CA-SPIKE-001 offline demo - exploratory, not approved, not gate evidence\n")
    print(f"{'var':3} {'engine':10} {'engine cause':12} {'false cause':11} | {'baseline':9} "
          f"{'baseline cause':14} {'false cause':11} | {'run state':22} {'synthesis':10} {'policy':6}")
    for r in report["variants"]:
        e, b = r["engine"], r["baseline"]
        print(f"{r['variant']:3} {e['outcome']:10} {e['causal_attribution']:12} {e['false_cause']:11} | "
              f"{b['outcome']:9} {b['causal_attribution']:14} {b['false_cause']:11} | "
              f"{e['run_state']:22} {r['security']['synthesis_status']:10} {r['security']['policy_result']:6}")
    print()
    for method in ("engine", "baseline"):
        s = report["summary"][method]
        print(f"{method:8}: result correct {s['result_correct']['value']}, "
              f"correct cause {s['correct_cause_on_resolvable']['value']}, "
              f"false cause selected {s['false_cause_selected']['value']}, "
              f"correct abstention {s['correct_abstention_on_unresolvable']['value']}")
    d = next(r for r in report["variants"] if r["variant"] == "D")["clock"]
    print(f"clock-order checks (D): {d['matched']['value']}")
    p = report["performance"]
    print(f"\nbundle assembly ms per variant: {p['bundle_assembly_ms']}")
    print(f"scale run ({p['declared_workload']['scale_run']['evidence_records']} evidence records): "
          f"{p['scale_bundle_assembly_ms']} ms; demo total {p['demo_total_s']} s; "
          f"within 5 minutes: {p['within_5_minutes']}")
    failed = [c for c in report["harness_checks"] if not c["ok"]]
    print(f"harness self-checks: {len(report['harness_checks']) - len(failed)}/{len(report['harness_checks'])} ok")
    for c in failed:
        print(f"  FAILED {c['check']}: expected {c['expected']!r}, got {c['actual']!r}")
    print(f"\nreport: {out / 'demo-report.json'}")


def cmd_run(args):
    scenario = load_scenario(FIXTURES, args.variant)
    out = Path(args.out) / args.variant
    run = run_investigation(scenario, FileArtifactStore(out), permute_seed=args.permute_seed)
    print(json.dumps({k: run[k] for k in ("variant", "state", "bundle_digest", "manifest_digest")}, indent=1))
    print(f"artifacts: {out}")
    return 0


def cmd_replay(args):
    result = replay(FileArtifactStore(args.run_dir))
    print(json.dumps(result, indent=1))
    return 0 if result["state"] == "equivalent" else 1


def cmd_score(args):
    truth, truth_digest = load_truth(ROOT, FIXTURE_ID)
    print(json.dumps(score_run(FileArtifactStore(args.run_dir), truth, truth_digest), indent=1, sort_keys=True))
    return 0


def cmd_verify(_args):
    manifest = verify_fixture_dir(FIXTURES)
    _, truth_digest = load_truth(ROOT, FIXTURE_ID)
    print(f"fixtures ok: {len(manifest['files'])} files; truth pin ok: {truth_digest}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("demo", help="run all variants, equivalence, replay, tamper, scoring and timing")
    p.add_argument("--out", default=str(ROOT / "out" / "demo"))
    p.add_argument("--scale-records", type=int, default=DEFAULT_SCALE_RECORDS)
    p.set_defaults(func=demo)
    p = sub.add_parser("run", help="run one variant")
    p.add_argument("--variant", choices=VARIANTS, required=True)
    p.add_argument("--out", default=str(ROOT / "out" / "runs"))
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
