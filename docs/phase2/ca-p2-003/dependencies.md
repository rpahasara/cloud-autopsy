# Dependency, image and supply-chain evaluation (CA-P2-003a, provisional)

Status: evaluation only. Nothing was downloaded, installed or pinned. License observations come from upstream project documentation known at the time of writing. They are engineering notes for the licensing reviewer, not clearance, and each must be re-verified against the exact pinned artifact (dependency policy, decision D7).

## PostgreSQL server and image

| Item | Proposal | Notes |
|---|---|---|
| Server line | PostgreSQL 18 (CA-DEC-002 proposal) | PostgreSQL License (permissive). The project supports each major for five years. Confirm the exact end-of-life date and the latest minor at pin time |
| Exact version | The newest 18.x minor available when CA-P2-003b starts | Record it in the inventory with its release-notes reference |
| Test image | Docker official image `postgres:18.<minor>-<debian codename>`, pinned by **digest** (`postgres@sha256:...`) | The image packaging repository is MIT; the image contains many Debian packages under their own licenses. Test-only and never redistributed. Inventory scope `ci-only`/test |
| Image verification | Record the digest, the build source and the image SBOM before first use | Generating an image SBOM or vulnerability report (for example Syft or Grype) needs tool and network approval (D6) |

## Python driver options

| Driver | Observed license | Shape | Assessment |
|---|---|---|---|
| psycopg 3 (`psycopg`, optional `psycopg-binary`) | LGPL-3.0-only (pure package); binary wheels also bundle libpq (PostgreSQL License), OpenSSL and other native libraries | Mature; COPY support; sync and async | Under our [dependency policy](../ca-p2-001/dependency-policy.md), LGPL needs an **approved specialist review before it can be inventoried**. Binary wheels add bundled native components to the SBOM. It was the Phase 1D candidate |
| pg8000 | BSD-3-Clause (verify); depends on `scramp` and `python-dateutil` (licenses to verify) | Pure Python, DB-API 2.0 | Permissive and has no native code, so the SBOM is smaller. Slower, with fewer bulk-load features. Adequate for bounded synthetic runs |
| asyncpg | Apache-2.0 (verify) | C extension, asyncio only | Fast, but forces an async architecture and native wheels; not needed for this scope |

**Update 2026-11-03:** D-DB2 now has a detailed, proposed disposition with exact versions, hashes, license files, advisories and Python 3.13 evidence. See the [D-DB2 driver decision](d-db2-driver-decision.md). It confirms pg8000 1.31.6 with scramp 1.5.0, asn1crypto 1.5.1, python-dateutil 2.9.0.post0 and six 1.17.0. It corrects the table above in three places:
- psycopg 3.3.7 metadata is `LGPL-3.0-only`;
- scramp is `MIT-0`;
- pg8000's tree also includes asn1crypto, and six through python-dateutil 2.x.

**Recommendation (provisional, decision D-DB2 in [inconsistencies](inconsistencies.md#decisions)):**
- **Start CA-P2-003b with pg8000** behind a narrow internal database-adapter interface. Its license class passes the current policy without a copyleft review, and it adds no native binaries.
- **Revisit psycopg 3** if bulk-load performance (COPY) or an approved LGPL review justifies it. Because the adapter keeps SQL in the repository rather than in a driver abstraction layer, switching drivers doesn't change the schema or migrations.
- **No ORM and no third-party migration framework.** Both would add dependencies without a need.

## Lock files, inventory, SBOM and vulnerability checks

1. **Manifest and lock:**
   - Add `pyproject.toml` (build backend: decision D5) and a hash-locked `requirements-db.txt` with `name==version --hash=sha256:...` for the driver and every transitive dependency.
   - Declare both in `supply-chain/dependency-inventory.json` under `dependency_manifests`. The existing check already enforces exact pins with hashes for declared requirement files.
2. **Lock generation:** pip-tools (`pip-compile --generate-hashes`) or uv. Either is a development tool needing its own inventory entry, and hashing requires network access to the package index, which needs approval for CA-P2-003b.
3. **Inventory entries:** one `python-package` component per package (driver plus transitive dependencies) with an exact pin, an SPDX license, a source URL and an upgrade owner. Scope:
   - `build-and-test` while only local tests use it;
   - `runtime-shipped` once a deliverable includes it, which then requires an approved license review.

   The PostgreSQL image is a new component type, `container-image`, with a digest pin.
4. **Required supply-chain tool changes** (`ca-supply-chain/0.1` → 0.2):
   - allow third-party imports in `src/` only for packages in the inventory (an `import_names` field per package);
   - add a `container-image` type that requires digest pins;
   - check workflow `services:` and `image:` lines for digest pins, not only `uses:`;
   - regenerate the SBOM, so CycloneDX gains the driver components with `pkg:pypi` purls.
5. **Vulnerability checks:**
   - Run `pip-audit` (OSV) before adding or upgrading a package, then weekly. It contacts external services, so it needs approval D6.
   - Until approved, record a manual advisory review (PyPI, GitHub Security Advisories, PostgreSQL security page) with its date in the inventory notes. This is weaker evidence and is labelled as such.
6. **Licensing outcome needed** (D7 reviewer): pg8000 and its dependencies, and, if chosen, psycopg 3 LGPL obligations for the intended distribution model (D2).
