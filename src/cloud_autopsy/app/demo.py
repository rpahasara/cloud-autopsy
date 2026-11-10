"""Local demonstration of the whole CA-P2-005a flow against a disposable synthetic PostgreSQL.

For every synthetic variant it:
  1. persists and seals run A (canonical delivery order) and run B (shuffled, with duplicate
     redeliveries and retry attempts) through the least-privileged roles;
  2. reads each sealed run back as ``ca_engine`` and produces a verified investigation result;
  3. checks that run A, run B, a replay of run A and the database-free in-memory path all give
     byte-identical results (run IDs are excluded from the result digest).
It writes each result as canonical JSON plus a summary, and exits non-zero on any mismatch.

Usage (with a disposable database already running; see db/README.md):
  python -m cloud_autopsy.app.demo --out out/ca-p2-005a
``tools/investigation_demo.py`` starts and removes the database around this in one command.
"""

import argparse
import json
import sys
from pathlib import Path

from ..contracts import canonical
from ..synthetic import scenario_001 as scenario
from . import pipeline
from .disposable import DisposableDatabase

PERMUTED_SEED = 20261110


def run(database, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, ok = [], True
    for variant in scenario.VARIANTS:
        domains = scenario.clock_domain_records(variant)
        run_a, manifest_a, _ = pipeline.persist_and_seal(database.roles, variant)
        run_b, manifest_b, outcomes_b = pipeline.persist_and_seal(database.roles, variant, seed=PERMUTED_SEED)
        result_a, bytes_a = pipeline.investigate_run(database.roles["ca_engine"], run_a, domains)
        _, bytes_b = pipeline.investigate_run(database.roles["ca_engine"], run_b, domains)
        _, replay_a = pipeline.investigate_run(database.roles["ca_engine"], run_a, domains)
        _, offline = pipeline.offline_result(variant)
        checks = {"manifest_identical": manifest_a == manifest_b, "permutation_identical": bytes_a == bytes_b,
                  "replay_identical": bytes_a == replay_a, "offline_identical": bytes_a == offline}
        ok &= all(checks.values())
        (out / f"{variant}.result.json").write_bytes(bytes_a)
        outcome = result_a["outcome"]
        rows.append({"variant": variant, "manifest_status": result_a["inputs"]["manifest_status"],
                     "manifest_digest": result_a["inputs"]["manifest_digest"],
                     "outcome": outcome["status"], "mechanism": outcome["mechanism"],
                     "reasons": outcome["reasons"], "cited_evidence": len(outcome["evidence_ids"]),
                     "limiting_gaps": len(outcome["gap_ids"]),
                     "hypotheses": {h["mechanism"] + ("" if h["change_evidence_id"] else ":unobserved"): h["status"]
                                    for h in result_a["hypotheses"]},
                     "contradictions": sum(len(h["contradictions"]) for h in result_a["hypotheses"]),
                     "permuted_ingest_outcomes": sorted(outcomes_b),
                     "result_digest": result_a["result_digest"], "result_bytes": len(bytes_a), **checks})
    summary = {"scope": "synthetic-only local demonstration; developer-authored scenario; not an evaluation",
               "database": {"migrations": database.applied, "engine_role": "ca_engine (sealed-only views)"},
               "all_checks_passed": ok, "variants": rows}
    (out / "summary.json").write_bytes(canonical.canonical_bytes(summary))
    return summary


def _print(summary):
    print(f"{'variant':24} {'manifest':10} {'outcome':9} {'mechanism':23} {'gaps':>4} {'contra':>6}  identical"
          " (perm/replay/offline)  reasons")
    for r in summary["variants"]:
        same = "/".join("yes" if r[k] else "NO" for k in ("permutation_identical", "replay_identical",
                                                           "offline_identical"))
        print(f"{r['variant']:24} {r['manifest_status']:10} {r['outcome']:9} {str(r['mechanism']):23} "
              f"{r['limiting_gaps']:>4} {r['contradictions']:>6}  {same:28} {','.join(r['reasons'])}")
    print("all checks passed" if summary["all_checks_passed"] else "CHECK FAILED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="out/ca-p2-005a")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    with DisposableDatabase.from_environment() as database:
        summary = run(database, args.out)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print(summary)
    return 0 if summary["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
