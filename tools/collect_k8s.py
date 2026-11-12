"""Collect sanitized evidence from a disposable local Kubernetes cluster (CA-P2-004e). Synthetic only.

  python -I tools/collect_k8s.py --server https://127.0.0.1:PORT --ca-file CA.crt --token-file TOKEN \
      --namespace ca-demo --cluster-id ca-kind-synthetic --recording-id ID --out NEW_DIR [--json]

The API server must be HTTPS on the loopback interface (a local ``kind`` cluster); anything else is
refused. The collector issues only allowlisted GET list requests for Pods, Deployments, ReplicaSets
and Events in one namespace, projects every object to an allowlist in memory, and writes
``NEW_DIR/recording`` (ca-k8s-recording/0.3-provisional), ``NEW_DIR/bundle`` and
``NEW_DIR/report.json``. Tokens, raw responses and Event messages are never written or printed.

Exit status: 0 when the run completed (collections may still be denied or failed: see the report);
1 when the run was refused; 2 for usage errors.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cloud_autopsy.app import k8s_recording as K  # noqa: E402
from cloud_autopsy.collector import client as cl  # noqa: E402
from cloud_autopsy.collector import collect as co  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only collector for a disposable local cluster (synthetic only)")
    for name in ("server", "namespace", "cluster-id", "recording-id"):
        parser.add_argument(f"--{name}", required=True)
    for name in ("ca-file", "token-file", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--page-limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-restarts", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    config = co.CollectorConfig(server=args.server, ca_file=args.ca_file, token_file=args.token_file,
                                namespace=args.namespace, cluster_id=args.cluster_id, recording_id=args.recording_id,
                                page_limit=args.page_limit, max_pages=args.max_pages, max_restarts=args.max_restarts)
    try:
        collections, conversion, report = co.run(config, args.out)
    except (cl.CollectorError, K.RecordingError) as exc:  # codes only; never a response body
        print(json.dumps({"status": "refused", "code": exc.code}) if args.json else f"REFUSED: {exc.code}")
        return 1
    if args.json:
        print(json.dumps({"status": "collected", "out": str(args.out), "report": report}, indent=2, sort_keys=True))
    else:
        for c in report["collections"]:
            print(f"{c['resource']:12} {c['outcome']:12} items={c['items']:<4} pages={c['pages']} "
                  f"restarts={c['restarts']} rv={c['collection_resource_version']}")
        for a in conversion.report["acquisitions"]:
            print(f"  {a['query_id']:16} {a['outcome']:8} {str(a['reason']):20} coverage "
                  f"{'claimed' if a['coverage_claimed'] else 'not claimed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
