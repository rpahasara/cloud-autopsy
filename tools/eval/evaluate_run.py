"""CA-P2-007a: extract the facts of one repetition into a run record (never reads the scenario truth).

  evaluate_run.py --scenario ID --repetition N --out DIR --steps FILE --db-json FILE --token-file FILE
                  --started ISO --records DIR

The record holds only what the run produced: harness step statuses, the offline and database outcomes, replay
checks, citation checks, a planted-data scan, coverage facts and timing facts. Scoring against the frozen truth
happens later, in score.py. A run that produced nothing still gets a record, so no attempt is ever lost.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "kind"))

from cloud_autopsy.app import bundle as B  # noqa: E402
from cloud_autopsy.app import create as C  # noqa: E402
from cloud_autopsy.app import k8s_watch_recording as W  # noqa: E402
from cloud_autopsy.contracts import timeinterval as ti  # noqa: E402

RECORD_VERSION = "ca-eval-run/0.1-provisional"


def _planted():
    import kind_checks as KC   # the needles the kind jobs already scan for
    return tuple(KC.PLANTED) + tuple(KC.LOG_PLANTED)


def _steps(path):
    out = {}
    try:
        for line in Path(path).read_text(encoding="ascii").splitlines():
            name, _, status = line.partition(" ")
            out[name] = status
    except OSError:
        pass
    return out


def _leaks(out, token):
    needles = [n.encode() for n in _planted()] + ([token.encode()] if token else [])
    found = []
    for path in sorted(Path(out).rglob("*")) if Path(out).is_dir() else []:
        if path.is_file():
            data = path.read_bytes()
            found += sorted({f"{path.name}:{n.decode()[:12]}" for n in needles if n in data})
    return found


def _bracket(observation, domain):
    for t in observation["times"]:
        if t["timestamp_kind"] == "observed" and t["clock_domain_id"] == domain:
            s = ti.source_timestamp(t["raw"], timestamp_kind="observed", clock_domain_id=domain,
                                    declared_precision_ns=t["declared_precision_ns"])
            return [s.local_lower_ms, s.local_upper_ms]
    return None


def evaluate(args):
    record = {"record_version": RECORD_VERSION, "scenario": args.scenario, "repetition": args.repetition,
              "started": args.started, "steps": _steps(args.steps), "harness": "ok", "harness_failure": None}
    failed = [k for k, v in record["steps"].items() if v != "ok"]
    out = Path(args.out)
    if failed:
        record["harness"], record["harness_failure"] = "failed", failed[0]
    if not (out / "bundle").is_dir() or not (out / "recording").is_dir():
        record["harness"] = "failed"
        record["harness_failure"] = record["harness_failure"] or "no_bundle"
        return record
    token = Path(args.token_file).read_text(encoding="ascii").strip() if Path(args.token_file).is_file() else ""
    record["leaks"] = _leaks(out, token)

    try:
        conversion = W.verify_bundle(out / "recording", out / "bundle")
        record["replay_bundle_rederived"] = True
    except Exception as exc:  # noqa: BLE001 -- recorded, never hidden
        record["replay_bundle_rederived"] = False
        record["replay_error"] = getattr(exc, "code", type(exc).__name__)
        return record
    loaded = B.load(out / "bundle")
    first, second = C.investigate_offline(loaded), C.investigate_offline(B.load(out / "bundle"))
    record["offline_deterministic"] = first.result_bytes == second.result_bytes
    result = first.result
    outcome = result["outcome"]
    record["offline_result_sha256"] = hashlib.sha256(first.result_bytes).hexdigest()
    record["outcome"] = {"status": outcome["status"], "mechanism": outcome["mechanism"],
                         "reasons": outcome["reasons"], "cited": len(outcome["evidence_ids"])}
    hypothesis = next((h for h in result["hypotheses"] if h["hypothesis_id"] == outcome.get("hypothesis_id")), None)
    record["resolved_change"] = None
    if hypothesis is not None:
        record["resolved_change"] = {"mechanism": hypothesis["mechanism"], "entity": hypothesis["entity"]}
    timeline_ids = {e["evidence_id"] for e in result["timeline"]["entries"]}
    cited = set(outcome["evidence_ids"]) | {i for h in result["hypotheses"] for p in h["prerequisites"]
                                            for i in p["evidence_ids"]}
    record["citations"] = {"cited": len(cited), "invalid": len(cited - timeline_ids)}

    report = conversion.report
    manifest = json.loads((out / "recording" / "recording.json").read_bytes())
    domain = manifest["clocks"]["collector"]["clock_domain_id"]
    intervals = report.get("intervals") or {}
    logs = report.get("pod_logs") or {}
    record["coverage"] = {
        "recording_version": manifest["contract_version"], "not_collected": report.get("not_collected"),
        "acquisitions": {a["query_id"]: {"outcomes": a["outcomes"], "classified": a.get("classified"),
                                         "unconverted": a["unconverted"], "withheld": a["withheld"]}
                         for a in report["acquisitions"]},
        "log_coverage_proven": logs.get("coverage_proven"), "log_basis_emitted": logs.get("basis_emitted"),
        "log_gaps": sorted({g[2] for g in logs.get("gaps", [])}),
        "requested_window_ms": intervals.get("requested_incident_window_ms"),
        "verified_interval_ms": intervals.get("verified_interval_ms"),
        "narrowed": intervals.get("narrowed"), "narrowing_refused": intervals.get("narrowing_refused"),
        "relevant_outside_count": intervals.get("relevant_outside_count"),
        "gaps": sorted({f"{g['query_id']}:{g['subject']}:{','.join(g['reasons'])}" for g in result["gaps"]})}

    rollouts, symptoms = [], []
    for b in conversion.batch_records:
        for o in b["observations"]:
            if o["observation_kind"] == "deployment_rollout":
                rollouts.append({"namespace": o["entity"]["namespace"], "name": o["entity"]["name"],
                                 "bracket_ms": _bracket(o, domain),
                                 "field_changes": [[fc["config_key"], fc["before_value"], fc["after_value"]]
                                                   for fc in o["attributes"].get("field_changes", [])]})
            elif o["observation_kind"] == "log_line" and o["attributes"]["template"] == "POOL_EXHAUSTED":
                symptoms.append(_bracket(o, domain))
    window = intervals.get("requested_incident_window_ms")
    witnessed = [r for r in rollouts if r["bracket_ms"]]
    record["timing"] = {
        "rollouts": rollouts,
        "rollout_lower_minus_window_start_ms": (witnessed[0]["bracket_ms"][0] - window[0]) if witnessed and window else None,
        "symptoms": len(symptoms), "symptoms_bracketed": sum(1 for s in symptoms if s),
        "symptoms_after_rollout": sum(1 for s in symptoms if s and witnessed and s[0] > witnessed[0]["bracket_ms"][1])}

    rows = []
    try:
        rows = json.loads(Path(args.db_json).read_bytes())
    except (OSError, ValueError):
        pass
    row = rows[0] if len(rows) == 1 else {}
    record["database"] = {"status": row.get("status"), "verified": row.get("verified"), "outcome": row.get("outcome"),
                          "matches_offline": row.get("status") == "ok" and row.get("verified") is True
                          and row.get("outcome") == outcome["status"]}
    return record


def main():
    p = argparse.ArgumentParser()
    for name in ("scenario", "out", "steps", "db-json", "token-file", "started", "records"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--repetition", type=int, required=True)
    args = p.parse_args()
    record = evaluate(args)
    records = Path(args.records)
    records.mkdir(parents=True, exist_ok=True)
    path = records / f"{args.scenario}-{args.repetition:02d}.json"
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"record {path.name}: harness {record['harness']} outcome "
          f"{(record.get('outcome') or {}).get('status')} {(record.get('outcome') or {}).get('reasons')}")


if __name__ == "__main__":
    main()
