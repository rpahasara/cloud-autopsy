"""Held-out evaluation kit: freeze, commit, seal, execute and score (Python standard library only).

Integrity tooling for the independently authored CA-SCENARIO-008..010 families. It contains no
scenario content or ground truth, and it never modifies the engine, scorer or fixtures it reads.
Procedure: docs/evaluation/heldout/README.md.

Subcommands, in custody order:
    manifest      write the engine-format fixture-manifest.json for a fixture directory
    freeze        hash every file of a fixtures / metadata / predictions directory into a record
    verify        re-check a directory against a freeze record
    commit-truth  salted commitment to a ground-truth file (truth itself stays private)
    open-truth    check a ground-truth file and salt against a commitment
    seal          combine per-family public records into evaluation-seal.json
    run           execute the frozen engine on sealed fixtures and freeze the predictions
    score         reveal truth to the frozen scorer only after predictions are frozen
"""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

KIT_VERSION = "ca-heldout-kit/0.1"
COMMIT_SCHEME = "sha256(b'ca-heldout-truth-commit/0.1\\x00' + salt32 + truth_bytes)"
COMMIT_PREFIX = b"ca-heldout-truth-commit/0.1\x00"
PLACEHOLDER = b"<<FILL"
TEMPLATE_MARK = ".TEMPLATE."
MAX_FILE_BYTES = 256 * 1024 * 1024
ROLES = ("fixtures", "metadata", "predictions")
# Outcome labels used by the pinned development truth files. A held-out truth label outside this
# set can still be scored, but no run of the frozen candidate can be credited with it.
DEVELOPMENT_MECHANISM_LABELS = ("config_value_change", "deployment_rollout")


class KitError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data, label):
    """Parse JSON bytes, rejecting non-UTF-8, BOM, duplicate keys, floats and NaN/Infinity."""
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise KitError(f"{label}: duplicate key {key!r}")
            obj[key] = value
        return obj

    def no_float(text):
        raise KitError(f"{label}: float not permitted ({text}); carry decimals as strings")

    def no_constant(text):
        raise KitError(f"{label}: non-finite constant not permitted ({text})")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise KitError(f"{label}: not UTF-8") from None
    if text.startswith("﻿"):
        raise KitError(f"{label}: byte-order mark not permitted")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_float=no_float, parse_constant=no_constant)
    except json.JSONDecodeError as exc:
        raise KitError(f"{label}: malformed JSON: {exc}") from None


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def git_work_tree(path):
    """Return the enclosing Git work tree of ``path`` (or None)."""
    path = Path(path).resolve()
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return parent
    return None


def require_outside_git(path, what):
    tree = git_work_tree(path)
    if tree is not None:
        raise KitError(f"{what} must be kept outside any Git work tree (found {tree}); "
                       "confidential held-out material must never enter a shared repository")


def _check_content(rel, data, role):
    if role != "predictions":
        if PLACEHOLDER in data:
            raise KitError(f"{rel}: unfilled template placeholder (<<FILL...>>)")
        if TEMPLATE_MARK in Path(rel).name:
            raise KitError(f"{rel}: template file; rename or remove before freezing")
        if rel.endswith(".json"):
            strict_json(data, rel)
    if role == "fixtures":
        parts = [p.lower() for p in Path(rel).parts]
        if any("truth" in p for p in parts):
            raise KitError(f"{rel}: fixture sets must not contain truth files or 'truth' path components")


def collect(root, role):
    """Hash every regular file under ``root``; refuse links, special files and empty sets."""
    root = Path(root)
    if role not in ROLES:
        raise KitError(f"unknown role {role!r}")
    if _is_link(root) or not root.is_dir():
        raise KitError(f"{root}: not a plain directory")
    if role == "fixtures" and any("truth" in p.lower() for p in root.resolve().parts):
        raise KitError(f"{root}: fixture directory path must not contain a 'truth' component")
    files = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in dirnames:
            if _is_link(here / name):
                raise KitError(f"{here / name}: links are not permitted")
        dirnames.sort()
        for name in sorted(filenames):
            path = here / name
            if _is_link(path) or not path.is_file():
                raise KitError(f"{path}: only regular files are permitted")
            data = path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                raise KitError(f"{path}: exceeds {MAX_FILE_BYTES} bytes")
            rel = path.relative_to(root).as_posix()
            _check_content(rel, data, role)
            files.append({"path": rel, "size": len(data), "sha256": _sha256(data)})
    if not files:
        raise KitError(f"{root}: no files to freeze")
    return sorted(files, key=lambda f: f["path"])


def aggregate(role, files):
    return _sha256(_canonical({"role": role, "files": files}))


def freeze(root, role, set_id):
    if role == "fixtures":
        require_outside_git(root, "held-out fixtures")
        if not (Path(root) / "fixture-manifest.json").is_file():
            raise KitError(f"{root}: run 'manifest' first; fixture-manifest.json is missing")
    files = collect(root, role)
    return {"record_version": "ca-heldout-freeze/0.1", "kit_version": KIT_VERSION, "role": role,
            "set_id": set_id, "files": files, "aggregate_sha256": aggregate(role, files),
            "created_utc": _now()}


def verify(record, root):
    """Return a list of differences between ``root`` and a freeze record (empty when identical)."""
    files = collect(root, record["role"])
    expected = {f["path"]: f for f in record["files"]}
    actual = {f["path"]: f for f in files}
    problems = [f"missing:{p}" for p in sorted(set(expected) - set(actual))]
    problems += [f"unexpected:{p}" for p in sorted(set(actual) - set(expected))]
    problems += [f"changed:{p}" for p in sorted(set(expected) & set(actual)) if expected[p] != actual[p]]
    if aggregate(record["role"], record["files"]) != record["aggregate_sha256"]:
        problems.append("record_aggregate_mismatch")
    return problems


def write_manifest(fixture_dir, fixture_id, fixture_version):
    """Write fixture-manifest.json in the engine's format: raw-byte SHA-256 of every other JSON file."""
    root = Path(fixture_dir)
    files = {}
    for f in collect(root, "fixtures"):
        if f["path"].endswith(".json") and f["path"] != "fixture-manifest.json":
            files[f["path"]] = f["sha256"]
    manifest = {"fixture_id": fixture_id, "fixture_version": fixture_version, "digest_algorithm": "sha256",
                "files": dict(sorted(files.items()))}
    (root / "fixture-manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return manifest


def commit_truth(truth_file, salt_out):
    truth_file, salt_out = Path(truth_file), Path(salt_out)
    require_outside_git(truth_file, "ground truth")
    require_outside_git(salt_out.parent, "the truth salt")
    if salt_out.exists():
        raise KitError(f"{salt_out}: already exists; refusing to overwrite a salt")
    data = truth_file.read_bytes()
    _check_content(truth_file.name, data, "truth")
    salt = secrets.token_bytes(32)
    salt_out.write_text(salt.hex() + "\n", encoding="ascii")
    return {"record_version": "ca-heldout-truth-commitment/0.1", "kit_version": KIT_VERSION,
            "scheme": COMMIT_SCHEME, "truth_commitment": _sha256(COMMIT_PREFIX + salt + data),
            "created_utc": _now()}


def open_truth(truth_file, salt_file, commitment):
    data = Path(truth_file).read_bytes()
    salt = bytes.fromhex(Path(salt_file).read_text(encoding="ascii").strip())
    if len(salt) != 32:
        raise KitError("salt must be 32 bytes")
    if _sha256(COMMIT_PREFIX + salt + data) != commitment:
        raise KitError("ground truth or salt does not match the sealed commitment")
    return data


def seal(seal_dir, candidate, author, reviewer):
    """Combine per-family public records (no truth) into evaluation-seal.json."""
    seal_dir = Path(seal_dir)
    families = []
    for family in sorted(p for p in seal_dir.iterdir() if p.is_dir()):
        def load(name):
            path = family / name
            if not path.is_file():
                raise KitError(f"{path}: missing")
            return strict_json(path.read_bytes(), str(path))
        fixtures, metadata, commitment = (load("fixtures.freeze.json"), load("metadata.freeze.json"),
                                          load("truth.commitment.json"))
        meta_doc = load("metadata/eval-metadata.json")
        if fixtures["role"] != "fixtures" or metadata["role"] != "metadata":
            raise KitError(f"{family}: freeze records have the wrong roles")
        if set(commitment) - {"record_version", "kit_version", "scheme", "truth_commitment", "created_utc"}:
            raise KitError(f"{family}: truth.commitment.json carries unexpected fields; never publish truth")
        problems = verify(metadata, family / "metadata")
        if problems:
            raise KitError(f"{family}: metadata does not match its freeze record: {problems}")
        if meta_doc.get("scenario_id") != family.name or meta_doc.get("candidate_commit") != candidate:
            raise KitError(f"{family}: eval-metadata scenario_id/candidate_commit disagree with the seal")
        families.append({"scenario_id": family.name, "fixture_id": meta_doc["fixture_id"],
                         "variants": meta_doc["variants"], "fixtures_record": fixtures,
                         "metadata_record": metadata, "truth_commitment": commitment["truth_commitment"],
                         "commit_scheme": commitment["scheme"]})
    if not families:
        raise KitError(f"{seal_dir}: no family directories")
    body = {"seal_version": "ca-heldout-seal/0.1", "kit_version": KIT_VERSION, "candidate_commit": candidate,
            "author": author, "reviewer": reviewer, "families": families}
    return dict(body, seal_sha256=_sha256(_canonical(body)), sealed_utc=_now())


def load_seal(path):
    doc = strict_json(Path(path).read_bytes(), str(path))
    body = {k: v for k, v in doc.items() if k not in ("seal_sha256", "sealed_utc")}
    if _sha256(_canonical(body)) != doc.get("seal_sha256"):
        raise KitError("evaluation-seal.json does not match its own digest")
    return doc


def check_engine_checkout(engine_root, candidate):
    head = subprocess.run(["git", "-C", str(engine_root), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != candidate:
        raise KitError(f"engine checkout is at {head}, not the sealed candidate {candidate}")
    dirty = subprocess.run(["git", "-C", str(engine_root), "status", "--porcelain", "--untracked-files=all"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        raise KitError("engine checkout has local changes; use a clean worktree at the candidate commit")


def _import_engine(engine_root):
    sys.path.insert(0, str(Path(engine_root) / "prototype"))
    import ca_spike
    from ca_eval import SCORER_VERSION
    from ca_eval.scorer import load_truth, score_run, summarize
    from ca_spike.fixtures import load_scenario
    from ca_spike.pipeline import replay, run_investigation
    from ca_spike.store import FileArtifactStore
    return {"engine_version": ca_spike.ENGINE_VERSION, "scorer_version": SCORER_VERSION,
            "load_scenario": load_scenario, "run_investigation": run_investigation, "replay": replay,
            "store": FileArtifactStore, "load_truth": load_truth, "score_run": score_run,
            "summarize": summarize}


def _error(exc):
    return {"error_type": type(exc).__name__, "error": str(exc)[:500],
            "traceback_tail": traceback.format_exc().splitlines()[-3:]}


def run(engine_root, seal_doc, fixture_dirs, out_dir, git_check=True):
    """Execute every sealed family/variant; record failures instead of stopping; freeze predictions."""
    if git_check:
        check_engine_checkout(engine_root, seal_doc["candidate_commit"])
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise KitError(f"{out_dir}: must be new or empty (the kit never deletes)")
    engine = _import_engine(engine_root)
    log = {"log_version": "ca-heldout-execution/0.1", "kit_version": KIT_VERSION,
           "candidate_commit": seal_doc["candidate_commit"], "seal_sha256": seal_doc["seal_sha256"],
           "engine_version": engine["engine_version"], "git_check": "passed" if git_check else "skipped",
           "started_utc": _now(), "families": []}
    for fam in seal_doc["families"]:
        entry = {"scenario_id": fam["scenario_id"], "fixture_id": fam["fixture_id"], "variants": []}
        log["families"].append(entry)
        fixture_dir = fixture_dirs.get(fam["scenario_id"])
        problems = ["fixture_directory_not_supplied"] if fixture_dir is None else verify(fam["fixtures_record"],
                                                                                        fixture_dir)
        if problems:
            entry["fixture_integrity"] = {"status": "failed", "problems": problems}
            entry["variants"] = [{"variant": v, "execution": "not_run", "reason": "fixture_integrity_failed"}
                                 for v in fam["variants"]]
            continue
        entry["fixture_integrity"] = {"status": "verified"}
        for variant in fam["variants"]:
            run_dir = out_dir / fam["scenario_id"] / variant
            result = {"variant": variant}
            try:
                scenario = engine["load_scenario"](Path(fixture_dir), variant)
                summary = engine["run_investigation"](scenario, engine["store"](run_dir))
                result.update(execution="completed", run_state=summary["state"],
                              bundle_digest=summary["bundle_digest"])
            except Exception as exc:  # report, never drop, a failed execution
                result.update(execution="failed", **_error(exc))
            if result["execution"] == "completed":
                try:
                    result["replay"] = engine["replay"](engine["store"](run_dir))["state"]
                except Exception as exc:
                    result["replay"] = "replay_failed"
                    result["replay_error"] = _error(exc)
            entry["variants"].append(result)
    log["finished_utc"] = _now()
    (out_dir / "execution-log.json").parent.mkdir(parents=True, exist_ok=True)
    (out_dir / "execution-log.json").write_bytes((json.dumps(log, indent=1, sort_keys=True) + "\n").encode())
    return log, freeze_predictions(out_dir)


def freeze_predictions(out_dir):
    files = collect(out_dir, "predictions")
    return {"record_version": "ca-heldout-freeze/0.1", "kit_version": KIT_VERSION, "role": "predictions",
            "set_id": "predictions", "files": files, "aggregate_sha256": aggregate("predictions", files),
            "created_utc": _now()}


def classify(report, truth, variant_truth):
    """Reporting class for one scored variant (fixed before execution; see evaluation-process.md)."""
    engine, expected = report["engine"], variant_truth["expected_outcome"]
    attribution = engine["causal_attribution"]
    if attribution == "identity_unverifiable":
        primary = "change_identity_unverifiable"
    elif attribution == "abstained":
        primary = "justified_abstention" if expected == "abstained" else "unnecessary_abstention"
    elif expected == "abstained":
        primary = "resolved_when_abstention_expected"
    else:
        primary = "correct_attribution" if attribution == "correct" else "incorrect_attribution"
    cause = truth.get("causal_change") or {}
    flags = []
    if cause and cause.get("mechanism") not in DEVELOPMENT_MECHANISM_LABELS:
        flags.append("truth_mechanism_label_outside_development_vocabulary")
    if engine["false_cause"] == "selected":
        flags.append("false_cause_selected")
    if not engine["run_state_correct"]:
        flags.append("run_state_mismatch")
    if not engine["gaps_correct"]:
        flags.append("gap_mismatch")
    if not engine["synthesis_status_correct"]:
        flags.append("synthesis_status_mismatch")
    if engine.get("abstention_reason_correct") is False:
        flags.append("abstention_reason_mismatch")
    if report["security"]["policy_result"] != "pass":
        flags.append("security_policy_fail")
    if report.get("clock") and report["clock"]["matched"]["numerator"] != report["clock"]["matched"]["denominator"]:
        flags.append("clock_order_mismatch")
    return {"primary": primary, "flags": flags}


def score(engine_root, seal_doc, predictions_dir, predictions_record, truth_sources, git_check=True):
    """Verify frozen predictions, then open each truth and score with the frozen scorer."""
    if git_check:
        check_engine_checkout(engine_root, seal_doc["candidate_commit"])
    problems = verify(predictions_record, predictions_dir)
    if problems:
        raise KitError(f"predictions changed after freezing: {problems}")
    engine = _import_engine(engine_root)
    log = strict_json((Path(predictions_dir) / "execution-log.json").read_bytes(), "execution-log.json")
    if log["seal_sha256"] != seal_doc["seal_sha256"]:
        raise KitError("predictions were produced under a different seal")
    results = {"results_version": "ca-heldout-results/0.1", "kit_version": KIT_VERSION,
               "candidate_commit": seal_doc["candidate_commit"], "seal_sha256": seal_doc["seal_sha256"],
               "predictions_aggregate_sha256": predictions_record["aggregate_sha256"],
               "engine_version": log["engine_version"], "scorer_version": engine["scorer_version"],
               "git_check": "passed" if git_check else "skipped", "scored_utc": _now(),
               "status": "exploratory; not approval of any SSDLC gate", "families": []}
    with tempfile.TemporaryDirectory() as tmp:
        for fam, fam_log in zip(seal_doc["families"], log["families"]):
            entry = {"scenario_id": fam["scenario_id"], "fixture_id": fam["fixture_id"],
                     "fixture_integrity": fam_log["fixture_integrity"]["status"], "variants": []}
            results["families"].append(entry)
            truth_file, salt_file = truth_sources[fam["scenario_id"]]
            data = open_truth(truth_file, salt_file, fam["truth_commitment"])
            entry["truth_sha256"] = _sha256(data)
            truth_doc = strict_json(data, "ground truth")
            pins = Path(tmp) / f"{fam['scenario_id']}-pins.json"
            pins.write_text(json.dumps({"truth": {fam["fixture_id"]: {"path": str(Path(truth_file).resolve()),
                                                                     "sha256": entry["truth_sha256"]}}}))
            scored = []
            for v in fam_log["variants"]:
                row = {"variant": v["variant"], "execution": v["execution"]}
                if v["execution"] != "completed":
                    row.update(classification={"primary": "execution_failed" if v["execution"] == "failed"
                                               else "not_run", "flags": []},
                               detail={k: v[k] for k in ("error_type", "error", "reason") if k in v})
                else:
                    try:
                        truth, digest = engine["load_truth"](Path(engine_root) / "prototype", fam["fixture_id"],
                                                             pins_path=pins)
                        store = engine["store"](Path(predictions_dir) / fam["scenario_id"] / v["variant"])
                        report = engine["score_run"](store, truth, digest)
                        row.update(replay=v.get("replay"), report=report,
                                   classification=classify(report, truth, truth["variants"][v["variant"]]))
                        scored.append(report)
                    except Exception as exc:  # truth or scorer defect: report, never silently fix
                        row.update(classification={"primary": "scoring_failed", "flags": []}, detail=_error(exc))
                entry["variants"].append(row)
            entry["scorer_summary_of_scored_variants"] = engine["summarize"](scored) if scored else None
    tally = {}
    for fam in results["families"]:
        for row in fam["variants"]:
            tally[row["classification"]["primary"]] = tally.get(row["classification"]["primary"], 0) + 1
    results["classification_counts"] = dict(sorted(tally.items()))
    results["variants_total"] = sum(tally.values())
    return results


def _write_json(path, doc):
    path = Path(path)
    if path.exists():
        raise KitError(f"{path}: already exists; the kit never overwrites records")
    path.write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))


def _pairs(values, label):
    out = {}
    for item in values or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise KitError(f"{label}: expected SCENARIO_ID=VALUE, got {item!r}")
        out[key] = value
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("manifest")
    p.add_argument("fixture_dir"); p.add_argument("--fixture-id", required=True)
    p.add_argument("--fixture-version", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("directory"); p.add_argument("--role", choices=ROLES, required=True)
    p.add_argument("--set-id", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("verify")
    p.add_argument("record"); p.add_argument("directory")
    p = sub.add_parser("commit-truth")
    p.add_argument("truth_file"); p.add_argument("--salt-out", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("open-truth")
    p.add_argument("truth_file"); p.add_argument("--salt", required=True); p.add_argument("--commitment", required=True)
    p = sub.add_parser("seal")
    p.add_argument("seal_dir"); p.add_argument("--candidate", required=True)
    p.add_argument("--author", required=True); p.add_argument("--reviewer", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("run")
    p.add_argument("--engine-root", required=True); p.add_argument("--seal", required=True)
    p.add_argument("--fixtures", action="append", required=True, help="SCENARIO_ID=FIXTURE_DIR (repeat)")
    p.add_argument("--out", required=True); p.add_argument("--record-out", required=True)
    p = sub.add_parser("score")
    p.add_argument("--engine-root", required=True); p.add_argument("--seal", required=True)
    p.add_argument("--predictions", required=True); p.add_argument("--predictions-record", required=True)
    p.add_argument("--truth", action="append", required=True, help="SCENARIO_ID=TRUTH_FILE,SALT_FILE (repeat)")
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "manifest":
            print(json.dumps(write_manifest(a.fixture_dir, a.fixture_id, a.fixture_version), indent=1))
        elif a.cmd == "freeze":
            record = freeze(a.directory, a.role, a.set_id)
            _write_json(a.out, record)
            print(f"{a.role} {a.set_id}: {len(record['files'])} files, aggregate {record['aggregate_sha256']}")
        elif a.cmd == "verify":
            problems = verify(strict_json(Path(a.record).read_bytes(), a.record), a.directory)
            print("verified" if not problems else "MISMATCH: " + ", ".join(problems))
            return 1 if problems else 0
        elif a.cmd == "commit-truth":
            record = commit_truth(a.truth_file, a.salt_out)
            _write_json(a.out, record)
            print(f"truth commitment {record['truth_commitment']} (salt kept at {a.salt_out})")
        elif a.cmd == "open-truth":
            open_truth(a.truth_file, a.salt, a.commitment)
            print("truth matches commitment")
        elif a.cmd == "seal":
            doc = seal(a.seal_dir, a.candidate, a.author, a.reviewer)
            _write_json(a.out, doc)
            print(f"sealed {len(doc['families'])} families: {doc['seal_sha256']}")
        elif a.cmd == "run":
            log, record = run(a.engine_root, load_seal(a.seal), _pairs(a.fixtures, "--fixtures"), a.out)
            _write_json(a.record_out, record)
            failed = sum(v["execution"] != "completed" for f in log["families"] for v in f["variants"])
            print(f"predictions frozen: {record['aggregate_sha256']} ({failed} variant(s) not completed)")
        elif a.cmd == "score":
            truth = {k: tuple(v.split(",", 1)) for k, v in _pairs(a.truth, "--truth").items()}
            results = score(a.engine_root, load_seal(a.seal), a.predictions,
                            strict_json(Path(a.predictions_record).read_bytes(), a.predictions_record), truth)
            _write_json(a.out, results)
            print(f"scored {results['variants_total']} variants: {results['classification_counts']}")
    except KitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
