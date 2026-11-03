# Transaction model (CA-P2-003a, provisional)

Status: design proposal, revised for the proposed [I1–I12 dispositions](inconsistencies.md) (notably I3, I7 and I8). No transaction has been executed. Tables are in the [proposed schema](schema.md), and roles in the [security design](security.md).

## Rules for every transaction

1. **Bounded and short.** No transaction spans a source query, a model call or unbounded computation (Phase 1C data model).
2. **Default isolation is `READ COMMITTED`**, with explicit row locks and unique constraints carrying correctness. `REPEATABLE READ` is used where a stable snapshot matters (sealing reads). `SERIALIZABLE` is not required by this design; a later review may adopt it where an invariant cannot be expressed as a constraint.
3. **Retry only these:** serialization failures (`40001`), deadlocks (`40P01`) and lock timeouts (`55P03`). At most 5 attempts, with exponential backoff and jitter; the numbers are provisional. Integrity violations (`23xxx`), contract errors and authorization errors are never retried. They are reported with a typed reason.
4. **Same order for locks.** Locks are always taken run row first, then batches, then evidence identities in ascending ID order. Consistent ordering prevents deadlocks between ingest workers.
5. **Bounded waits.** `lock_timeout` and `statement_timeout` are set for every runtime session. A timeout fails the transaction cleanly instead of waiting without limit.

## T1 — Idempotent batch ingestion (role `ca_ingest`)

The contract's per-batch validation (`decode_batch`, `observe`) runs **before** the transaction, in application memory. Invalid input never opens a write transaction.

```text
BEGIN;  -- READ COMMITTED
  SELECT ca.ingest_lock_run($run);   -- SECURITY DEFINER: row lock FOR UPDATE, serializes ingestion per run (I7)
  -- state must be 'collecting'; otherwise ROLLBACK with run_not_collecting
  INSERT INTO ca.acquisition_batch ... ON CONFLICT DO NOTHING;  -- identical redelivery is a no-op
  INSERT INTO ca.batch_delivery (..., attempt) ON CONFLICT DO NOTHING;
  -- for each observation, in ascending evidence_id order:
  INSERT INTO ca.evidence_identity ... ON CONFLICT (evidence_id) DO NOTHING;
  -- verify the existing identity row has identical identity columns, else ROLLBACK (identity_collision)
  INSERT INTO ca.evidence_version ... ON CONFLICT (evidence_id, content_digest) DO NOTHING;
  INSERT INTO ca.run_delivered_evidence ... ON CONFLICT DO NOTHING;
  INSERT INTO ca.batch_evidence ... ON CONFLICT DO NOTHING;
  -- plan limits checked with exact counts under the run lock (see "Limits")
COMMIT;
```

- **Identical redelivery** of the same batch (same key and digest) inserts nothing new except a delivery receipt. It is idempotent.
- **Same key, different digest:** this is a **batch conflict**. Both rows exist, because `batch_digest` is part of the key, and the `run_batch_conflict` view reports it. Nothing is overwritten.
- **Same evidence identity, different content:** both versions exist, and `run_identity_conflict` reports it. This is the contract's quarantine. No row changes and no last-write-wins.
- **Partial failure:** any error rolls back the whole batch, so a batch is either fully recorded or not at all. The collector retries it with the same batch key, and the retry is idempotent.

## T2 — Conflicting digest quarantine

There is no separate transaction. Quarantine is derived from the append-only rows, so it can't be lost or raced. Two concurrent ingests of different versions of one identity both succeed, and both versions are visible to the seal. That reproduces the contract's order-independent outcome. A uniqueness constraint that rejected the second version would lose data and make the result depend on order, so it is deliberately absent.

## T3 — Atomic manifest sealing (role `ca_sealer`), two-phase

Sealing computes the manifest with the pure contract function `frozen_input.seal`, which can take seconds for large runs. Holding a write lock for that whole time is avoided:

```text
-- Phase A: freeze intake
BEGIN;
  SELECT state, state_version FROM ca.run WHERE run_id = $run FOR UPDATE;   -- waits for in-flight ingests
  UPDATE ca.run SET state = 'sealing', state_version = state_version + 1,
         lease_owner = $worker, lease_expires_at = now() + $lease
   WHERE run_id = $run AND state = 'collecting' AND state_version = $expected;  -- 0 rows: lost race
COMMIT;

-- Outside any transaction: read the run's batches (REPEATABLE READ, read-only)
-- and compute FrozenInput = seal(plan, registry, batches)

-- Phase B: publish
BEGIN;
  SELECT state, state_version, lease_owner FROM ca.run WHERE run_id = $run FOR UPDATE;
  -- require state = 'sealing', our lease and the state_version from phase A
  INSERT INTO ca.frozen_input ...; INSERT INTO ca.manifest_page ...;
  INSERT INTO ca.run_evidence ...; INSERT INTO ca.run_gap ...; INSERT INTO ca.run_coverage ...;
  INSERT INTO ca.run_acquisition ...;   -- all decoded from the same FrozenInput object (I5, I10)
  -- verification query: decoded rows must equal the page items, otherwise ROLLBACK (I10)
  UPDATE ca.run SET state = 'sealed', state_version = state_version + 1, lease_owner = NULL,
         lease_expires_at = NULL WHERE run_id = $run AND state_version = $expected + 1;
COMMIT;
```

- **Atomicity:** phase B publishes the root, every page and the decoded membership in one transaction. Readers see either nothing or the complete sealed set.
- **One manifest per run:** `frozen_input.run_id` is the primary key, so a second seal can never publish a second authoritative manifest.
- **Concurrent sealers:** the compare-and-swap on `state_version` in phase A lets exactly one sealer move the run to `sealing`. The others see 0 rows and stop.
- **Late ingestion:** `T1` and phase A take the same run-row lock, so they never interleave. After phase A, `T1` sees `state = 'sealing'` and rolls back. Late evidence goes into a new run (an attempt with `parent_run_id`), never into a sealed run.
- **Determinism makes recovery safe:** recomputing the seal from the same stored batches gives byte-identical output.

## T4 — Crash recovery and leases

- **Crash during phase A:** the transaction rolls back, and the run stays `collecting`.
- **Crash between phases:** the run is `sealing` with a lease. When the lease expires, a recovery worker takes it over with a compare-and-swap on `state_version` and repeats the computation. The bytes are identical, so the result is the same.
- **Crash during phase B:** the transaction rolls back and nothing is published. Recovery repeats phase B.
- **Delayed duplicate publication:** if a delayed worker tries to publish after recovery succeeded, its phase B fails the lease and state-version check, and the primary key prevents a second manifest.
- **Repeated sealing failures** (for example a contract error in stored batches) move the run to `failed` with a typed reason. Its batches are retained for inspection. Nothing is deleted.

## Limits inside the database

Plan limits are enforced in two places:
- **In application memory before writing:** the batch size and per-batch observation count, by the contract decoder.
- **Inside `T1`, under the per-run `FOR UPDATE` lock:** counts of batch deliveries, distinct batch variants per acquisition, distinct delivered evidence and stored batch bytes for the run. Because ingestion for a run is serialized (I7), the counts are exact and no limit can be overshot. If a limit would be exceeded, the transaction rolls back with `limit_exceeded`.

The seal re-checks every limit from stored rows with the same contract code, as defense in depth. Batches for one run are written one at a time; throughput per run is unmeasured (CA-DEC-007).

## Rollback after partial failure

| Failure | Result |
|---|---|
| Error during `T1` | Whole batch rolled back; collector retries with the same key (idempotent) |
| Error during phase A | Run stays `collecting` |
| Error while computing the seal | No writes; run stays `sealing` until the lease expires or the run is marked `failed` |
| Error during phase B | Nothing published; recovery retries phase B |
| Disk full or connection loss | Ordinary transaction rollback; the same handling applies |

There is no partial manifest state anywhere: the only published state is a complete `frozen_input` with every page.
