"""Convert a recorded Kubernetes response directory into an evidence bundle (CA-P2-004c). Offline only.

  python -I tools/convert_k8s_recording.py examples/k8s-recordings/rollout-complete --out OUT_DIR --report OUT.json

No network, no Kubernetes client, no credentials. Synthetic recordings only.
Details: docs/phase2/ca-p2-004/ca-p2-004c.md.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cloud_autopsy.app import k8s_cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(k8s_cli.main())
