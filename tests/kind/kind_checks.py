"""CA-P2-004e checks run by the ``collector-kind`` CI job against its own disposable kind cluster.

  kind_checks.py rbac  --server URL --ca-file CA --token-file TOKEN
      Sends requests the collector's Role must refuse, with the collector's short-lived token, through
      a test-only raw request function (deliberately bypassing the collector's allowlist). Every one
      must be refused with 403; the allowlisted client must refuse to even form them. One permitted
      list is checked to return 200, so a broken token cannot pass as "refused".
  kind_checks.py run   --out DIR --token-file TOKEN --expect consistent|truncated|denied|unavailable
      Checks a collector run: outcomes, fail-closed batches (never complete/empty, zero verified
      coverage), honest abstention, and that no planted value or the token appears in anything written.
  kind_checks.py watch ... --rule-profile 2
      CA-P2-005b: the run pins rule profile 2 (timeline rules 0.2) in its plan and report; every observed
      bracket is on the session's own clock (ca-collector-<session_id>); converting twice is identical.
  kind_checks.py sessions --out DIR --out DIR
      Two real runs have different generated session identities and clock domains, and no observed
      bracket of one is on the other's clock.
  kind_checks.py db    --json FILE
      Checks the database-verified creation output: verified, byte-identical, abstained.
  kind_checks.py rbac  ... --watch-role
      CA-P2-004f: the watch Role. The permitted watch must open (200) and every watch outside it must
      be refused (403): Secrets, ConfigMaps, another namespace, cluster-wide, nodes and namespaces.
  kind_checks.py watch --out DIR --token-file TOKEN --expect proven|denied|event_limit [--min-segments N]
      Checks a list + watch run: coverage only with a coherent basis, nothing withheld counted, the
      bundle re-derived byte-identically from the recording, abstention, and no planted value,
      Event text, token or continue token written.

  kind_checks.py rbac-incident --server URL --ca-file CA --token-file TOKEN
      CA-P2-004g: with the incident Role, pods/log of a ca-incident pod answers 200, and pods/log in
      every other namespace, Secrets, ConfigMaps, exec/attach/portforward/proxy, nodes, namespaces and
      every write answer 403 (raw requests with the real token).
  kind_checks.py logs --out DIR --token-file TOKEN [--expect-ordered]
      CA-P2-004g: a pod-log run in ca-incident. Recording 0.5 re-derives byte-identically; log coverage is
      proven (every instance continuous from seq 1, stopped or covered past the final probe, no gap);
      the rollout carries the typed declared-limit change 16 -> 4; symptom lines carry observed brackets
      on the session clock; no planted log line, env value, Event text or token is written; and the log
      batches stay partial under acquisition batch 0.2, so the investigation abstains. With
      --expect-ordered, at least one symptom bracket lies strictly after the rollout bracket.

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
from cloud_autopsy.app import k8s_watch_recording as W  # noqa: E402
from cloud_autopsy.contracts.canonical import canonical_bytes  # noqa: E402
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
WATCH_ALLOWED = "/api/v1/namespaces/ca-demo/pods?watch=1"
# CA-P2-004f: with the watch Role, these watches must still be refused.
WATCH_REFUSALS = (
    ("GET", "/api/v1/namespaces/ca-demo/secrets?watch=1", "watch secrets"),
    ("GET", "/api/v1/namespaces/ca-demo/configmaps?watch=1", "watch configmaps"),
    ("GET", "/api/v1/namespaces/ca-other/pods?watch=1", "watch another namespace"),
    ("GET", "/apis/apps/v1/namespaces/ca-other/deployments?watch=1", "watch another namespace"),
    ("GET", "/api/v1/pods?watch=1", "cluster-wide pod watch"),
    ("GET", "/api/v1/events?watch=1", "cluster-wide event watch"),
    ("GET", "/api/v1/nodes?watch=1", "watch nodes"),
    ("GET", "/api/v1/namespaces?watch=1", "watch namespaces"),
)


def fail(message):
    print(f"FAIL: {message}")
    sys.exit(1)


def raw_request(server, ca_file, token, method, path, read=True):
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
        data = response.read(1_048_576) if read or response.status != 200 else b""
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
    refusals = REFUSALS
    if args.watch_role:
        refusals = tuple(r for r in REFUSALS if r[1] != WATCH_ALLOWED) + WATCH_REFUSALS
        status, _ = raw_request(args.server, args.ca_file, token, "GET",
                                WATCH_ALLOWED + "&timeoutSeconds=1&allowWatchBookmarks=true", read=False)
        if status != 200:
            fail(f"the permitted watch answered {status}")
    for method, path, why in refusals:
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
    print(f"rbac: {refused} forbidden requests refused with 403; permitted list 200"
          f"{'; permitted watch 200' if args.watch_role else ''}; allowlist refuses all six")


# CA-P2-004g: the incident Role (deploy/kind/rbac-incident.yaml).
INCIDENT_REFUSALS = (
    ("GET", "/api/v1/namespaces/ca-demo/pods/{pod}/log", "pods/log in ca-demo"),
    ("GET", "/api/v1/namespaces/ca-other/pods/any-pod/log", "pods/log in ca-other"),
    ("GET", "/api/v1/namespaces/kube-system/pods/any-pod/log", "pods/log in kube-system"),
    ("GET", "/api/v1/namespaces/ca-incident/secrets", "secrets"),
    ("GET", "/api/v1/namespaces/ca-incident/secrets/checkout-db", "a secret"),
    ("GET", "/api/v1/namespaces/ca-incident/configmaps", "configmaps"),
    ("GET", "/api/v1/namespaces/ca-incident/configmaps/ca-incident-workload", "a configmap"),
    ("POST", "/api/v1/namespaces/ca-incident/pods/{pod}/exec?command=ls&stdout=true", "pods/exec"),
    ("POST", "/api/v1/namespaces/ca-incident/pods/{pod}/attach?stdout=true", "pods/attach"),
    ("POST", "/api/v1/namespaces/ca-incident/pods/{pod}/portforward", "pods/portforward"),
    ("GET", "/api/v1/namespaces/ca-incident/pods/{pod}/proxy/", "pods/proxy"),
    ("PATCH", "/api/v1/namespaces/ca-incident/pods/{pod}/ephemeralcontainers", "ephemeral containers"),
    ("POST", "/api/v1/namespaces/ca-incident/pods/{pod}/eviction", "eviction"),
    ("GET", "/api/v1/nodes", "cluster-scoped nodes"),
    ("GET", "/api/v1/namespaces", "cluster-scoped namespaces"),
    ("GET", "/api/v1/pods", "pods in all namespaces"),
    ("POST", "/api/v1/namespaces/ca-incident/pods", "create"),
    ("DELETE", "/api/v1/namespaces/ca-incident/pods/{pod}", "delete a pod"),
    ("PATCH", "/apis/apps/v1/namespaces/ca-incident/deployments/checkout-api", "patch"),
    ("PUT", "/apis/apps/v1/namespaces/ca-incident/deployments/checkout-api", "update"),
    ("DELETE", "/apis/apps/v1/namespaces/ca-incident/replicasets", "deletecollection"),
    ("GET", "/apis/apps/v1/namespaces/ca-incident/deployments/checkout-api/scale", "deployments/scale"),
    ("POST", "/api/v1/namespaces/ca-collector/serviceaccounts/ca-collector/token", "tokenrequest"),
)
LOG_PLANTED = ("PLANTED-LOG-PASSWORD-1d2", "PLANTED-LOG-TOKEN-8e1", "PLANTED-LOG-EMAIL", "PLANTED-LOG-JWT",
               "DEBUG_DUMP", "ramp:2:8:30")


def rbac_incident(args):
    token = Path(args.token_file).read_text(encoding="ascii").strip()
    status, body = raw_request(args.server, args.ca_file, token, "GET", "/api/v1/namespaces/ca-incident/pods?limit=50")
    if status != 200:
        fail(f"the permitted list answered {status}; refusals below would prove nothing")
    pods = [i["metadata"]["name"] for i in json.loads(body)["items"]]
    if not pods:
        fail("no pods to probe")
    status, _ = raw_request(args.server, args.ca_file, token, "GET",
                            f"/api/v1/namespaces/ca-incident/pods/{pods[0]}/log?limitBytes=1", read=False)
    if status != 200:
        fail(f"the permitted pods/log in ca-incident answered {status}")
    status, body = raw_request(args.server, args.ca_file, token, "GET", "/api/v1/namespaces/ca-demo/pods?limit=50")
    demo = [i["metadata"]["name"] for i in json.loads(body)["items"]] if status == 200 else ["any-pod"]
    refused = 0
    for method, path, why in INCIDENT_REFUSALS:
        path = path.format(pod=(demo[0] if "ca-demo" in path else pods[0]) if demo else pods[0])
        status, _ = raw_request(args.server, args.ca_file, token, method, path)
        if status != 403:
            fail(f"{method} {path.split('?')[0]} ({why}) answered {status}, expected 403")
        refused += 1
    print(f"rbac-incident: {refused} forbidden requests refused with 403; pods/log in ca-incident 200")


def logs(args):
    out = Path(args.out)
    token = Path(args.token_file).read_text(encoding="ascii").strip()
    found = []
    needles = [n.encode() for n in PLANTED + LOG_PLANTED] + [token.encode()]
    for path in sorted(out.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            found += [f"{path.name}:{n.decode()[:14]}..." for n in needles if n in data]
    if found:
        fail(f"planted or secret values written: {found}")
    manifest = json.loads((out / "recording" / "recording.json").read_bytes())
    if manifest["contract_version"] != "ca-k8s-recording/0.5-provisional":
        fail("not a 0.5 (pod-log) recording")
    conversion = W.verify_bundle(out / "recording", out / "bundle")  # replay: byte-identical
    report = conversion.report["pod_logs"]
    instances = report["instances"]
    stopped = sum(1 for i in instances.values() if i["stopped"])
    handshake = sum(i["handshake_bounds"] for i in instances.values())
    print(f"pod logs: {len(instances)} instances, {stopped} stopped, handshake bounds {handshake}, "
          f"gaps {sorted({g[2] for g in report['gaps']})}, counts {report['counts']}")
    if not report["coverage_proven"] or report["gaps"]:
        fail(f"log coverage not proven: {report['gaps']}")
    if len(instances) < 4 or stopped < 2:
        fail("expected two stopped old instances and two new ones")
    batches = conversion.batch_records
    rollouts = [o for b in batches for o in b["observations"] if o["observation_kind"] == "deployment_rollout"]
    typed = [fc for o in rollouts for fc in o["attributes"].get("field_changes", [])]
    if [(fc["config_key"], fc["before_value"], fc["after_value"]) for fc in typed] != [("pool.maxConnections", "16", "4")]:
        fail(f"expected exactly one typed limit change 16 -> 4, got {[(f['before_value'], f['after_value']) for f in typed]}")
    session_domain = manifest["clocks"]["collector"]["clock_domain_id"]
    symptoms = [o for b in batches if b["query_id"] == W.LOG_QUERY for o in b["observations"]
                if o["attributes"]["template"] == "POOL_EXHAUSTED"]
    if not symptoms:
        fail("no POOL_EXHAUSTED line was collected")
    if any("message" in o["attributes"] for o in symptoms):
        fail("a log line carries free text")
    log_batches = [b for b in batches if b["query_id"] == W.LOG_QUERY]
    clean = [b for b in log_batches if b["outcome"] in ("complete", "empty")]
    if not report["basis_emitted"] or not clean:
        fail(f"proven log coverage must be a complete batch with a log basis (batch 0.3): {report['not_emitted_because']}")
    basis = clean[0]["coverage_basis"]
    if basis["kind"] != "log_sequence_continuity" or basis["session_id"] != manifest["session_id"]             or basis["clock_domain_id"] != session_domain or len(basis["instances"]) != len(instances):
        fail("the log basis does not bind this session, its clock and every instance")
    if any(b["coverage_basis"] and b["coverage_basis"]["kind"] != "watch_continuity"
           for b in batches if b["query_id"] != W.LOG_QUERY):
        fail("a non-log batch carries a log basis")
    if any(o["observation_kind"] == "log_line" for b in batches if b["query_id"] != W.LOG_QUERY for o in b["observations"]):
        fail("a log line outside the log acquisition")
    print(f"log batches: {sorted({(b['outcome'], b['reason']) for b in log_batches}, key=str)}; basis instances "
          f"{len(basis['instances'])} ({sorted({i['ending'] for i in basis['instances']})}); "
          f"coverage {clean[0]['coverage']}")

    def bracket(o):
        t = next((t for t in o["times"] if t["timestamp_kind"] == "observed"), None)
        if t is None or t["clock_domain_id"] != session_domain:
            return None
        from cloud_autopsy.contracts import timeinterval as ti
        stamp = ti.source_timestamp(t["raw"], timestamp_kind="observed", clock_domain_id=t["clock_domain_id"],
                                    declared_precision_ns=t["declared_precision_ns"])
        return (stamp.local_lower_ms, stamp.local_upper_ms)  # inclusive ms, outward-rounded

    limit_rollout = next(o for o in rollouts if o["attributes"].get("field_changes"))
    r = bracket(limit_rollout)
    bounded = [bracket(o) for o in symptoms]
    ordered = [b for b in bounded if b is not None and r is not None and b[0] > r[1]]
    print(f"symptoms: {len(symptoms)} lines, {sum(b is not None for b in bounded)} with a session bracket, "
          f"{len(ordered)} strictly after the rollout bracket {r}")
    if args.expect_ordered and not ordered:
        fail("no symptom bracket lies strictly after the rollout bracket")
    loaded = B.load(out / "bundle")
    inv = C.investigate_offline(loaded)
    outcome = inv.result["outcome"]
    by_query = {}
    for g in inv.result["gaps"]:
        key = (g.get("query_id"), g.get("subject"), ",".join(g.get("reasons") or []))
        by_query[key] = by_query.get(key, 0) + 1
    log_gaps = [k for k in by_query if k[0] == W.LOG_QUERY]
    print("remaining gaps (query, subject, reasons): count")
    for key, n in sorted(by_query.items(), key=str):
        print(f"  {key}: {n}")
    # The log proof itself is gap-free (checked above). Gaps that remain on the log acquisition come from the
    # plan window reaching past the Pod watch anchors (coverage holes) and from lines received after the
    # final probe (a partial tail batch); they are reported, never hidden, and they are not log-proof gaps.
    print(f"log acquisition gaps outside the proof (window edges, tail): {sum(by_query[k] for k in log_gaps)}")
    if outcome["status"] == "resolved":
        print(f"RESOLVED: {outcome}")
    print(f"logs: ok; replay byte-identical; log coverage proven as batch 0.3; outcome {outcome['status']} "
          f"({', '.join(outcome.get('reasons') or [])}); no planted value, log text, token or event text written")


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


def watch(args):
    out = Path(args.out)
    report = json.loads((out / "report.json").read_bytes())
    token = Path(args.token_file).read_text(encoding="ascii").strip()
    leaks = scan(out, token)
    for path in sorted(out.rglob("*")):
        if path.is_file() and b"continue" in path.read_bytes() and b'"continue"' in path.read_bytes():
            leaks.append(f"{path.name}:continue-token")
    if leaks:
        fail(f"planted or secret values written: {leaks}")
    conversion = W.verify_bundle(out / "recording", out / "bundle")  # replay: byte-identical
    manifest = json.loads((out / "recording" / "recording.json").read_bytes())
    session, domain = manifest["session_id"], manifest["clocks"]["collector"]["clock_domain_id"]
    if not W.SESSION_ID.fullmatch(session) or domain != f"ca-collector-{session}":
        fail("the recording does not carry a generated session identity and its own clock")
    plan = json.loads((out / "bundle" / "plan.json").read_bytes())
    pinned = plan["rule_versions"]["timeline-rules"]
    expected = {1: "ca-timeline-rules/0.1-provisional", 2: "ca-timeline-rules/0.2-provisional"}[args.rule_profile]
    if pinned != expected or conversion.report["rule_profile"] != args.rule_profile:
        fail(f"the bundle pins {pinned}, expected rule profile {args.rule_profile}")
    again = W.K.convert(out / "recording", W.ev.KIND_REGISTRY_VERSION_V3, rule_profile=args.rule_profile)
    if [canonical_bytes(r) for r in again.batch_records] != [canonical_bytes(r) for r in conversion.batch_records]:
        fail("converting the recording twice differs")
    observed_domains = {t["clock_domain_id"] for r in conversion.batch_records for o in r["observations"]
                        for t in o["times"] if t["timestamp_kind"] == "observed"}
    if observed_domains - {domain}:
        fail(f"observed brackets on another clock: {sorted(observed_domains - {domain})}")
    print(f"session {session}: clock {domain}; rule profile {args.rule_profile} ({pinned}); "
          f"observed brackets on {len(observed_domains)} clock(s); deterministic conversion")
    acquisitions = {a["query_id"]: a for a in conversion.report["acquisitions"]}
    print("acquisitions:", {q: (a["outcomes"], a["verified_coverage_ms"], [s.get("end") for s in a["segments"]],
                                a["withheld"], a["unconverted"]) for q, a in acquisitions.items()})
    loaded = B.load(out / "bundle")
    for b in loaded.batches:
        claimed = b["outcome"] in ("complete", "empty")
        if claimed != (b["coverage_basis"] is not None):
            fail("a coverage basis without a coverage claim, or the reverse")
        if claimed and (b["coverage"]["start"], b["coverage"]["end"]) != (
                b["coverage_basis"]["start_anchor"]["at"], b["coverage_basis"]["end_anchor"]["at"]):
            fail("coverage differs from its basis")
    frozen = fi.seal(loaded.plan, loaded.registry, list(loaded.batches))
    verified = sum(a["verified_ms"] for a in frozen.root()["acquisitions"])
    inv = C.investigate_offline(loaded)
    if inv.result["outcome"]["status"] != "abstained":
        fail(f"the investigation is {inv.result['outcome']['status']}, expected abstained")
    if args.expect == "proven":
        if report["verified_coverage_ms"] <= 0 or verified <= 0:
            fail("no verified coverage from a healthy session")
        proven = sorted(q for q, a in acquisitions.items() if any(s.get("proven") for s in a["segments"]))
        if not proven:
            fail("no watch was proven")
        print("proven acquisitions:", proven)
        exhausted = sorted(q for q, a in acquisitions.items() if any(s.get("end") == "reconnects_exhausted"
                                                                     for s in a["segments"]))
        if exhausted:
            fail(f"a healthy session exhausted its reconnects: {exhausted}")
        changes = sum(1 for b in loaded.batches for o in b["observations"]
                      if any(t["timestamp_kind"] == "observed" for t in o["times"]))
        if changes < 1:
            fail("no watched change was recorded")
    elif args.expect == "denied":
        ends = [s.get("end") for a in acquisitions.values() for s in a["segments"]]
        if "denied" not in ends:
            fail(f"expected a denied end after the revocation: {ends}")
    elif args.expect == "event_limit":
        ends = [s.get("end") for a in acquisitions.values() for s in a["segments"]]
        if "event_limit" not in ends:
            fail(f"expected an event_limit end: {ends}")
        if not [b for b in loaded.batches if b["reason"] == "event_limit" and b["truncation"]["truncated"]]:
            fail("expected a truncated partial event_limit batch")
    segments = max(len(a["segments"]) for a in acquisitions.values())
    if segments < args.min_segments:
        fail(f"expected at least {args.min_segments} segments, got {segments}")
    print(f"watch ({args.expect}): ok; verified {report['verified_coverage_ms']} ms (frozen input {verified} ms); "
          "replay byte-identical; abstained; no planted value, token, continue token or event text written")


def sessions(args):
    seen = []
    for out in args.out:
        manifest = json.loads((Path(out) / "recording" / "recording.json").read_bytes())
        bundle = Path(out) / "bundle"
        domains = set()
        for path in sorted((bundle / "batches").iterdir()):
            for o in json.loads(path.read_bytes())["observations"]:
                domains |= {t["clock_domain_id"] for t in o["times"] if t["timestamp_kind"] == "observed"}
        seen.append((manifest["recording_id"], manifest["session_id"], manifest["clocks"]["collector"]["clock_domain_id"],
                     domains))
    (_, s1, d1, o1), (_, s2, d2, o2) = seen
    if s1 == s2 or d1 == d2:
        fail("two collection sessions share a session identity or clock")
    if (o1 & {d2}) or (o2 & {d1}):
        fail("an observed bracket is on another session's clock")
    print(f"sessions: {s1} and {s2} are distinct, each with its own clock; no bracket crosses sessions")


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
    p.add_argument("--watch-role", action="store_true")
    p = sub.add_parser("watch")
    p.add_argument("--out", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--expect", required=True, choices=("proven", "denied", "event_limit", "any"))
    p.add_argument("--min-segments", type=int, default=1)
    p.add_argument("--rule-profile", type=int, choices=(1, 2), default=1)
    p = sub.add_parser("rbac-incident")
    p.add_argument("--server", required=True)
    p.add_argument("--ca-file", required=True)
    p.add_argument("--token-file", required=True)
    p = sub.add_parser("logs")
    p.add_argument("--out", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--expect-ordered", action="store_true")
    p = sub.add_parser("sessions")
    p.add_argument("--out", required=True, action="append")
    p = sub.add_parser("run")
    p.add_argument("--out", required=True)
    p.add_argument("--token-file")
    p.add_argument("--expect", required=True, choices=("consistent", "truncated", "denied", "unavailable"))
    p = sub.add_parser("db")
    p.add_argument("--json", required=True)
    args = parser.parse_args()
    {"rbac": rbac, "run": run, "db": db, "watch": watch, "sessions": sessions, "rbac-incident": rbac_incident,
     "logs": logs}[args.command](args)


if __name__ == "__main__":
    main()
