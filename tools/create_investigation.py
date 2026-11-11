"""Create investigations from evidence bundles (CA-P2-004a). Synthetic data only.

  python -I tools/create_investigation.py --offline examples/bundles/config-cause
      engine-checked in memory; no database, no Docker; not database-verified

  python -I tools/create_investigation.py examples/bundles/* --serve
      a disposable loopback-only PostgreSQL (Docker), each run created and verified on read, then
      the dashboard served on 127.0.0.1 with a private token for exactly those runs until Ctrl+C

Database mode needs the interpreter with the hash-locked driver tree (requirements-db.txt).
Usage details: docs/phase2/ca-p2-004/ca-p2-004a.md.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from cloud_autopsy.app import create_cli  # noqa: E402


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--offline" in argv or "-h" in argv or "--help" in argv:
        return create_cli.main(argv)
    import investigation_demo  # noqa: E402  (same directory: disposable database lifecycle)
    port = os.environ.get("CA_PG_DEMO_PORT", "0")
    return investigation_demo.with_disposable_postgres(port, lambda: create_cli.main(argv))


if __name__ == "__main__":
    sys.exit(main())
