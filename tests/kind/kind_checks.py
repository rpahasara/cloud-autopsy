"""CA-P2-004e checks run by the ``collector-kind`` CI job against its own disposable kind cluster.

  kind_checks.py rbac  --server URL --ca-file CA --token-file TOKEN
      Sends requests the collector's Role must refuse, with the collector's short-lived token, through
      a test-only raw request function (deliberately bypassing the collector's allowlist). Every one
      must be refused with 403; the allowlisted client must refuse to even form them. One permitted
      list is checked to return 200, so a broken token cannot pass as "refused".
  kind_checks.py run   --out DIR --token-file TOKEN --expect consistent|truncated|denied|unavailable
      Checks a collector run: outcomes, fail-closed batches (never complete/empty, zero verified
      coverage), honest abstention, and that no planted value or the token appears in anything written.
  kind_checks.py db    --json FILE
      Checks the database-verified creation output: verified, byte-identical, abstained.

Synthetic data only. Prints codes and counts, never response bodies or the token.
"""

import argparse
import http.client
import json
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.app import bundle as B  # noqa: E402
from cloud_autopsy.app import create as C  # noqa: E402
from cloud_autopsy.collector import client as cl  # noqa: E402
from cloud_autopsy.contracts import acquisition as acq  # noqa: E402
from cloud_autopsy.contracts import frozen_input as fi  # noqa: E402

PLANTED = ("PLANTED-ENV-VALUE-7c1", "PLANTED-ANNOTATION-91d", "PLANTED-CONFIG-VALUE-c44", "PLANTED-SECRET-VALUE-d17",
           "last-applied-configuration", "secretKeyRef", "Back-off", "Error:", "Scaled up", "Created container",
           "does-not-exist", "no such file")
# (method, path, why it must be refused)
REFUSALS = (
    ("GET", "/api/v1/namespaces/ca-demo/secrets", "secrets"),
    ("GET", "/api/v1/namespaces/ca-demo/secrets/checkout-db", "a secret"),
    ("GET", "/api/v1/namespaces/ca-demo/configmaps", "configmaps"),
    ("GET", "/api/v1/namespaces/ca-demo/configmaps/checkout-db-pool", "a configmap"),
    ("GET", "/api/v1/namespaces/ca-demo/pods?watch=1", "watch"),
    ("GET", "/api/v1/namespaces/ca-other/pods", "another namespace"),
    ("GET", "/apis/apps/v1/namespaces/ca-other/deployments", "another namespace"),
    ("GET", "/api/v1/nodes", "cluster-scoped nodes"),
    ("GET", "/api/v1/namespaces", "cluster-scoped namespaces"),
    ("GET", "/api/v1/pods", "pods in all namespaces"),
    ("POST", "/api/v1/namespaces/ca-demo/pods", "create"),
    ("PATCH", "/apis/apps/v1/namespaces/ca-demo/deployments/checkout-api", "patch"),
    ("PUT", "/apis/apps/v1/namespaces/ca-demo/deployments/checkout-api", "update"),
    ("DELETE", "/apis/apps/v1/namespaces/ca-demo/replicasets", "deletecollection"),
    ("DELETE", "/api/v1/namespaces/ca-demo/pods/{pod}", "delete"),
    ("GET", "/api/v1/namespaces/ca-demo/pods/{pod}/log", "pods/log"),
    ("POST", "/api/v1/namespaces/ca-demo/pods/{pod}/exec?command=ls&stdout=true", "pods/exec"),
    ("POST", "/api/v1/namespaces/ca-demo/pods/{pod}/portforward", "pods/portforward"),
    ("GET", "/api/v1/namespaces/ca-demo/pods/{pod}/proxy/", "pods/proxy"),
    ("GET", "/apis/apps/v1/namespaces/ca-demo/deployments/checkout-api/scale", "deployments/scale"),
    ("POST", "/api/v1/namespaces/ca-collector/serviceaccounts/ca-collector/token", "tokenrequest"),
    ("GET", "/apis/rbac.authorization.k8s.io/v1/namespaces/ca-demo/roles", "rbac"),
)


def fail(message):
    print(f"FAIL: {message}")
    sys.exit(1)


def raw_request(server, ca_file, token, method, path):
    """Test-only: an arbitrary request with the collector token (never used by the collector)."""
    parts = urlsplit(server)
    context = ssl.create_default_context(cafile=str(ca_file))
    con = http.client.HTTPSConnection(parts.hostname, parts.port, context=context, timeout=20)
    body = b"{}" if method in ("POST", "PUT", "PATCH") else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if method == "PATCH":
        headers["Content-Type"] = "application/merge-patch+json"
    elif body is not None:
        headers["Content-Type"] = "application/json"
    try:
        con.request(method, path, body=body, headers=headers)
        response = con.getresponse()
        data = response.read(1_048_576)
        return response.status, data
    finally:
        con.close()


def rbac(args):
    token = Path(args.token_file).read_text(encoding="ascii").strip()
    status, body = raw_request(args.server, args.ca_file, token, "GET", "/api/v1/namespaces/ca-demo/pods?limit=50")
    if status != 200:
        fail(f"the permitted list answered {status}; refusals below would prove nothing")
    pods = [i["metadata"]["name"] for i in json.loads(body)["items"]]
    if not pods:
        fail("no pods to probe")
    refused = 0
    for method, path, why in REFUSALS:
        path = path.format(pod=pods[0])
        status, _ = raw_request(args.server, args.ca_file, token, method, path)
        if status != 403:
            fail(f"{method} {path.split('?')[0]} ({why}) answered {status}, expected 403")
        refused += 1
    for resource in ("secrets", "configmaps", "pods/log", "pods/exec", "nodes", "namespaces"):
        try:
            cl.build_path(resource, "ca-demo", 10)
            fail(f"the allowlisted client formed a request for {resource}")
        except cl.CollectorError:
            pass
    try:
        cl.build_path("pods", "ca-other", 10)
    except cl.CollectorError:
        fail("the namespace is configuration, not part of the allowlist check")
    print(f"rbac: {refused} forbidden requests refused with 403; permitted list 200; allowlist refuses all six")


def scan(out, token):
    found = []
    needles = [p.encode() for p in PLANTED] + [token.encode()]
    for path in sorted(Path(out).rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            found += [f"{path.name}:{n.decode()[:12]}..." for n in needles if n in data]
    return found


def run(args):
    out = Path(args.out)
    report = json.loads((out / "report.json").read_bytes())
    token = Path(args.token_file).read_text(encoding="ascii").strip() if args.token_file else "\x00none"
    leaks = scan(out, token)
    if leaks:
        fail(f"planted or secret values written: {leaks}")
    outcomes = {c["resource"]: c["outcome"] for c in report["collections"]}
    print("collections:", {c["resource"]: (c["outcome"], c["items"], c["pages"], c["collection_resource_version"])
                           for c in report["collections"]})
    if report["verified_coverage_ms"] != 0:
        fail("verified coverage claimed")
    acquisitions = {a["query_id"]: (a["outcome"], a["reason"], a["coverage_claimed"])
                    for a in report["conversion"]["acquisitions"]}
    print("acquisitions:", acquisitions)
    if any(claimed for _, _, claimed in acquisitions.values()):
        fail("an acquisition claims coverage")
    loaded = B.load(out / "bundle")
    if [b for b in loaded.batches if b["outcome"] in ("complete", "empty")]:
        fail("a collector batch is complete or empty")
    frozen = fi.seal(loaded.plan, loaded.registry, list(loaded.batches))
    if any(a["verified_ms"] for a in frozen.root()["acquisitions"]):
        fail("verified milliseconds in the frozen input")
    inv = C.investigate_offline(loaded)
    if inv.result["outcome"]["status"] != "abstained":
        fail(f"the investigation is {inv.result['outcome']['status']}, expected abstained")
    expect = args.expect
    if expect == "consistent":
        if set(outcomes.values()) != {"consistent"}:
            fail(f"expected every collection consistent: {outcomes}")
        for query in ("k8s.pods", "k8s.deployments", "k8s.events"):
            if acquisitions[query][:2] != ("partial", "continuity_lost"):
                fail(f"{query} is {acquisitions[query]}, expected partial/continuity_lost")
        if acquisitions["k8s.configmaps"][:2] != ("failed", "source_unavailable"):
            fail("ConfigMaps must be unrecorded (never collected)")
        kinds = {e.observation_kind for b in loaded.batches
                 for e in acq.decode_batch(b, loaded.plan, loaded.registry).evidence}
        for needed in ("pod", "replicaset", "deployment_rollout", "k8s_event"):
            if needed not in kinds:
                fail(f"no {needed} evidence from the cluster")
        if any(c["collection_resource_version"] is None for c in report["collections"]):
            fail("no collection resourceVersion recorded")
        if max(c["pages"] for c in report["collections"]) < 2:
            fail("no collection paginated: the resourceVersion check across pages was not exercised")
    elif expect == "truncated":
        if not {"truncated"} & set(outcomes.values()):
            fail(f"expected a truncated collection: {outcomes}")
        if not [q for q, (o, r, _) in acquisitions.items() if (o, r) == ("partial", "page_limit")]:
            fail("expected a partial/page_limit acquisition")
    elif expect in ("denied", "unavailable"):
        if set(outcomes.values()) != {expect}:
            fail(f"expected every collection {expect}: {outcomes}")
        if [b for b in loaded.batches if b["observations"]]:
            fail("a failed collection produced observations")
    print(f"run ({expect}): ok; abstained; no planted value, token or event text written")


def db(args):
    rows = json.loads(Path(args.json).read_bytes())
    if len(rows) != 1 or rows[0].get("status") != "ok" or rows[0].get("verified") is not True:
        fail(f"database creation did not verify: {[{k: r.get(k) for k in ('status', 'stage', 'reason')} for r in rows]}")
    if rows[0].get("outcome") != "abstained":
        fail(f"the database-verified investigation is {rows[0].get('outcome')}, expected abstained")
    print("db: created, stored once, verified on read, byte-identical to offline, abstained")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("rbac")
    p.add_argument("--server", required=True)
    p.add_argument("--ca-file", required=True)
    p.add_argument("--token-file", required=True)
    p = sub.add_parser("run")
    p.add_argument("--out", required=True)
    p.add_argument("--token-file")
    p.add_argument("--expect", required=True, choices=("consistent", "truncated", "denied", "unavailable"))
    p = sub.add_parser("db")
    p.add_argument("--json", required=True)
    args = parser.parse_args()
    {"rbac": rbac, "run": run, "db": db}[args.command](args)


if __name__ == "__main__":
    main()
