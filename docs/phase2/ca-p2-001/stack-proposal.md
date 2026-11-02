# Minimum Python application stack (Proposed)

Status: proposal for decisions D3, D4 and D5 in [decisions required](decisions-required.md). Nothing here is an accepted technology choice. The [technology evaluation](../../reviews/phase1d/technology-evaluation.md) and CA-DEC-001/002 remain the governing proposals. Python/FastAPI is still only a candidate.

## Principle

Add a third-party dependency only when the backlog item that needs it is authorized, and only after its inventory entry, pin, license review and advisory check exist. Contracts (CA-P2-002) do not need any third-party package. The prototype already shows that strict JSON parsing, canonical encoding, hashing and interval time logic fit in the standard library.

## Layers and proposed choices

| Layer | Needed by | Proposed choice | Status |
|---|---|---|---|
| Interpreter | All | CPython 3.13 line, exact patch pinned in CI (D3) | Provisional; the line is in use today, the patch pin is not |
| Contracts: schemas, canonical bytes, identity, time | CA-P2-002 | Standard library only: `json`, `hashlib`, `dataclasses`, `decimal`, `unicodedata`. Hand-written strict validators rather than a schema library | Proposed (D4) |
| Test runner | All | Standard library `unittest`, matching the prototype and kit; no pytest until a need is shown | Proposed |
| Packaging | First third-party dependency | `pyproject.toml` with a build backend and a hash-locked requirements file | Deferred (D5); not introduced here |
| Database driver | CA-P2-003 | Candidate: psycopg 3 for PostgreSQL 18 (CA-DEC-002) | Candidate only; needs license, pin and advisory review |
| Local API | CA-P2-006 | Candidate: FastAPI or a smaller standard-library HTTP layer on loopback (CA-DEC-001/008) | Candidate only; choose when CA-P2-006 is authorized |
| Kubernetes, Prometheus and Loki clients | CA-P2-004 | Decide between official client libraries and a minimal fixed-query HTTP client | Open; needs security review of the dependency surface |
| Synthesis runtime | CA-P2-008 | Local model runtime and weights | Unselected (CA-DEC-004); no provider access |

## Why the contracts layer stays dependency-free

- **Smaller attack surface.** The contract layer parses untrusted input, so a parser outside our control would sit on the trust boundary.
- **Exact canonical bytes.** Our identity and digest rules must be pinned by our own vectors, and no schema library defines them.
- **Reproducibility.** The same interpreter version reproduces every digest without a lock file.
- **No dependency approval needed.** This slice can proceed while D5 and D6 are still open.

The trade-off is that we write more validation code ourselves. If the architecture lead prefers a schema library such as `jsonschema` or pydantic, that is decision D4. It would bring a lock file, license review and advisory scanning (D5 and D6) forward into CA-P2-002.
