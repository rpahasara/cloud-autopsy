"""Local demonstration of the CA-P2-005a/006a flow against a disposable synthetic PostgreSQL.

For every synthetic variant it:
  1. persists run A (canonical delivery order) and run B (shuffled, with duplicate
     redeliveries and retry attempts), freezes each run's clock declaration, and seals both,
     through the least-privileged roles;
  2. reads each sealed run back as ``ca_engine`` and produces a verified investigation result
     from the run's own stored clock declaration;
  3. stores result A once as ``ca_result_writer``, retries the store (must be a no-op), and
     loads it back on a *new* ``ca_engine`` connection with full verification on read
     (bindings, clock declaration, re-execution of the engine, byte-identical output);
  4. checks that run A, run B, a replay of run A, the stored-and-replayed bytes and the
     database-free in-memory path are all byte-identical (run IDs are excluded from the digest).
It writes each result as canonical JSON plus a summary, and exits non-zero on any mismatch.

Usage (with a disposable database already running; see db/README.md):
  python -m cloud_autopsy.app.demo --out out/ca-p2-006a
``tools/investigation_demo.py`` starts and removes the database around this in one command.
"""

import argparse
import json
import sys
from pathlib import Path

from ..contracts import canonical
from ..db import results
from ..synthetic import scenario_001 as scenario
from . import pipeline
from .disposable import DisposableDatabase

PERMUTED_SEED = 20261110


def run(database, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, ok = [], True
    for variant in scenario.VARIANTS:
        engine, writer = database.roles["ca_engine"], database.roles["ca_result_writer"]
        run_a, manifest_a, _ = pipeline.persist_and_seal(database.roles, variant)
        run_b, manifest_b, outcomes_b = pipeline.persist_and_seal(database.roles, variant, seed=PERMUTED_SEED)
        stored, investigation = pipeline.record_result(engine, writer, run_a)
        result_a, bytes_a = investigation.result, investigation.result_bytes
        retry, _ = pipeline.record_result(engine, writer, run_a)
        _, bytes_b = pipeline.investigate_run(engine, run_b)
        _, replay_a = pipeline.investigate_run(engine, run_a)
        fresh = database.connect("ca_engine")  # verify on read from a new connection
        verified = pipeline.replay_stored(fresh, run_a)
        fresh.close()
        _, offline = pipeline.offline_result(variant)
        checks = {"manifest_identical": manifest_a == manifest_b, "permutation_identical": bytes_a == bytes_b,
                  "replay_identical": bytes_a == replay_a, "offline_identical": bytes_a == offline,
                  "stored_once": (stored, retry) == (results.STORED, results.IDENTICAL),
                  "stored_replay_identical": verified.result_bytes == bytes_a
                  and verified.result_digest == result_a["result_digest"]}
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
                     "result_digest": result_a["result_digest"], "result_bytes": len(bytes_a),
                     "clock_declaration_digest": result_a["inputs"]["clock_declaration_digest"], **checks})
    summary = {"scope": "synthetic-only local demonstration; developer-authored scenario; not an evaluation",
               "database": {"migrations": database.applied, "engine_role": "ca_engine (sealed-only views)",
                            "result_writer_role": "ca_result_writer (insert-only, write-once)"},
               "all_checks_passed": ok, "variants": rows}
    (out / "summary.json").write_bytes(canonical.canonical_bytes(summary))
    return summary


def _print(summary):
    print(f"{'variant':24} {'manifest':10} {'outcome':9} {'mechanism':23} {'gaps':>4} {'contra':>6}  identical"
          " (perm/replay/offline/stored)  stored+retry  result digest")
    for r in summary["variants"]:
        same = "/".join("yes" if r[k] else "NO" for k in ("permutation_identical", "replay_identical",
                                                           "offline_identical", "stored_replay_identical"))
        print(f"{r['variant']:24} {r['manifest_status']:10} {r['outcome']:9} {str(r['mechanism']):23} "
              f"{r['limiting_gaps']:>4} {r['contradictions']:>6}  {same:35} {'ok' if r['stored_once'] else 'NO':12}  "
              f"{r['result_digest'].split(':')[1][:16]}")
        print(f"{'':24} reasons: {','.join(r['reasons']) or '-'}")
    print("all checks passed" if summary["all_checks_passed"] else "CHECK FAILED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="out/ca-p2-006a")
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
