# Local disposable PostgreSQL (CA-P2-003b-1)

**Scope:** synthetic data only, on a local machine or in CI, under the product owner's pre-gate development authorization of 2026-11-09. This is **not** security certification, independent review, production readiness or approval for customer data. Formal Gate D, Gate I and specialist approvals remain open ([authorization record](../docs/phase2/ca-p2-003/ca-p2-003b-1.md)).

## Prerequisites

- Python 3.13 and Docker with Compose v2.
- One-time network access to PyPI (the hash-locked install) and Docker Hub (the digest-pinned image).

## Setup

```bash
python -m venv .venv-db
```

```bash
.venv-db/bin/python -m pip install --require-hashes --no-deps --only-binary=:all: -r requirements-db.txt
```

On Windows use `.venv-db\Scripts\python`. pip refuses any artifact whose SHA-256 differs from `requirements-db.txt`.

## Start a session

Create a private secret directory outside the repository, write a random bootstrap password, and start the container:

```bash
umask 077
export CA_PG_SECRET_DIR="$(mktemp -d)"
python -c "import secrets; print(secrets.token_urlsafe(32), end='')" > "$CA_PG_SECRET_DIR/bootstrap_password"
chmod 0644 "$CA_PG_SECRET_DIR/bootstrap_password"   # readable by the container's postgres user; the directory stays 0700
docker compose -f db/test/compose.yaml up -d --wait
```

The container:
- publishes PostgreSQL on `127.0.0.1:55432` only (override with `CA_PG_PORT`);
- runs as uid 999 with every Linux capability dropped and `no-new-privileges`;
- has a read-only root filesystem with data on in-memory temporary storage;
- is limited to 1 GiB of memory, 2 CPUs and 256 processes;
- authenticates with SCRAM-SHA-256.

## Run the integration tests

```bash
CA_PG_REQUIRE=1 .venv-db/bin/python -I -m unittest discover -s tests/integration -t tests/integration -v
```

**What the tests do:**
- connect as the bootstrap user only to create the ten roles with fresh random passwords (written as `<role>.password` into `CA_PG_SECRET_DIR`);
- send the server only SCRAM verifiers, never plaintext passwords;
- create a fresh database per test class, apply the migrations as `ca_migrator`, and run everything else under the least-privileged runtime roles.

Without `CA_PG_SECRET_DIR` the database tests are reported as **skipped**. With `CA_PG_REQUIRE=1` and no database, the run **fails** rather than reporting skips as a pass.

## Investigation demo (CA-P2-005a, CA-P2-006a)

One command starts its own disposable database, runs the whole synthetic investigation flow and removes the database afterwards. The flow covers persisting, freezing clocks, sealing, investigating, storing the result once and verifying it on read. Records: [CA-P2-005a](../docs/phase2/ca-p2-005/ca-p2-005a.md), [CA-P2-006a](../docs/phase2/ca-p2-006/ca-p2-006a.md).

```bash
.venv-db/bin/python -I tools/investigation_demo.py
```

## Local read-only API demo (CA-P2-006b)

One command serves the stored, verified results on `127.0.0.1` with run-scoped tokens, retrieves all six results and their citations, checks the refusals, and then removes the database ([record](../docs/phase2/ca-p2-006/ca-p2-006b.md)):

```bash
.venv-db/bin/python -I tools/api_demo.py
```

## Read-only dashboard (CA-P2-006c)

The API also serves a read-only dashboard at `/` on the same loopback origin ([record](../docs/phase2/ca-p2-006/ca-p2-006c.md)). Without a database, a clearly labelled synthetic preview serves the same page with results computed in memory and marked as not verified:

```bash
python -I tools/dashboard_preview.py
```

## End the session

```bash
docker compose -f db/test/compose.yaml down -v --remove-orphans
```

```bash
rm -rf "$CA_PG_SECRET_DIR"
```

Nothing persists: the data lives only in the container's temporary storage.

## Before each new use

- **Image version:** before the first use of a new session series, re-check the [D-DB1 pin](../docs/phase2/ca-p2-003/d-db1-postgresql-pin.md#how-to-repeat-this-verification) for a newer 18.x minor or a rebuilt image, and update the digest in `db/test/compose.yaml` and the inventory together. The supply-chain check fails if they differ.
- **Advisories:** re-run the advisory check before regenerating `requirements-db.txt`.
