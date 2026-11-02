# Prototype audit for Phase 2 reuse (Proposed)

Audited commit: `c21b50dc5edd6cd07de55d2f3e0bce6103b4d952` (frozen CA-SPIKE-001 engine). Auditor: engineering author of the prototype; an independent reviewer is still needed. The prototype stays frozen and is not imported by product code. "Reuse" means the module is a reviewed reference to port into a new, separately versioned package, with its own tests and contract versions.

## Classification

| Module | Classification | Reason and conditions for reuse |
|---|---|---|
| `ca_spike/canonical.py` (`ca-canon/0.1-spike`) | Reference for CA-P2-002 | Strict parsing, duplicate-key and float rejection, prefixed digests. Port with the findings below fixed and a new version identifier |
| `ca_spike/timemodel.py` (`ca-time/0.1-spike`) | Reference for CA-P2-002 | Implements the [engine design](../../architecture/phase1c/engine.md) interval rule and unknown-clock behavior. Needs approved precision, leap-second and clock-step decisions |
| `ca_spike/model.py` (`ca-evidence/0.1-spike`, `ca-evid/0.1-spike`) | Reference for CA-P2-002 | Evidence, gap, acquisition-outcome and relation records already mirror the [logical data model](../../architecture/phase1c/data-model.md). The observation-kind table is scenario-specific and must become a versioned registry |
| `ca_spike/fixtures.py` | Partly reusable | Manifest verification and size-bounded strict reads are reusable. The "truth path component" guard is a spike heuristic; product isolation must rely on process and storage identity |
| `ca_spike/store.py` | Interface reference only | The put/get/has boundary is useful; the file store is not the product store (CA-P2-003 is PostgreSQL) |
| `ca_spike/synthesis.py` (validator `0.3-spike`) | Reference for CA-P2-008 | Iterative shape limits and deterministic rejection codes are worth porting. No model client exists or is proposed here |
| `ca_spike/acquire.py` | Experimental only | Fixture-replay connector with random delivery permutation; live acquisition is CA-P2-004 |
| `ca_spike/assemble.py`, `ledger.py`, `pipeline.py` | Experimental only | Scenario-specific mechanism catalog and assembly for CA-SCENARIO-001. CA-P2-005 must be designed from the engine specification, not grown from these rules |
| `ca_spike/baseline.py` | Evaluation only | Naive comparator (CA-BENCH-B0 style); never part of the product |
| `ca_eval/scorer.py`, truth pins, `fixture_tools/` | Evaluation only | Must stay outside product code and engine identity (CA-P2-007 independence) |
| `cli.py` | Experimental only | Demo and fixture-verification entry point |
| `prototype/tests/` | Reference test patterns | Replay, permutation, isolation and hardening patterns inform the CA-P2-002 test strategy |

## Findings that affect CA-P2-002 contracts

These were reproduced against the frozen code on 2026-11-02. The prototype is not changed; each finding becomes a contract requirement and a test vector in the [CA-P2-002 plan](ca-p2-002-plan.md).

| ID | Finding | Effect | Proposed contract handling |
|---|---|---|---|
| CA-P2-001-F1 | `loads_strict` lets `RecursionError` escape for very deeply nested input (100,000 levels); 1,000 levels parse | Untrusted input can raise an untyped exception instead of a typed rejection | Bound depth and node count before or during parsing; typed `CanonicalError` for every malformed input |
| CA-P2-001-F2 | Object keys are sorted by Python code point, not UTF-16 code units, so `ca-canon/0.1-spike` is not RFC 8785 (JCS) compatible for characters outside the Basic Multilingual Plane | Digests may differ from a JCS implementation in another language | Decision D8: adopt RFC 8785 ordering, or specify code-point order explicitly with cross-language vectors |
| CA-P2-001-F3 | Integers are unbounded (2^80 is accepted and encoded) | Values beyond 2^53−1 lose precision in common JSON consumers; PostgreSQL `bigint` is 64-bit | Bound integers to the interoperable range, or carry large values as strings |
| CA-P2-001-F4 | Evidence IDs keep 24 hex characters (96 bits) of SHA-256 | Collision risk is negligible at prototype scale but undocumented as a contract | Record the truncation length and collision handling as part of the identity algorithm |
| CA-P2-001-F5 | Timestamps are floored to milliseconds; leap seconds and clock steps are rejected or assumed absent | Sub-millisecond ordering and stepped clocks are not representable | Decision D8: approve precision and clock-step treatment |

## Not reused

No module is copied into product code by this change. The prototype keeps its own versions and tests, and CI continues to run them unchanged.
