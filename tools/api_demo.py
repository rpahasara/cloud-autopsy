"""One command for the CA-P2-006b local API demonstration (synthetic data only).

  python -I tools/api_demo.py [--out out/ca-p2-006b] [--port 0]

Run it with the interpreter that has the hash-locked driver tree (requirements-db.txt). Like
tools/investigation_demo.py it creates a private per-session secret directory, starts the
digest-pinned, loopback-only PostgreSQL container under a unique Compose project, runs
cloud_autopsy.app.api_demo (which serves the API on 127.0.0.1 only, with tokens provisioned into
that private directory), and always removes the container and the secrets.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import investigation_demo  # noqa: E402  (same directory)


def main():
    parser = argparse.ArgumentParser(description="CA-P2-006b one-command local API demonstration")
    parser.add_argument("--out", default=str(investigation_demo.REPO / "out" / "ca-p2-006b"))
    parser.add_argument("--port", default=os.environ.get("CA_PG_DEMO_PORT", "0"),
                        help="host port on 127.0.0.1; 0 (default) lets Docker choose a free one")
    args = parser.parse_args()

    def run():
        from cloud_autopsy.app import api_demo
        return api_demo.main(["--out", args.out])

    return investigation_demo.with_disposable_postgres(args.port, run)


if __name__ == "__main__":
    sys.exit(main())
