"""One command for the CA-P2-005a/006a demonstration: disposable database up, full flow, database down.

  python -I tools/investigation_demo.py [--out out/ca-p2-006a] [--port 0]

Run it with the interpreter that has the hash-locked driver tree (requirements-db.txt), for
example ``.venv-db/bin/python``. It:
  1. creates a private per-session secret directory (mode 0700) and a random bootstrap password;
  2. starts the digest-pinned, loopback-only PostgreSQL from db/test/compose.yaml under a unique
     Compose project name, waiting for its health check. By default (``--port 0``) Docker picks a
     free 127.0.0.1 port, which is then read back: a fixed port inside the kernel's ephemeral range
     (32768-60999 on Linux) can be held by an earlier client connection and fail to bind;
  3. runs cloud_autopsy.app.demo (persist, declare clocks, seal, investigate as ca_engine, store
     once as ca_result_writer, verify on read from a new connection, replay);
  4. always removes the container, its temporary storage and the secret directory.
Synthetic data only. Needs Docker with Compose v2; no other network access after the image pull.
"""

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "db" / "test" / "compose.yaml"
DYNAMIC_ATTEMPTS = 3
_LOOPBACK_PORT = re.compile(r"127\.0\.0\.1:([0-9]{1,5})")


def _published_port(compose, env):
    """The host port Docker chose for the container's 5432, which must be on 127.0.0.1."""
    out = subprocess.run(compose + ["port", "postgres", "5432"], env=env, check=True, capture_output=True, text=True).stdout
    match = _LOOPBACK_PORT.fullmatch(out.strip())
    if not match or not 0 < int(match.group(1)) < 65536:
        raise RuntimeError("the disposable database is not published on a 127.0.0.1 port")
    return match.group(1)


def with_disposable_postgres(port, callback):
    """Start the disposable container, run ``callback()`` with the environment set, always tear down."""
    secret_dir = Path(tempfile.mkdtemp(prefix="ca-demo-"))  # created 0700 by mkdtemp
    project = f"ca-demo-{secrets.token_hex(4)}"
    env = {**os.environ, "CA_PG_SECRET_DIR": str(secret_dir), "CA_PG_PORT": str(port)}
    compose = ["docker", "compose", "-p", project, "-f", str(COMPOSE)]
    try:
        password_file = secret_dir / "bootstrap_password"
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(secrets.token_urlsafe(32))
        os.chmod(password_file, 0o644)  # readable by the container's postgres user; the directory stays 0700
        dynamic = str(port) == "0"
        for attempt in range(DYNAMIC_ATTEMPTS if dynamic else 1):
            try:
                subprocess.run(compose + ["up", "-d", "--wait"], env=env, check=True)
                break
            except subprocess.CalledProcessError:
                # Only a dynamic port is retried (a fresh allocation); a fixed port fails as before.
                if not dynamic or attempt == DYNAMIC_ATTEMPTS - 1:
                    raise
                subprocess.run(compose + ["down", "-v", "--remove-orphans"], env=env, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if dynamic:
            port = _published_port(compose, env)
        os.environ.update({"CA_PG_SECRET_DIR": str(secret_dir), "CA_PG_PORT": str(port)})
        sys.path.insert(0, str(REPO / "src"))
        return callback()
    finally:
        subprocess.run(compose + ["down", "-v", "--remove-orphans"], env=env, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(secret_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="CA-P2-005a/006a one-command synthetic demonstration")
    parser.add_argument("--out", default=str(REPO / "out" / "ca-p2-006a"))
    parser.add_argument("--port", default=os.environ.get("CA_PG_DEMO_PORT", "0"),
                        help="host port on 127.0.0.1; 0 (default) lets Docker choose a free one")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    def run():
        from cloud_autopsy.app import demo
        return demo.main(["--out", args.out] + (["--json"] if args.json else []))

    return with_disposable_postgres(args.port, run)


if __name__ == "__main__":
    sys.exit(main())
