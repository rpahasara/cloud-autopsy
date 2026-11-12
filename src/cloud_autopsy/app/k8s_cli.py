"""Convert a recorded Kubernetes response directory into an evidence bundle (CA-P2-004c). Offline only.

  python -I tools/convert_k8s_recording.py RECORDING --out BUNDLE_DIR [--report REPORT.json] [--json]

``BUNDLE_DIR`` and ``REPORT.json`` must not exist. The bundle is then used like any other, for
example ``tools/create_investigation.py --offline BUNDLE_DIR``. The report lists every converted
acquisition with its outcome and every ``unsupported_conversion`` resource with its counts.

Exit status: 0 converted; 1 refused (nothing written); 2 usage error.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import k8s_recording as K


def summary(conversion):
    rows = []
    for a in conversion.report["acquisitions"]:
        rows.append(f"{a['query_id']:18} {a['outcome']:8} {str(a['reason'] or ''):20} {a['observations']:3} observations"
                    f"  coverage {'claimed' if a['coverage_claimed'] else 'not claimed'}")
    for u in conversion.report["unsupported"]:
        rows.append(f"{u['resource']:18} {u['classification']} ({u['response']}; {u.get('items', 0)} items; "
                    "no coverage, not evidence)")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert a recorded Kubernetes directory (synthetic only) to a bundle")
    parser.add_argument("recording", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="new bundle directory")
    parser.add_argument("--report", type=Path, help="new conversion report file (canonical JSON)")
    parser.add_argument("--kinds", choices=("0.1", "0.2"), default="0.1",
                        help="observation kinds the plan pins (0.2 converts Events and ConfigMap metadata; "
                             "needs a snapshot recording)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.report and args.report.exists():
        parser.error("--report must name a new file")
    kinds = K.ev.KIND_REGISTRY_VERSION_V2 if args.kinds == "0.2" else K.ev.KIND_REGISTRY_VERSION
    try:
        conversion = K.convert(args.recording, kinds)
    except K.RecordingError as exc:
        print(json.dumps({"status": "refused", "code": exc.code}) if args.json else f"REFUSED: {exc.code}")
        return 1
    conversion.write_bundle(args.out)
    if args.report:
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(conversion.report_bytes())
    if args.json:
        print(json.dumps({"status": "converted", "bundle": str(args.out), "report": conversion.report}, indent=2))
    else:
        print(f"bundle {conversion.bundle_id} written to {args.out}")
        for row in summary(conversion):
            print("  " + row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
