# Database security design (CA-P2-003a, provisional)

Status: design proposal. No role, credential or database exists. Pending security-reviewer approval (CA-DEC-002, CA-DEC-008).

## Roles (least privilege, no runtime superuser)

| Role | Login | Purpose | Privileges |
|---|---|---|---|
| `ca_owner` | No | Owns schema `ca` and every object | All on `ca`; never used by a running service |
| `ca_migrator` | Yes | Applies reviewed migrations | Member of `ca_owner`; `SET ROLE ca_owner` only inside the migration runner; separate credential |
| `ca_ingest` | Yes | Collector and normalizer writes | `INSERT` on `acquisition_batch`, `batch_delivery`, `evidence_identity`, `evidence_version`, `evidence_time`, `run_delivered_evidence`, `batch_evidence`; `SELECT` on `run`, `run_plan`, `plan_acquisition`, `source_binding`, `data_classification`, `contract_pin` and the rows needed for limit checks; `EXECUTE` on `ca.ingest_lock_run` only (row locks need `UPDATE`, which this role does not have, I7); no `UPDATE`, `DELETE` or `TRUNCATE` |
| `ca_sealer` | Yes | Coordinator: seal and run state | `SELECT` on run-scoped and evidence tables; `INSERT` on `frozen_input`, `manifest_page`, `run_evidence`, `run_gap`, `run_coverage`, `run_acquisition`; column-level `UPDATE (state, state_version, lease_owner, lease_expires_at)` on `run` only, constrained by the `run_state_transition` trigger (I8) |
| `ca_planner` | Yes | Registers registries, plans, investigations and runs | `INSERT` on `registry_snapshot`, `source_binding`, `run_plan`, `plan_acquisition`, `investigation`, `run` |
| `ca_reader` | Yes | Local API read path (CA-P2-006) | `SELECT` on curated views only; no base tables, no `record_bytes` columns |
| `ca_evaluator` | Yes | Scorer (CA-P2-007) | `SELECT` on sealed views; `SELECT` on schema `ca_truth`, the only role allowed to read it |
| `ca_lifecycle` | Yes | Expiry and deletion (CA-P2-006) | `EXECUTE` on `SECURITY DEFINER` purge functions that null `record_bytes` and write `lifecycle_event`; no direct table writes |

**Hardening for every role:**
- `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`.
- `REVOKE ALL ON SCHEMA public FROM PUBLIC`, and `REVOKE CREATE ON DATABASE`.
- `ALTER DEFAULT PRIVILEGES` so new objects grant nothing by default. This explicitly includes `REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`, because PostgreSQL otherwise grants `EXECUTE` on every new function to `PUBLIC`.
- `search_path` fixed to `ca, pg_catalog` per runtime role. `SECURITY DEFINER` functions instead use `SET search_path = pg_catalog, pg_temp` with schema-qualified bodies, so neither a writable schema nor temporary objects can capture a name. PostgreSQL's guidance is to list `pg_temp` explicitly and last.
- `SECURITY DEFINER` functions (`ingest_lock_run`, and the purge functions later) set their own `search_path`, are owned by `ca_owner`, revoke `EXECUTE` from `PUBLIC` and grant it to exactly one role.
- Every role may read `data_classification` and `contract_pin`; the adapter refuses to run unless the classification is `synthetic` (I4) and the pins equal `CONTRACT_VERSIONS` (I12).

**Separation:**
- The engine (CA-P2-005) runs as `ca_reader`, or as a dedicated engine role with the same reads, and has no access to `ca_truth`.
- No role combines ingest and seal.
- No runtime role can change approval-like fields, because none exist in the schema (CA-SEC-012).

## Credentials

- **Never in Git.** Generated per environment and per test run outside the repository. The existing supply-chain secret scan and `.gitignore` entries must cover any local credential file pattern chosen in CA-P2-003b.
- **Authentication:** `scram-sha-256` only. The `pg_hba.conf` allows the named roles from loopback (or the container network) only, with no `trust` method.
- **Local delivery:** a passfile with owner-only permissions, or environment variables injected by the test harness. No credential appears in logs, error messages or manifests. The contract layer already never echoes values.
- **Rotation:** the disposable synthetic database is recreated per test session, so credentials don't outlive a session. Rotation for longer-lived environments is a CA-DEC-008 open question.
- **TLS:** not required for a loopback-only disposable database. Any networked deployment needs a new review: TLS, certificate pinning and remote authentication (Phase 1C API boundary).

## Threats addressed and residual risks

| Threat (STRIDE subcase) | Control | Residual risk |
|---|---|---|
| Tampering with sealed evidence by a runtime component (F6, F11) | No `UPDATE`/`DELETE` grants; immutability triggers; digests over stored bytes; `verify_full` on read | Database owner or superuser can rewrite rows and recompute digests; only an external anchor (a published manifest digest) detects that |
| Cross-run citation or membership (F7) | Composite foreign keys `run_evidence` → `run_delivered_evidence` | Application bugs outside the schema (CA-P2-005) still need tests |
| Truth leakage to the engine (F12) | `ca_truth` readable only by `ca_evaluator` | Shared-host administrator access |
| Credential leakage | Credentials outside Git; secret scan; no values in errors | Host compromise |
| Denial of service through oversized input (CA-SEC-009) | Contract limits before writing; column size checks; statement and lock timeouts | Unbenchmarked limits (CA-DEC-007) |
| Payload retained past expiry (CA-SEC-005) | `ca_lifecycle` purge functions; access-time expiry checks (lifecycle contract) | Purge design not specified (CA-P2-006); backups out of scope |
