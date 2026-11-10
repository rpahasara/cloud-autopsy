"""Local demonstration of the read-only investigation API (CA-P2-006b), synthetic data only.

Against a disposable database it:
  1. persists, seals and investigates all six synthetic variants and stores each result through
     the verifying write path (plus one extra copy of ``config-cause`` used for a tamper check);
  2. provisions two bearer tokens into the private per-session secret directory (hashes only in
     the grants file): ``reviewer`` granted all seven runs, ``single-run`` granted one;
  3. starts the API on 127.0.0.1 (ephemeral port) and, over HTTP, retrieves for every variant
     the verified result, timeline, hypotheses, citations and every cited evidence record,
     checking that the served result bytes equal the stored bytes;
  4. checks refusals: no token, a wrong token, a run outside the token's grant, an unknown run,
     a write method, and a tampered stored result (409, no data).
It writes the summary to ``out/ca-p2-006b/summary.json`` and exits non-zero on any failure.
"""

import argparse
import hashlib
import http.client
import json
import sys
import threading
import uuid
from pathlib import Path

from ..api import grants as G
from ..api import server
from ..contracts import canonical
from ..engine import RESULT_DIGEST_ALGORITHM
from ..synthetic import scenario_001 as scenario
from . import pipeline
from .disposable import DisposableDatabase


def _get(port, path, token=None, method="GET"):
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    con.request(method, path, headers={"Authorization": f"Bearer {token}"} if token else {})
    response = con.getresponse()
    body = response.read()
    con.close()
    return response.status, json.loads(body), len(body)


def _tamper(database, run_id, stored_bytes):
    """Rewrite a stored result in place, bypassing every trigger, as direct database access would."""
    doc = canonical.loads(stored_bytes)
    body = {k: v for k, v in doc.items() if k != "result_digest"}
    body["outcome"]["reasons"] = sorted(set(body["outcome"]["reasons"]) | {"forged"})
    body["result_digest"] = f"{RESULT_DIGEST_ALGORITHM}:{hashlib.sha256(canonical.canonical_bytes(body)).hexdigest()}"
    forged = canonical.canonical_bytes(body)
    admin = database._superuser(database.name)
    try:
        with admin.transaction():
            admin.run("SET LOCAL session_replication_role = replica")
            admin.run("UPDATE ca.investigation_result SET result_bytes = :b, result_bytes_sha256 = :h, "
                      "result_digest = :d WHERE run_id = CAST(:r AS uuid)", b=forged,
                      h=hashlib.sha256(forged).hexdigest(), d=body["result_digest"], r=run_id)
    finally:
        admin.close()


def run(database, out_dir):
    roles = database.roles
    runs, stored = {}, {}
    for key, variant in [(v, v) for v in scenario.VARIANTS] + [("tamper-check", "config-cause")]:
        run_id, _, _ = pipeline.persist_and_seal(roles, variant)
        _, investigation = pipeline.record_result(roles["ca_engine"], roles["ca_result_writer"], run_id)
        runs[key], stored[key] = run_id, investigation

    missing = str(uuid.uuid4())  # granted, but no such run: must be 404, not data
    record, tokens = G.issue({"reviewer": list(runs.values()) + [missing], "single-run": [runs["config-cause"]]})
    grants_path = database.secret_dir / "api-grants.json"
    G.write_private(grants_path, json.dumps(record).encode("utf-8"))
    connect = server.engine_connector(database.host, database.port, database.name, database.passwords["ca_engine"])
    api = server.build(grants_path, connect, quiet=True)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    port, token = api.port, tokens["reviewer"]
    rows, checks = [], {}
    try:
        checks["healthz"] = _get(port, "/healthz")[0] == 200
        checks["readyz"] = _get(port, "/readyz")[0] == 200
        for variant in scenario.VARIANTS:
            run_id, inv = runs[variant], stored[variant]
            status, body, size = _get(port, f"/v1/runs/{run_id}/result", token)
            same_bytes = status == 200 and canonical.canonical_bytes(body["data"]) == inv.result_bytes
            routes_ok = all(_get(port, f"/v1/runs/{run_id}/{r}", token)[0] == 200
                            for r in ("timeline", "hypotheses", "citations"))
            cites = _get(port, f"/v1/runs/{run_id}/citations", token)[1]["data"]
            cited = sorted({e for h in cites["hypotheses"] for e in h["cited_evidence_ids"]})
            evidence_ok = all(_get(port, f"/v1/runs/{run_id}/evidence/{e.split(':')[1]}", token)[0] == 200
                              for e in cited)
            outcome = body["data"]["outcome"] if status == 200 else {}
            rows.append({"variant": variant, "run_id": run_id, "status": status,
                         "verified": status == 200 and body["verified"],
                         "result_digest": body.get("result_digest"), "served_bytes_equal_stored": same_bytes,
                         "outcome": outcome.get("status"), "mechanism": outcome.get("mechanism"),
                         "outcome_citations": len(outcome.get("evidence_ids", [])),
                         "cited_evidence_served": len(cited), "evidence_ok": evidence_ok,
                         "routes_ok": routes_ok, "response_bytes": size})
        allowed = runs["config-cause"]
        refusals = {
            "no_token": _get(port, f"/v1/runs/{allowed}/result")[0] == 401,
            "wrong_token": _get(port, f"/v1/runs/{allowed}/result", "x" * 43)[0] == 401,
            "outside_grant": _get(port, f"/v1/runs/{runs['no-symptom']}/result", tokens["single-run"])[0] == 403,
            "inside_grant": _get(port, f"/v1/runs/{allowed}/result", tokens["single-run"])[0] == 200,
            "unknown_run": _get(port, f"/v1/runs/{missing}/result", token)[0] == 404,
            "ungranted_run": _get(port, f"/v1/runs/{uuid.uuid4()}/result", token)[0] == 403,
            "write_method": _get(port, f"/v1/runs/{allowed}/result", token, "POST")[0] == 405,
        }
        before = _get(port, f"/v1/runs/{runs['tamper-check']}/result", token)[0]
        _tamper(database, runs["tamper-check"], stored["tamper-check"].result_bytes)
        status, body, _ = _get(port, f"/v1/runs/{runs['tamper-check']}/result", token)
        refusals["tampered_result"] = before == 200 and status == 409 and "data" not in body
        checks.update(refusals)
    finally:
        api.shutdown()
        api.server_close()
    ok = all(checks.values()) and all(r["served_bytes_equal_stored"] and r["routes_ok"] and r["evidence_ok"]
                                       for r in rows)
    summary = {"scope": "synthetic-only local demonstration on 127.0.0.1; not an evaluation or deployment",
               "api": "ca-api/0.1-provisional", "checks": checks, "variants": rows, "all_checks_passed": ok}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_bytes(canonical.canonical_bytes(summary))
    return summary


def _print(summary):
    print(f"{'variant':22} {'http':4} {'verified':8} {'outcome':9} {'mechanism':23} {'cites':>5} {'evid':>4} "
          f"{'bytes=stored':12} result digest")
    for r in summary["variants"]:
        print(f"{r['variant']:22} {r['status']:<4} {str(r['verified']):8} {str(r['outcome']):9} "
              f"{str(r['mechanism']):23} {r['outcome_citations']:>5} {r['cited_evidence_served']:>4} "
              f"{'yes' if r['served_bytes_equal_stored'] else 'NO':12} {str(r['result_digest']).split(':')[-1][:16]}")
    print("checks: " + ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in summary["checks"].items()))
    print("all checks passed" if summary["all_checks_passed"] else "CHECK FAILED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="out/ca-p2-006b")
    args = parser.parse_args(argv)
    with DisposableDatabase.from_environment() as database:
        summary = run(database, args.out)
    _print(summary)
    return 0 if summary["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
