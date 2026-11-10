"""Synthetic preview of the CA-P2-006c dashboard: no database, results computed in memory and
labelled as not verified. Standard library only.

  python -I tools/dashboard_preview.py [--port 8766]

For verified results, run the API against a disposable database (tools/api_demo.py or
``python -m cloud_autopsy.api.server``); it serves the same dashboard at ``/``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cloud_autopsy.app import preview  # noqa: E402

if __name__ == "__main__":
    sys.exit(preview.main(sys.argv[1:]))
