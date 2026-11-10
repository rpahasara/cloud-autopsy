"""One command for the CA-P2-005a demonstration: disposable database up, full flow, database down.

  python -I tools/investigation_demo.py [--out out/ca-p2-005a] [--port 55442]

Run it with the interpreter that has the hash-locked driver tree (requirements-db.txt), for
example ``.venv-db/bin/python``. It:
  1. creates a private per-session secret directory (mode 0700) and a random bootstrap password;
  2. starts the digest-pinned, loopback-only PostgreSQL from db/test/compose.yaml under a unique
     Compose project name, waiting for its health check;
  3. runs cloud_autopsy.app.demo (persist, seal, read as ca_engine, investigate, verify, replay);
  4. always removes the container, its temporary storage and the secret directory.
Synthetic data only. Needs Docker with Compose v2; no other network access after the image pull.
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "db" / "test" / "compose.yaml"


def main():
    parser = argparse.ArgumentParser(description="CA-P2-005a one-command synthetic demonstration")
    parser.add_argument("--out", default=str(REPO / "out" / "ca-p2-005a"))
    parser.add_argument("--port", default=os.environ.get("CA_PG_DEMO_PORT", "55442"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    secret_dir = Path(tempfile.mkdtemp(prefix="ca-demo-"))  # created 0700 by mkdtemp
    project = f"ca-demo-{secrets.token_hex(4)}"
    env = {**os.environ, "CA_PG_SECRET_DIR": str(secret_dir), "CA_PG_PORT": str(args.port)}
    compose = ["docker", "compose", "-p", project, "-f", str(COMPOSE)]
    try:
        password_file = secret_dir / "bootstrap_password"
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(secrets.token_urlsafe(32))
        os.chmod(password_file, 0o644)  # readable by the container's postgres user; the directory stays 0700
        subprocess.run(compose + ["up", "-d", "--wait"], env=env, check=True)
        os.environ.update({"CA_PG_SECRET_DIR": str(secret_dir), "CA_PG_PORT": str(args.port)})
        sys.path.insert(0, str(REPO / "src"))
        from cloud_autopsy.app import demo
        return demo.main(["--out", args.out] + (["--json"] if args.json else []))
    finally:
        subprocess.run(compose + ["down", "-v", "--remove-orphans"], env=env, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(secret_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
