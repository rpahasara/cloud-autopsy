"""CA-P2-007a developer-set scorer (standard library only).

  score.py RECORDS_DIR [--json OUT.json] [--markdown OUT.md]

Reads every run record and the frozen scenario file (truth, expectations, thresholds) -- the only component that
reads the truth, and only after every run has finished. Every attempted run is in the denominator; harness
failures are reported separately and never count as correct or as valid abstentions. Exit status 0 when every
acceptance criterion is met, 1 otherwise (the report is written either way).

Per run:
- ``correct_resolution``: positive; resolved with the expected mechanism on the true Deployment (namespace and
  name), and the bundle shows the true typed limit change;
- ``false_cause``: resolved anything when truth has no cause, or resolved a different mechanism or entity;
- ``unsupported_resolution``: a negative scenario whose cause exists but whose evidence was made insufficient
  (N5, N6) resolved -- not a false cause, but the run had to abstain;
- ``necessary_abstention`` (negative abstained) / ``unnecessary_abstention`` (positive abstained, with reasons);
- ``harness_failure``: the run did not produce a verifiable bundle (with the failed step).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I leaves the script directory out
from scenario import load  # noqa: E402

SCORER_VERSION = "ca-eval-scorer/0.1-provisional"


def classify(record, scenario):
    truth, expected = scenario["truth"], scenario["expected"]
    outcome = record.get("outcome") or {}
    status = outcome.get("status")
    resolved = status == "resolved"
    entity = (record.get("resolved_change") or {}).get("entity") or {}
    c = {"scenario": scenario["id"], "repetition": record["repetition"], "kind": scenario["kind"],
         "expected": expected["status"], "actual": status if record.get("harness") == "ok" else "harness_failure",
         "reasons": outcome.get("reasons"), "harness_failure": record.get("harness_failure"),
         "correct_resolution": False, "false_cause": False, "unsupported_resolution": False,
         "necessary_abstention": False, "unnecessary_abstention": False,
         "citations_valid": (record.get("citations") or {}).get("invalid") == 0 if resolved or status else None,
         "leaks": len(record.get("leaks") or []) if "leaks" in record else None,
         "replay_ok": bool(record.get("replay_bundle_rederived") and record.get("offline_deterministic")),
         "database_ok": bool((record.get("database") or {}).get("matches_offline")),
         "rollout_lower_minus_window_start_ms": (record.get("timing") or {}).get("rollout_lower_minus_window_start_ms"),
         "narrowed": (record.get("coverage") or {}).get("narrowed"),
         "narrowing_refused": (record.get("coverage") or {}).get("narrowing_refused")}
    if record.get("harness") != "ok" or status is None:
        return c
    true_change = truth.get("cause") and any(
        r["namespace"] == truth.get("namespace") and r["name"] == truth.get("deployment")
        and [truth.get("config_key"), truth.get("before"), truth.get("after")] in r["field_changes"]
        for r in (record.get("timing") or {}).get("rollouts", []))
    on_true_entity = entity.get("namespace") == truth.get("namespace") and entity.get("name") == truth.get("deployment")
    if resolved:
        if scenario["kind"] == "positive" and outcome.get("mechanism") == expected.get("mechanism") \
                and on_true_entity and true_change:
            c["correct_resolution"] = True
        elif scenario["kind"] == "negative" and truth.get("cause") and outcome.get("mechanism") == truth["cause"]                 and on_true_entity and true_change:
            c["unsupported_resolution"] = True       # the true cause, but the evidence was made insufficient
        else:
            c["false_cause"] = True
    elif scenario["kind"] == "negative":
        c["necessary_abstention"] = True
    else:
        c["unnecessary_abstention"] = True
    return c


def summarize(rows, doc):
    th = doc["thresholds"]
    by = {}
    for r in rows:
        by.setdefault(r["scenario"], []).append(r)
    summary = {"scorer": SCORER_VERSION, "scenarios": {}, "criteria": {}}
    for s in doc["scenarios"]:
        runs = by.get(s["id"], [])
        summary["scenarios"][s["id"]] = {
            "kind": s["kind"], "planned": s["repetitions"], "attempted": len(runs),
            "correct_resolutions": sum(r["correct_resolution"] for r in runs),
            "necessary_abstentions": sum(r["necessary_abstention"] for r in runs),
            "unnecessary_abstentions": sum(r["unnecessary_abstention"] for r in runs),
            "false_causes": sum(r["false_cause"] for r in runs),
            "unsupported_resolutions": sum(r["unsupported_resolution"] for r in runs),
            "harness_failures": sum(r["actual"] == "harness_failure" for r in runs)}
    sc = summary["scenarios"]
    crit = summary["criteria"]
    for pid in ("P1", "P2"):
        need = th[pid]
        crit[f"{pid}_correct"] = {"value": f"{sc[pid]['correct_resolutions']}/{sc[pid]['attempted']}",
                                  "met": sc[pid]["attempted"] >= need["repetitions"]
                                  and sc[pid]["correct_resolutions"] >= need["min_correct_resolutions"]}
    negatives = [s for s in doc["scenarios"] if s["kind"] == "negative"]
    crit["every_negative_abstains"] = {
        "value": f"{sum(sc[s['id']]['necessary_abstentions'] for s in negatives)}/"
                 f"{sum(sc[s['id']]['attempted'] for s in negatives)}",
        "met": all(sc[s["id"]]["attempted"] >= th["negatives"]["min_repetitions"]
                   and sc[s["id"]]["necessary_abstentions"] == sc[s["id"]]["attempted"] for s in negatives)}
    false_causes = sum(r["false_cause"] for r in rows)
    crit["zero_false_causes"] = {"value": false_causes, "met": false_causes == 0}
    checked = [r for r in rows if r["citations_valid"] is not None]
    crit["citations_valid"] = {"value": f"{sum(bool(r['citations_valid']) for r in checked)}/{len(checked)}",
                               "met": all(r["citations_valid"] for r in checked)}
    leaks = sum(r["leaks"] or 0 for r in rows)
    crit["zero_leaks"] = {"value": leaks, "met": leaks == 0 and all(r["leaks"] is not None for r in rows
                                                                    if r["actual"] != "harness_failure")}
    ok = [r for r in rows if r["actual"] != "harness_failure"]
    crit["deterministic_replay"] = {"value": f"{sum(r['replay_ok'] and r['database_ok'] for r in ok)}/{len(ok)}",
                                    "met": all(r["replay_ok"] and r["database_ok"] for r in ok)}
    crit["no_harness_failures"] = {"value": sum(r["actual"] == "harness_failure" for r in rows),
                                   "met": all(r["actual"] != "harness_failure" for r in rows)}
    summary["all_met"] = all(c["met"] for c in crit.values())
    margins = [r["rollout_lower_minus_window_start_ms"] for r in rows
               if r["kind"] == "positive" and r["rollout_lower_minus_window_start_ms"] is not None]
    summary["timing"] = {"positive_rollout_lower_minus_window_start_ms": sorted(margins),
                         "positive_runs_not_narrowed": sum(1 for r in rows if r["kind"] == "positive" and r["narrowed"] is False)}
    return summary


def markdown(summary, rows, digest):
    lines = [f"# CA-P2-007a development-set evaluation ({SCORER_VERSION})", "",
             f"Scenario file `{digest}`. Developer-authored synthetic development set; not independent accuracy certification.", "",
             "## Acceptance criteria", "", "| Criterion | Value | Met |", "|---|---|---|"]
    for name, c in summary["criteria"].items():
        lines.append(f"| {name} | {c['value']} | {'yes' if c['met'] else '**no**'} |")
    lines += ["", f"**All criteria met: {'yes' if summary['all_met'] else 'no'}**", "", "## Per scenario", "",
              "| Scenario | Kind | Attempted | Correct | Necessary abst. | Unnecessary abst. | False cause | Unsupported | Harness failures |",
              "|---|---|---|---|---|---|---|---|---|"]
    for sid, s in summary["scenarios"].items():
        lines.append(f"| {sid} | {s['kind']} | {s['attempted']}/{s['planned']} | {s['correct_resolutions']} | "
                     f"{s['necessary_abstentions']} | {s['unnecessary_abstentions']} | {s['false_causes']} | "
                     f"{s['unsupported_resolutions']} | {s['harness_failures']} |")
    lines += ["", "## Every run", "", "| Run | Expected | Actual | Reasons | Window narrowed | Refused | Rollout margin (ms) | Citations | Leaks | Replay | DB |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["scenario"], r["repetition"])):
        lines.append(f"| {r['scenario']}-{r['repetition']:02d} | {r['expected']} | {r['actual']}"
                     f"{' (' + str(r['harness_failure']) + ')' if r['harness_failure'] else ''} | "
                     f"{', '.join(r['reasons'] or [])} | {r['narrowed']} | {', '.join(r['narrowing_refused'] or [])} | "
                     f"{r['rollout_lower_minus_window_start_ms']} | {r['citations_valid']} | {r['leaks']} | "
                     f"{r['replay_ok']} | {r['database_ok']} |")
    lines += ["", f"Positive rollout margins after the window start (ms): {summary['timing']['positive_rollout_lower_minus_window_start_ms']}",
              f"Positive runs whose window was not narrowed: {summary['timing']['positive_runs_not_narrowed']}", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("records")
    p.add_argument("--json")
    p.add_argument("--markdown")
    args = p.parse_args()
    doc, digest = load()
    scenarios = {s["id"]: s for s in doc["scenarios"]}
    rows = []
    for path in sorted(Path(args.records).glob("*.json")):
        record = json.loads(path.read_bytes())
        rows.append(classify(record, scenarios[record["scenario"]]))
    summary = summarize(rows, doc)
    summary["scenario_file"] = digest
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "runs": rows}, indent=1, sort_keys=True) + "\n",
                                   encoding="utf-8")
    text = markdown(summary, rows, digest)
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
    print(text)
    return 0 if summary["all_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
