"""CA-P2-007a scenario driver helper (standard library only): read the frozen scenario file, render manifests.

  scenario.py order                       the run order: round-robin over repetitions (fixed, frozen)
  scenario.py render ID OUTDIR            write OUTDIR/incident.yaml (and other.yaml) and OUTDIR/params.env

Manifests are rendered from the reviewed deploy/kind/incident.yaml by exact line replacement only; any line not
found is an error. ``params.env`` holds only values from the frozen file, each checked against a pattern, so the
driver can source it safely. Nothing here reads a result; nothing in the product reads this file.
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


def load():
    data = SCENARIOS.read_bytes()
    doc = json.loads(data)
    return doc, "sha256:" + hashlib.sha256(data).hexdigest()


def scenario(doc, sid):
    for s in doc["scenarios"]:
        if s["id"] == sid:
            return s
    raise SystemExit(f"unknown scenario {sid}")


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
    params = {"ACTION_TYPE": action["type"], "ACTION_NS": action["namespace"],
              "ACTION_ENV": " ".join(f"{k}={v}" for k, v in sorted(env.items())),
              "RBAC": s["rbac"], "LOG_MAX_BYTES": str(s["log_max_bytes"] or ""),
              "OTHER_NS": "ca-other" if s.get("other_namespace") else ""}
    for value in params.values():
        if value and not all(SAFE.fullmatch(part) for part in value.split(" ")):
            raise SystemExit("unsafe parameter")
    (out / "params.env").write_text("".join(f"{k}='{v}'\n" for k, v in params.items()), encoding="ascii")


def main(argv):
    doc, digest = load()
    if argv[:1] == ["order"]:
        print("\n".join(order(doc)))
    elif argv[:1] == ["render"] and len(argv) == 3:
        render(doc, argv[1], argv[2])
    elif argv[:1] == ["digest"]:
        print(digest)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
