"""CA-P2-007 developer-set scorer (standard library only).

  score.py RECORDS_DIR [--scenarios FILE] [--json OUT.json] [--markdown OUT.md]

Reads every run record and the frozen scenario file (truth, expectations, predictions, thresholds) -- the only
component that reads the truth, and only after every run has finished.

**Integrity first (CA-P2-007b).** Scoring is refused (exit 2, nothing scored) unless the records are exactly the
pre-registered run set:
- every (scenario, repetition) of the file has exactly one record, and nothing else has one: no missing, no
  unexpected scenario, no additional repetition, no duplicate;
- every record's file name is ``<scenario>-<nn>.json`` for the IDs inside it;
- ``attempts.log`` (append-only, written before each attempt) lists every registered run exactly once: a
  repeated attempt, which could have replaced an earlier result, is refused even though records are written
  with exclusive create.

Every attempted run is in the denominator; harness failures never count as correct or as valid abstentions.
Exit 0 when every acceptance criterion is met, 1 otherwise (the report is written either way).

Per run: ``correct_resolution`` (positive; resolved with the expected mechanism on the true Deployment, and the
bundle shows the true typed change), ``false_cause`` (resolved when truth has no cause, or a different mechanism,
entity or change), ``unsupported_resolution`` (a negative whose cause exists but whose evidence was removed
resolved), ``necessary_abstention``, ``unnecessary_abstention`` (with reasons), ``harness_failure``.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I leaves the script directory out
from scenario import collection, expected_runs, load  # noqa: E402

SCORER_VERSION = "ca-eval-scorer/0.2-provisional"


class IntegrityError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def check_run_set(records_dir, doc):
    """The records exactly as pre-registered, or IntegrityError listing every problem. Returns the records."""
    records_dir = Path(records_dir)
    expected = expected_runs(doc)
    problems, records, seen = [], [], Counter()
    for path in sorted(records_dir.glob("*.json")):
        try:
            record = json.loads(path.read_bytes())
            key = (record["scenario"], record["repetition"])
            name = f"{key[0]}-{key[1]:02d}.json"
        except (ValueError, KeyError, TypeError):
            problems.append(f"{path.name}: not a run record")
            continue
        if path.name != name:
            problems.append(f"{path.name}: file name disagrees with its IDs {name}")
        if key not in expected:
            problems.append(f"{path.name}: {key[0]} repetition {key[1]} is not pre-registered")
        seen[key] += 1
        records.append(record)
    problems += [f"{s}-{r:02d}: more than one record" for (s, r), n in sorted(seen.items()) if n > 1]
    problems += [f"{s}-{r:02d}: no record" for (s, r) in sorted(expected - set(seen))]
    attempts = Counter()
    log = records_dir / "attempts.log"
    if not log.is_file():
        problems.append("attempts.log: missing")
    else:
        for line in log.read_text(encoding="ascii").splitlines():
            parts = line.split(" ")
            if len(parts) < 2 or not parts[1].isdigit():
                problems.append(f"attempts.log: malformed line {line[:40]!r}")
                continue
            attempts[(parts[0], int(parts[1]))] += 1
        problems += [f"{s}-{r:02d}: attempted {n} times" for (s, r), n in sorted(attempts.items()) if n > 1]
        problems += [f"{s}-{r:02d}: attempted but not pre-registered" for (s, r) in sorted(set(attempts) - expected)]
        problems += [f"{s}-{r:02d}: pre-registered but never attempted" for (s, r) in sorted(expected - set(attempts))]
    if problems:
        raise IntegrityError(problems)
    return records


def classify(record, scenario, doc=None):
    truth, expected = scenario["truth"], scenario["expected"]
    outcome = record.get("outcome") or {}
    status = outcome.get("status")
    resolved = status == "resolved"
    entity = (record.get("resolved_change") or {}).get("entity") or {}
    timing, coverage = record.get("timing") or {}, record.get("coverage") or {}
    config = record.get("config") or (collection(doc, scenario) if doc else {})
    c = {"scenario": scenario["id"], "repetition": record["repetition"], "kind": scenario["kind"],
         "expected": expected["status"], "prediction": scenario.get("prediction"),
         "actual": status if record.get("harness") == "ok" else "harness_failure",
         "reasons": outcome.get("reasons"), "harness_failure": record.get("harness_failure"),
         "correct_resolution": False, "false_cause": False, "unsupported_resolution": False,
         "necessary_abstention": False, "unnecessary_abstention": False,
         "citations_valid": (record.get("citations") or {}).get("invalid") == 0 if resolved or status else None,
         "leaks": len(record.get("leaks") or []) if "leaks" in record else None,
         "replay_ok": bool(record.get("replay_bundle_rederived") and record.get("offline_deterministic")),
         "database_ok": bool((record.get("database") or {}).get("matches_offline")),
         "rollout_lower_minus_window_start_ms": timing.get("rollout_lower_minus_window_start_ms"),
         "min_symptom_lower_minus_rollout_upper_ms": timing.get("min_symptom_lower_minus_rollout_upper_ms"),
         "narrowed": coverage.get("narrowed"), "narrowing_refused": coverage.get("narrowing_refused"),
         "config": {k: config.get(k) for k in ("probe_interval_seconds", "action_at_seconds", "incident_window_seconds",
                                                "log_rotation_seconds")}}
    if record.get("harness") != "ok" or status is None:
        return c
    true_change = bool(truth.get("cause")) and any(
        r["namespace"] == truth.get("namespace") and r["name"] == truth.get("deployment")
        and [truth.get("config_key"), truth.get("before"), truth.get("after")] in r["field_changes"]
        for r in timing.get("rollouts", []))
    on_true_entity = entity.get("namespace") == truth.get("namespace") and entity.get("name") == truth.get("deployment")
    if resolved:
        if scenario["kind"] == "positive" and outcome.get("mechanism") == expected.get("mechanism") \
                and on_true_entity and true_change:
            c["correct_resolution"] = True
        elif scenario["kind"] == "negative" and truth.get("cause") and outcome.get("mechanism") == truth["cause"] \
                and on_true_entity and true_change:
            c["unsupported_resolution"] = True       # the true cause, but the evidence was made insufficient
        else:
            c["false_cause"] = True
    elif scenario["kind"] == "negative":
        c["necessary_abstention"] = True
    else:
        c["unnecessary_abstention"] = True
    return c


def _min_correct(doc, s):
    th = doc["thresholds"].get(s["id"])
    if isinstance(th, dict) and "min_correct_resolutions" in th:
        return th["min_correct_resolutions"]
    return s.get("min_correct_resolutions")   # None: measured, no threshold (timing matrix)


def summarize(rows, doc):
    th = doc["thresholds"]
    by = {}
    for r in rows:
        by.setdefault(r["scenario"], []).append(r)
    summary = {"scorer": SCORER_VERSION, "scenarios": {}, "criteria": {}}
    for s in doc["scenarios"]:
        runs = by.get(s["id"], [])
        summary["scenarios"][s["id"]] = {
            "kind": s["kind"], "planned": s["repetitions"], "attempted": len(runs), "prediction": s.get("prediction"),
            "config": collection(doc, s),
            "correct_resolutions": sum(r["correct_resolution"] for r in runs),
            "necessary_abstentions": sum(r["necessary_abstention"] for r in runs),
            "unnecessary_abstentions": sum(r["unnecessary_abstention"] for r in runs),
            "false_causes": sum(r["false_cause"] for r in runs),
            "unsupported_resolutions": sum(r["unsupported_resolution"] for r in runs),
            "harness_failures": sum(r["actual"] == "harness_failure" for r in runs)}
    sc, crit = summary["scenarios"], summary["criteria"]
    for s in doc["scenarios"]:
        need = _min_correct(doc, s)
        if s["kind"] == "positive" and need is not None:
            crit[f"{s['id']}_correct"] = {"value": f"{sc[s['id']]['correct_resolutions']}/{sc[s['id']]['attempted']}",
                                          "met": sc[s["id"]]["attempted"] >= s["repetitions"]
                                          and sc[s["id"]]["correct_resolutions"] >= need}
    negatives = [s for s in doc["scenarios"] if s["kind"] == "negative"]
    min_reps = th.get("negatives", {}).get("min_repetitions", 1)
    crit["every_negative_abstains"] = {
        "value": f"{sum(sc[s['id']]['necessary_abstentions'] for s in negatives)}/"
                 f"{sum(sc[s['id']]['attempted'] for s in negatives)}",
        "met": all(sc[s["id"]]["attempted"] >= min_reps
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
                         "positive_runs_not_narrowed": sum(1 for r in rows if r["kind"] == "positive" and r["narrowed"] is False),
                         "positive_unnecessary_abstentions": sum(r["unnecessary_abstention"] for r in rows)}
    return summary


def markdown(summary, rows, digest, version):
    lines = [f"# CA-P2-007 development-set evaluation ({SCORER_VERSION})", "",
             f"Scenario file `{version}`, `{digest}`. Developer-authored synthetic development set; not independent "
             "accuracy certification.", "",
             "Integrity: the records are exactly the pre-registered run set (checked before scoring).", "",
             "## Acceptance criteria", "", "| Criterion | Value | Met |", "|---|---|---|"]
    for name, c in summary["criteria"].items():
        lines.append(f"| {name} | {c['value']} | {'yes' if c['met'] else '**no**'} |")
    lines += ["", f"**All criteria met: {'yes' if summary['all_met'] else 'no'}**", "", "## Per scenario", "",
              "| Scenario | Kind | Probe s | Action s | Window s | Rotation s | Prediction | Attempted | Correct | "
              "Necessary abst. | Unnecessary abst. | False cause | Unsupported | Harness failures |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sid, s in summary["scenarios"].items():
        c = s["config"]
        lines.append(f"| {sid} | {s['kind']} | {c['probe_interval_seconds']} | {c['action_at_seconds']} | "
                     f"{c['incident_window_seconds']} | {c['log_rotation_seconds']} | {s['prediction'] or ''} | "
                     f"{s['attempted']}/{s['planned']} | {s['correct_resolutions']} | {s['necessary_abstentions']} | "
                     f"{s['unnecessary_abstentions']} | {s['false_causes']} | {s['unsupported_resolutions']} | "
                     f"{s['harness_failures']} |")
    lines += ["", "## Every run", "",
              "| Run | Expected | Actual | Reasons | Narrowed | Refused | Rollout margin ms | Symptom margin ms | "
              "Citations | Leaks | Replay | DB |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["scenario"], r["repetition"])):
        lines.append(f"| {r['scenario']}-{r['repetition']:02d} | {r['expected']} | {r['actual']}"
                     f"{' (' + str(r['harness_failure']) + ')' if r['harness_failure'] else ''} | "
                     f"{', '.join(r['reasons'] or [])} | {r['narrowed']} | {', '.join(r['narrowing_refused'] or [])} | "
                     f"{r['rollout_lower_minus_window_start_ms']} | {r['min_symptom_lower_minus_rollout_upper_ms']} | "
                     f"{r['citations_valid']} | {r['leaks']} | {r['replay_ok']} | {r['database_ok']} |")
    t = summary["timing"]
    lines += ["", f"Positive rollout margins after the window start (ms): {t['positive_rollout_lower_minus_window_start_ms']}",
              f"Positive runs whose window was not narrowed: {t['positive_runs_not_narrowed']}",
              f"Positive unnecessary abstentions: {t['positive_unnecessary_abstentions']}", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("records")
    p.add_argument("--scenarios", default=None)
    p.add_argument("--json")
    p.add_argument("--markdown")
    args = p.parse_args()
    doc, digest = load(args.scenarios)
    try:
        records = check_run_set(args.records, doc)
    except IntegrityError as exc:
        print("SCORING REFUSED: the records are not exactly the pre-registered run set")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 2
    scenarios = {s["id"]: s for s in doc["scenarios"]}
    rows = [classify(r, scenarios[r["scenario"]], doc) for r in records]
    summary = summarize(rows, doc)
    summary["scenario_file"] = digest
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "runs": rows}, indent=1, sort_keys=True) + "\n",
                                   encoding="utf-8")
    text = markdown(summary, rows, digest, doc.get("version"))
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
    print(text)
    return 0 if summary["all_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
