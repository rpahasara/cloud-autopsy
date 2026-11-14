"""CA-P2-007 scenario driver helper (standard library only): read a frozen scenario file, render manifests.

  scenario.py [--file F] order              the run order: round-robin over repetitions (fixed, frozen)
  scenario.py [--file F] render ID OUTDIR   write OUTDIR/incident.yaml (and other.yaml) and OUTDIR/params.env
  scenario.py [--file F] digest             the scenario file's SHA-256
  scenario.py [--file F] config ID          the effective collection configuration of one scenario (JSON)

``--file`` defaults to tools/eval/scenarios.json (version 0.1, frozen). A scenario may override any key of the
file-level ``collection`` (CA-P2-007b timing matrix); the effective configuration is recorded with every run.
Manifests are rendered from the reviewed deploy/kind/incident.yaml by exact line replacement only; ``params.env``
holds only values from the frozen file, each checked against a pattern, so the driver can source it safely.
Nothing here reads a result; nothing in the product reads these files.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = REPO / "tools" / "eval" / "scenarios.json"
MANIFEST = REPO / "deploy" / "kind" / "incident.yaml"
SAFE = re.compile(r"[A-Za-z0-9_.:=-]{1,64}", re.ASCII)
LINES = {"DB_POOL_MAX": '            - {name: DB_POOL_MAX, value: "16"}',
         "DEMAND": '            - {name: DEMAND, value: "ramp:2:8:30:75"}',
         "PLANTED": '            - {name: PLANTED, value: "1"}'}
COLLECTION_KEYS = {"session_seconds", "probe_interval_seconds", "final_wait_seconds", "incident_window_seconds",
                   "action_at_seconds", "ordering_rules", "no_events", "pod_logs", "declared_limit",
                   "log_rotation_seconds"}


def load(path=None):
    data = Path(path or SCENARIOS).read_bytes()
    doc = json.loads(data)
    return doc, "sha256:" + hashlib.sha256(data).hexdigest()


def scenario(doc, sid):
    for s in doc["scenarios"]:
        if s["id"] == sid:
            return s
    raise SystemExit(f"unknown scenario {sid}")


def collection(doc, s):
    """The effective collection configuration of scenario ``s``: the file's, overridden by the scenario's."""
    config = dict(doc["collection"])
    config.setdefault("log_rotation_seconds", 5)
    for key, value in (s.get("collection") or {}).items():
        if key not in COLLECTION_KEYS:
            raise SystemExit(f"unknown collection key {key}")
        config[key] = value
    window = config["incident_window_seconds"]
    if not (isinstance(window, list) and len(window) == 2 and 0 <= window[0] < window[1] <= config["session_seconds"]):
        raise SystemExit("bad incident window")
    return config


def render_manifest(initial, namespace="ca-incident"):
    text = MANIFEST.read_text(encoding="utf-8")
    for key, line in LINES.items():
        value = initial[key]
        if not SAFE.fullmatch(value) or text.count(line) != 1:
            raise SystemExit(f"cannot render {key}")
        text = text.replace(line, line.split("value:")[0] + f'value: "{value}"}}')
    if namespace != "ca-incident":
        if not SAFE.fullmatch(namespace):
            raise SystemExit("bad namespace")
        text = text.replace("namespace: ca-incident", f"namespace: {namespace}").replace(
            "metadata: {name: ca-incident}", f"metadata: {{name: {namespace}}}")
    return text


def expected_runs(doc):
    """The pre-registered run set: (scenario, repetition) for every repetition of every scenario."""
    return {(s["id"], rep) for s in doc["scenarios"] for rep in range(1, s["repetitions"] + 1)}


def order(doc):
    runs, most = [], max(s["repetitions"] for s in doc["scenarios"])
    for rep in range(1, most + 1):
        for s in doc["scenarios"]:
            if rep <= s["repetitions"]:
                runs.append(f"{s['id']} {rep}")
    return runs


def render(doc, sid, outdir):
    s = scenario(doc, sid)
    out = Path(outdir)
    (out / "incident.yaml").write_text(render_manifest(s["initial"]), encoding="utf-8")
    if s.get("other_namespace"):
        (out / "other.yaml").write_text(render_manifest(s["initial"], "ca-other"), encoding="utf-8")
    action = s["action"]
    env = action.get("env", {})
    c = collection(doc, s)
    params = {"ACTION_TYPE": action["type"], "ACTION_NS": action["namespace"],
              "ACTION_ENV": " ".join(f"{k}={v}" for k, v in sorted(env.items())),
              "RBAC": s["rbac"], "LOG_MAX_BYTES": str(s["log_max_bytes"] or ""),
              "OTHER_NS": "ca-other" if s.get("other_namespace") else "",
              "SESSION_SECONDS": str(c["session_seconds"]), "PROBE_INTERVAL": str(c["probe_interval_seconds"]),
              "FINAL_WAIT": str(c["final_wait_seconds"]), "ACTION_AT": str(c["action_at_seconds"]),
              "WINDOW": f"{c['incident_window_seconds'][0]}:{c['incident_window_seconds'][1]}",
              "ORDERING_RULES": str(c["ordering_rules"]), "LOG_ROTATION": str(c["log_rotation_seconds"])}
    for value in params.values():
        if value and not all(SAFE.fullmatch(part) for part in value.split(" ")):
            raise SystemExit("unsafe parameter")
    (out / "params.env").write_text("".join(f"{k}='{v}'\n" for k, v in params.items()), encoding="ascii")
    (out / "config.json").write_text(json.dumps(c, sort_keys=True), encoding="ascii")


def main(argv):
    path = None
    if argv[:1] == ["--file"]:
        path, argv = argv[1], argv[2:]
    doc, digest = load(path)
    if argv[:1] == ["order"]:
        print("\n".join(order(doc)))
    elif argv[:1] == ["render"] and len(argv) == 3:
        render(doc, argv[1], argv[2])
    elif argv[:1] == ["digest"]:
        print(digest)
    elif argv[:1] == ["config"] and len(argv) == 2:
        print(json.dumps(collection(doc, scenario(doc, argv[1])), sort_keys=True))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
