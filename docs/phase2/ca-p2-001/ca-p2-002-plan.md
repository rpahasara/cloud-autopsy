# CA-P2-002 package layout, test strategy and first slice (Proposed)

Backlog item: [CA-P2-002](../../reviews/phase1d/phase2-backlog.md), versioned evidence/time/manifest, source-plan and integration schemas. Owner role: Architecture lead. Status: plan only. No contract code is added by CA-P2-001. Implementation needs decisions D1, D4 and D8 in [decisions required](decisions-required.md).

## Proposed layout

```text
src/cloud_autopsy/
  __init__.py
  contracts/
    __init__.py        # contract version registry; no I/O
    errors.py          # ContractError with stable reason codes
    versioning.py      # contract identifiers; exact-match compatibility, explicit incompatibility
    canonical.py       # strict bounded parser, canonical bytes, prefixed digest (successor to ca-canon/0.1-spike)
    identity.py        # source-qualified evidence identity and ID format
    timeinterval.py    # timestamp provenance, intervals, ordering (successor to ca-time/0.1-spike)
    evidence.py        # Observation, Evidence, EvidenceTime, Gap records; strict decode/encode
    source_plan.py     # RunPlan (CA-CON-001) and fixed query registry entries
    acquisition.py     # AcquisitionBatch (CA-CON-002)
    manifest.py        # FrozenInput manifest (CA-CON-003); excluded volatile-field list
  vectors/             # language-neutral JSON test vectors, versioned with each contract
tests/
  contracts/           # unittest modules, one per contract module plus cross-cutting suites
```

**Rules:**
- **Standard library only.** The existing import check already covers `src/` and fails on any third-party import.
- **No I/O beyond the input passed in.** Contracts make no network, database, cluster or model calls; callers pass bytes.
- **No prototype imports.** Product code never imports `prototype/`. The only link between them is a read-only differential test.
- **Versioned changes only.** Every encoded record carries `contract_version`. A behavior change creates a new version and new vectors; existing vectors are never edited.
- **Interface coverage:** CA-CON-001, 002 and 003 are in scope. CA-CON-004 through 008 belong to later items and get a placeholder only if an earlier contract has to reference them.

## Test strategy

| Suite | What it proves | Key cases |
|---|---|---|
| Canonical vectors | Stable bytes and digests | Key ordering per D8 (including characters outside the Basic Multilingual Plane), escaping, empty containers, integers at the agreed limits |
| Parse limits | Fail-closed typed rejection | Duplicate keys, floats, NaN/Infinity, BOM, invalid UTF-8, lone surrogates, oversize input, depth and node limits (CA-P2-001-F1), out-of-range integers (F3) |
| Schema decode | Strict records | Missing, unknown and mistyped fields; wrong `contract_version`; unsupported version gives explicit incompatibility, never coercion |
| Identity | Duplicate and conflict semantics | Identical redelivery gives the same ID; same identity with different content is quarantined as a conflict, not last-write-wins; same UID from different sources gives different IDs; truncation length (F4) |
| Time vectors | Interval rules from the engine design | Unknown clocks stay unordered; overlap; declared offset sign; precision widening; unparseable time retained with error; precision and leap-second policy (F5) |
| Manifest | Deterministic freeze | Permutation and retry of the same inputs give the same digest (seeded shuffles); volatile fields excluded and listed; any membership change changes the digest |
| Source plan | No arbitrary queries | Only registered query IDs; hosts, URLs and free-form PromQL/LogQL rejected; finite limits required |
| Differential (read-only) | Continuity with the spike | Decode the three development fixtures with both implementations and report intended differences explicitly; prototype files and pins unchanged |

**How the vectors are kept trustworthy:**
- Vectors are written by hand and reviewed by someone other than the implementer.
- Because they're plain JSON, an independent implementation, such as an RFC 8785 library in another language, can cross-check them during review without becoming a dependency.
- Mutation checks like the ones run for the supply-chain tool are recommended before each contract version is proposed for approval.

**CI:** add one step that runs `python -I -m unittest discover -s tests -t .`. The supply-chain check already enforces the standard-library-only rule for `src/`.

## Proposed next slice: CA-P2-002a — canonical encoding and versioning

The smallest useful slice:
- `errors.py`, `versioning.py` and `canonical.py`;
- their vectors, plus the parse-limit and canonical-vector suites.

It fixes CA-P2-001-F1 to F3 in the new contract while leaving the prototype frozen. It unblocks every later contract, because each one depends on canonical bytes.

**Entry conditions:**
- **D1:** CA-P2-002 authorized, or explicitly allowed as preparatory work.
- **D4:** contracts stay standard-library only.
- **D8:** canonical ordering, integer range, Unicode handling and limit values decided.

If D8 isn't settled, the slice can still start using placeholder limits that fail closed. In that case it has to stay draft, and its contract version is marked `-draft` so no digest is treated as stable.

**Done means:**
- all vectors pass in CI;
- every malformed input produces a typed error;
- the vectors are reviewed by a second person;
- CA-P2-002b (time intervals), 002c (evidence and identity) and 002d (source plan, acquisition batch and manifest) are planned against the reviewed slice.
