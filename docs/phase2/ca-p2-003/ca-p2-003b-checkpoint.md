# CA-P2-003b readiness checkpoint (go/no-go)

Date: 2026-11-03. Baseline: PR #20 at `0176abb`. This is the single checkpoint that gates CA-P2-003b. It consolidates the blockers from the [design package](README.md); it doesn't add architecture.

**Current verdict: NO-GO.** Every engineering preparation item is done. Every remaining item is a **human decision or approval** that can't be satisfied by automated checks or AI review. No dependency has been installed, no container started, no credential created and no migration written.

## Product-owner decisions recorded (provisional, not specialist approvals)

| Date | Decision | What it does not cover |
|---|---|---|
| 2026-11-03 | PostgreSQL 18.6 with digest `sha256:3a4264520e121176619f54ff867d12774bc81e95e7b84db58d63bccdb6144b81`, for a disposable synthetic test environment ([D-DB1](d-db1-postgresql-pin.md)) | DB and security reviewer approval, and a fresh version check at first use |
| 2026-11-03 | The pg8000 1.31.6 tree, with python-dateutil 2.9.0.post0 ([D-DB2](d-db2-driver-decision.md)) | Licensing clearance |
| 2026-11-03 | I1, I3, I4, I5, I7 and I12 preferences ([inconsistencies](inconsistencies.md)) | DB, security and privacy reviewer approval |

## 1. Disposable PostgreSQL container (prepared, not launched)

This file is created in CA-P2-003b as `db/test/compose.yaml`, only after D-DB1 and D-DB7 approval. Once it exists, supply-chain check 0.2 requires its image to be digest-pinned and inventoried, with an approved license review.

```yaml
# Disposable synthetic-only PostgreSQL for CA-P2-003b integration tests.
services:
  postgres:
    image: postgres:18.6-trixie@sha256:3a4264520e121176619f54ff867d12774bc81e95e7b84db58d63bccdb6144b81
    user: "999:999"                       # image's postgres uid/gid; no root, no gosu step
    read_only: true
    tmpfs:                                # nothing persists; deleted with the container
      - /var/lib/postgresql:uid=999,gid=999,mode=0700,size=1g
      - /var/run/postgresql:uid=999,gid=999,mode=0775,size=16m
      - /tmp:uid=999,gid=999,mode=1777,size=64m
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    privileged: false
    pids_limit: 256
    mem_limit: 1g
    cpus: 2
    shm_size: 128m
    ports:
      - "127.0.0.1:55432:5432"            # loopback only; never 0.0.0.0
    environment:
      POSTGRES_USER: ca_bootstrap         # bootstrap superuser: used only by the harness to create roles
      POSTGRES_PASSWORD_FILE: /run/secrets/ca_bootstrap_password
      POSTGRES_DB: cloud_autopsy_synthetic
      POSTGRES_HOST_AUTH_METHOD: scram-sha-256
      POSTGRES_INITDB_ARGS: "--auth-local=scram-sha-256 --auth-host=scram-sha-256 --data-checksums --encoding=UTF8 --locale=C.UTF-8"
    command: ["postgres", "-c", "max_connections=20", "-c", "shared_buffers=128MB",
              "-c", "ssl=off", "-c", "log_statement=none", "-c", "log_min_error_statement=error"]
    secrets: [ca_bootstrap_password]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "ca_bootstrap", "-d", "cloud_autopsy_synthetic"]
      interval: 2s
      timeout: 2s
      retries: 30
secrets:
  ca_bootstrap_password:
    file: ${CA_PG_SECRET_DIR:?set by the test harness}/bootstrap_password   # generated per session, outside Git
```

**Rules:**
- **Loopback only.** In CI the same image runs as a `services:` container on the hosted runner, published only to `127.0.0.1`.
- **Synthetic data only, enforced:** `ca.data_classification = 'synthetic'` (I4).
- **Finite resources:** 1 GiB memory and 2 CPUs; 1 GiB of temporary storage for data; 256 processes; 20 connections.
- **No volumes, no host mounts except the secret file, no host network and no extra capabilities.**
- **Per-session credentials:** the harness generates random passwords for the bootstrap user and the eight roles in a private temporary directory with permissions `0700`, and deletes them at teardown.
- **The bootstrap superuser is never used by runtime code.** It only runs the role and bootstrap script and then disconnects.
- **TLS is off**, because traffic never leaves loopback; this is recorded as an accepted limitation for synthetic data. Any networked use needs a new review.
- **Fresh version check at first use.** If 18.7 or later is out (expected 2026-11-12), re-run the [D-DB1 procedure](d-db1-postgresql-pin.md#how-to-repeat-this-verification), re-pin by digest and get the new digest approved before use.

## 2. Role, privilege and `SECURITY DEFINER` review (engineering self-review)

This review checks the [security design](security.md) against the [schema](schema.md). It is **not** the security reviewer's approval.

| ID | Finding | Status |
|---|---|---|
| R1 | No role combines ingest and seal; no runtime role has `UPDATE`/`DELETE` on append-only tables; `ca_ingest` row-locks only through `ca.ingest_lock_run` | Consistent |
| R2 | PostgreSQL grants `EXECUTE` on new functions to `PUBLIC` by default. The design revoked it only for `ingest_lock_run` | **Fixed:** `ALTER DEFAULT PRIVILEGES FOR ROLE ca_owner IN SCHEMA ca REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`, plus a per-function `REVOKE`, and a grant to exactly one role |
| R3 | The `SECURITY DEFINER` function used `search_path = ca, pg_catalog` | **Fixed:** `SET search_path = pg_catalog, pg_temp` with a schema-qualified body. `pg_temp` is listed explicitly and last, per PostgreSQL guidance |
| R4 | Trigger functions (`check_run_transition`, `check_run_is_sealing`, `check_sealed_has_manifest`, `check_run_created_collecting`) run as the invoking role | They need only `SELECT` on `ca.run` and `ca.frozen_input`, which the invoking roles already have. They must **not** be `SECURITY DEFINER`. CA-IT-003 verifies this |
| R5 | Roles are cluster-level objects, so migrations can't create them portably | The bootstrap script `db/bootstrap/roles.sql`, run once by the bootstrap superuser in the disposable container, creates the eight roles with `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, `LOGIN` where required and passwords from the session's secret files, and sets `search_path`, `statement_timeout` and `lock_timeout` per role. Migrations then grant privileges |
| R6 | `ca_lifecycle` purge functions and the `ca_truth` schema | Out of scope for the first slice: not created, and their roles hold no grants |
| R7 | The `public` schema | `REVOKE ALL ON SCHEMA public FROM PUBLIC` and `REVOKE CREATE ON DATABASE ... FROM PUBLIC` in the bootstrap script |

**Role matrix for the first slice:**

| Role | Login | First-slice privileges |
|---|---|---|
| `ca_owner` | No | Owns everything |
| `ca_migrator` | Yes | Member of `ca_owner`; used by the migration runner |
| `ca_planner` | Yes | `INSERT` on configuration, plan, investigation and run tables |
| `ca_ingest` | Yes | Append-only inserts on batch and evidence tables, plus `EXECUTE ca.ingest_lock_run` |
| `ca_sealer` | Yes | `SELECT` on run-scoped tables; `INSERT` on sealed tables; column-level `UPDATE` on run state |
| `ca_reader` | Yes | `SELECT` on views only |
| `ca_evaluator` | Yes | No grants yet (CA-P2-007) |
| `ca_lifecycle` | Yes | No grants yet (CA-P2-006) |

## 3. Supply-chain checker 0.2 (implemented in this PR)

`tools/supply_chain/supply_chain.py` is now `ca-supply-chain/0.2`, with inventory schema `ca-dep-inventory/0.2`. It uses only the standard library, works offline, and is tested by 31 unit tests plus 8 mutants, all caught.

| Capability | Rule |
|---|---|
| `container-image` components | Pin kind `image-digest`, `name[:tag]@sha256:<64 hex>`; no other pin kind |
| Image references | Every YAML `image:`, Dockerfile `FROM` and workflow `uses: docker://` must be digest-pinned and match an inventoried image; an inventoried image that nothing references is flagged |
| `python-package` components | `exact-version` pin equal to `version`; a non-empty list of distinct SHA-256 artifact hashes; `import_names` (empty for indirect dependencies); repository-relative `allowed_paths` |
| Requirements files | Every `name==version --hash=...` line, including `\` continuations, must match an inventoried package's version and **exactly** its hash set; every inventoried package must appear in some declared requirements file |
| Imports | A third-party import is allowed only if its top-level name is in some package's `import_names` **and** the importing file is under that package's `allowed_paths`. Indirect dependencies can't be imported |
| SBOM | Python packages carry `pkg:pypi` purls and SHA-256 hashes; images carry the `container` type and `pkg:docker/library/<name>@sha256%3A<digest>` |
| License gate | Unchanged: any license outside the permissive set (including `MIT-0`, `PostgreSQL` and compound expressions) needs an approved review record before the check passes |

**Ready-to-apply inventory additions** (applied in CA-P2-003b; versions and hashes from [D-DB2](d-db2-driver-decision.md) and [D-DB1](d-db1-postgresql-pin.md)):

| Component | Type | Pin | `import_names` / `allowed_paths` | License as it stands today |
|---|---|---|---|---|
| pg8000 | python-package | `1.31.6` + 2 hashes | `pg8000` / `src/cloud_autopsy/db/` | `BSD-3-Clause`; passes the gate while scope is `build-and-test` |
| scramp | python-package | `1.5.0` + 2 hashes | none | `MIT-0`: **blocked until approved** |
| asn1crypto | python-package | `1.5.1` + 2 hashes | none | `MIT`; passes |
| python-dateutil | python-package | `2.9.0.post0` + 2 hashes | none | **Reviewer to decide**. Passes only if recorded as plain `BSD-3-Clause` |
| six | python-package | `1.17.0` + 2 hashes | none | `MIT`; passes |
| postgres | container-image | `postgres:18.6-trixie@sha256:3a42…4b81` | not applicable | `PostgreSQL`: **blocked until approved** |

## 4. Dependency tree versus licensing approvals (kept separate)

| Package | Product-owner preference | Engineering evidence | Licensing approval |
|---|---|---|---|
| pg8000 1.31.6 | Selected | License file and hashes verified; no advisories; CVE-2025-61385 fixed in 1.31.5 | **Pending** |
| scramp 1.5.0 | Selected (pinned by pg8000) | `MIT-0` license file verified; no advisories | **Pending** (MIT-0 policy decision) |
| asn1crypto 1.5.1 | Selected | `MIT` verified; parses on 3.13 (static) | **Pending** |
| python-dateutil 2.9.0.post0 | Selected over 4.0.0 | Dual-license wording quoted; three candidate readings | **Pending** (reading and SPDX expression) |
| six 1.17.0 | Selected | `MIT` verified | **Pending** |
| postgres 18.6 image | Accepted for disposable synthetic testing | Digest, provenance and SLSA attestation verified | **Pending** (PostgreSQL License, and image content not redistributed) |

## 5. External access required for reproducible testing (to be approved)

| Access | Purpose | When | Constraint |
|---|---|---|---|
| `pypi.org` and `files.pythonhosted.org`, read-only | Generate the hash-locked `requirements-db.txt` once, then install with `pip install --require-hashes --no-deps --only-binary=:all:` in CI and locally | Lock generation and each CI run | Hashes must equal the D-DB2 record; any difference fails |
| `registry-1.docker.io` and `auth.docker.io`, anonymous pull | Pull `postgres@sha256:3a42…4b81` | Each local session and CI run | Digest reference only; anonymous rate limits apply |
| `api.osv.dev` (and PyPI JSON), read-only | Dated advisory check before lock generation, and on the D6/D-DB8 cadence | Before the lock, then periodically | Results recorded in the inventory notes; not a gating CI dependency until D6 is approved |
| No other egress | | | The database container has no outbound needs; tests use loopback only |

## 6. Human decisions still outstanding (no names recorded)

No person has been appointed to any of these roles (CA-DEC-008). Automated checks and AI review are evidence for them, not substitutes.

| Reviewer role | Decisions needed for CA-P2-003b |
|---|---|
| **Product / requirements authority** | Authorize CA-P2-003b, or Gate I for CA-P2-003; appoint the reviewers below; approve the external access in section 5 |
| **DB reviewer** | D-DB1 digest; I1–I3 and I5–I11 dispositions; schema; transaction model; first-slice migration review |
| **Security reviewer** | D-DB1 digest; D-DB7 container configuration (section 1); role matrix and `SECURITY DEFINER` review (section 2); credential handling; I2 and I7; image-scanning decision (D6, D-DB8) |
| **Licensing reviewer** | pg8000, scramp (`MIT-0`), asn1crypto, python-dateutil (reading and SPDX) and six; PostgreSQL License for the test image; record approvals in the inventory |
| **Privacy/lifecycle reviewer** | Not needed for synthetic-only CA-P2-003b; needed before any real data (I4) |
| **Independent architecture and security review** | The pinned provisional CA-P2-002a–d contracts (I12): either a review, or an explicit acceptance that the work proceeds on provisional versions |
| **Repository maintainer** | Lock-file tool (D5, D-DB3); upgrade owner (D7) |

## Go/no-go checklist

| # | Condition | State |
|---|---|---|
| 1 | Design contradictions resolved (I1–I12, C1–C8, R2–R3) | Done (proposed) |
| 2 | Supply-chain checker 0.2 implemented and tested | Done |
| 3 | Container configuration prepared (section 1) | Done (not launched) |
| 4 | Exact dependency tree, hashes and image digest recorded | Done |
| 5 | Product authorization of CA-P2-003b | **Open** |
| 6 | DB reviewer and security reviewer approval of D-DB1 and D-DB7 | **Open** |
| 7 | Security reviewer approval of the role matrix and credentials | **Open** |
| 8 | Licensing approvals for all five packages and the image | **Open** |
| 9 | Approval of external access (section 5) and the lock-file tool | **Open** |
| 10 | Contracts reviewed, or provisional use accepted (I12) | **Open** |
| 11 | Fresh PostgreSQL version check on the day of first use | **Open** (at first use) |

**GO** requires rows 5–10 to be recorded as dated approvals by named people, with row 11 done on the day of first use.

## First implementation slice (starts only at GO)

**CA-P2-003b-1: migrations, idempotent ingest, conflict retention, atomic sealing and rollback.**

| Deliverable | Content |
|---|---|
| `requirements-db.txt` and inventory entries | The five packages, with D-DB2 hashes; the inventory and SBOM updated; supply-chain check green |
| `db/test/compose.yaml`, `db/bootstrap/roles.sql` | Section 1 and the R5/R7 bootstrap |
| `db/migrations/0001_core.sql` | Classification and contract pins; configuration and plan tables; investigation and run; batches and deliveries; evidence identity, version and time; delivered evidence and provenance; frozen input, pages and decoded tables; views; triggers; `ingest_lock_run`; grants |
| `src/cloud_autopsy/db/` | `adapter.py` (the only pg8000 importer: connect, transaction, typed error mapping), `migrate.py` (checksummed forward-only runner), `ingest.py` (T1), `seal.py` (T3 two-phase, reusing `frozen_input.seal`) |
| `tests/integration/` | Run only when `CA_PG_TEST_DSN` and the approved container are present; otherwise reported as skipped, never as passed |
| CI | A new job with a digest-pinned `services:` container; the existing offline job unchanged |

**Integration tests in the first slice:**

| Test | Proves |
|---|---|
| CA-IT-001, CA-IT-002 | Migrations apply; checksums refuse edits |
| CA-IT-003 (first-slice roles) | Privilege matrix |
| CA-IT-004 | Idempotent duplicate delivery |
| CA-IT-005, CA-IT-006 | Batch and identity conflicts retained, never overwritten |
| CA-IT-008, CA-IT-009 | Concurrent sealers; late ingest rejected |
| CA-IT-011 | Rollback inside phase B publishes nothing |
| CA-IT-014 | Immutability |
| CA-IT-015 | Exact limits under per-run serialization |
| CA-IT-016 | Replay from stored batches is byte-identical |
| CA-IT-023, CA-IT-029 | Manifest and run-state triggers |
| CA-IT-025, CA-IT-031 | Synthetic classification and contract pins |

**Exit criteria:**
- every listed test passes in CI against the approved digest;
- the offline suite and supply-chain check stay green;
- the PR stays a draft, with reviewers assigned.
