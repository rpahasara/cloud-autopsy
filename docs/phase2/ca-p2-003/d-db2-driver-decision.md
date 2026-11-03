# D-DB2 — PostgreSQL driver selection and licensing evidence (proposed)

Date: 2026-11-03. Status: **proposed disposition, not approved**. It is engineering evidence for the licensing reviewer, not legal advice or license clearance. Nothing was installed, no package archive was downloaded, and no lock file or inventory entry was created.

**Sources:**
- PyPI JSON API metadata for each exact version (`https://pypi.org/pypi/<name>/<version>/json`);
- upstream `LICENSE` files read at the matching release tags (Codeberg and GitHub);
- the OSV advisory database (`api.osv.dev`), queried by exact version;
- upstream changelogs (README and GitHub releases).

All of this was read on 2026-11-03.

## Proposed disposition

**Adopt pg8000 for the initial synthetic implementation, behind a narrow adapter** (product-owner preference), with this exact candidate tree:

| Package | Version | Released | Why this version |
|---|---|---|---|
| pg8000 | **1.31.6** | 2026-10-26 | Only change from 1.31.5: upgrades scramp to 1.5.0. Includes the 1.31.5 fix for CVE-2025-61385 |
| scramp | **1.5.0** | 2026-10-25 | Required exactly by pg8000 1.31.6 (`scramp==1.5.0`). 1.4.18 and 1.5.0 harden SCRAM parsing and iteration-count and salt validation |
| asn1crypto | **1.5.1** | 2022-03-15 | Required by scramp (`>=1.5.1`); latest release |
| python-dateutil | **2.9.0.post0** | 2024-03-01 | Satisfies pg8000's `>=2.8.2`. Mature and widely deployed. Chosen over 3.0.0 and 4.0.0 (see below) |
| six | **1.17.0** | 2024-12-04 | Required by python-dateutil 2.9.0.post0 (`six>=1.5`) |

Use of these packages stays confined to `src/cloud_autopsy/db/` (CA-P2-003b), behind an adapter exposing only connect, execute, fetch, transaction control and typed error mapping.

## Exact artifacts and SHA-256 (PyPI, 2026-11-03)

These are candidate pins for a future hash-locked file. They are **not** a committed lock file. Re-verify them against the package index when the lock is generated, and fail on any difference.

```text
pg8000==1.31.6 \
    --hash=sha256:1ffe27af94fa5b37ce6885b98d591dc75562ff076859bf50ca7729af59345a80 \
    --hash=sha256:553b240256d4b2d8f0ad2af28d07df1f9980247f74ac98d2c2b573762ec1ff1b
scramp==1.5.0 \
    --hash=sha256:8280608f568e81da9e9c9d69cac1331b836622d9b48bf5c5e400e16129c6d1fa \
    --hash=sha256:21b88a54bc4b656f57de9f0f6be531ca99f7efe49220bbd083b84cf88748e395
asn1crypto==1.5.1 \
    --hash=sha256:db4e40728b728508912cbb3d44f19ce188f218e9eba635821bb4b68564f8fd67 \
    --hash=sha256:13ae38502be632115abf8a24cbe5f4da52e3b5231990aff31123c805306ccb9c
python-dateutil==2.9.0.post0 \
    --hash=sha256:a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427 \
    --hash=sha256:37dd54208da7e1cd875388217d5e00ebd4179249f90fb72437e91a35459a0ad3
six==1.17.0 \
    --hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274 \
    --hash=sha256:ff70335d468e7eb6ec65b95b99d3a2836546063f63acc5171de367e834932a81
```

The first hash of each package is the pure-Python wheel and the second the source distribution. Every artifact is pure Python (`py3-none-any` or `py2.py3-none-any`), so there are no native binaries.

## License evidence

| Package | PyPI license metadata | Upstream `LICENSE` at the tag | SPDX (proposed) | NOTICE file | Obligation when redistributed |
|---|---|---|---|---|---|
| pg8000 1.31.6 | `BSD 3-Clause License` (text field); classifier BSD | BSD 3-Clause, "Copyright Mathieu Fenniak and Contributors to pg8000" | `BSD-3-Clause` | None | Keep the copyright and license text; no endorsement use |
| scramp 1.5.0 | `License-Expression: MIT-0` | "MIT No Attribution", "Copyright The Contributors" | `MIT-0` | None | None (no attribution required) |
| asn1crypto 1.5.1 | `MIT` | MIT, "Copyright (c) 2015-2022 Will Bond" | `MIT` | None | Keep the copyright and license text |
| python-dateutil 2.9.0.post0 | `Dual License` | Apache-2.0 for contributions after 2017-12-01; BSD 3-Clause for all code | `Apache-2.0 AND BSD-3-Clause` (reviewer to confirm the expression) | None (only `AUTHORS.md`) | Apache-2.0 §4: provide the license text and keep attributions. No NOTICE file to carry. BSD terms also apply |
| six 1.17.0 | `MIT` | MIT, "Copyright (c) 2010-2024 Benjamin Peterson" | `MIT` | None | Keep the copyright and license text |

**Policy fit:**
- **What the check would accept today:** pg8000 (`BSD-3-Clause`), asn1crypto and six (`MIT`) are in the dependency policy's permissive set.
- **What it would reject until approved:**
  - scramp (`MIT-0`), because `MIT-0` isn't in the set yet. It is a public-domain-equivalent license without an attribution requirement;
  - python-dateutil, because the check matches whole SPDX strings and `Apache-2.0 AND BSD-3-Clause` isn't one of them.

  Both need an approved specialist review record, or a policy amendment, before the supply-chain check passes.
- Under the policy, every package needs `review: approved` before its scope can become `runtime-shipped`. While it is used only for local synthetic tests (`build-and-test`), a `pending` review is allowed.

**No NOTICE file is needed now:** none of these packages ships one, and nothing is redistributed. If a deliverable later bundles them, it needs a third-party license file containing each license text above.

## Security evidence

| Check | Result |
|---|---|
| OSV, exact versions (all five) | No advisories |
| PyPI `vulnerabilities` field, exact versions | None listed |
| pg8000, any version | One advisory: **CVE-2025-61385** / GHSA-wq2g-r956-j8cc / PYSEC-2026-1766, SQL injection through `pg8000.native.literal` with a crafted list; affects versions below 1.31.5, **fixed in 1.31.5**, so 1.31.6 is not affected. The adapter will use server-side parameters, never `literal()` |
| scramp, asn1crypto, python-dateutil, any version | No advisories |
| Yanked releases | None of the candidates is yanked |

**Advisory evidence is a dated manual check**, not continuous monitoring. It must be repeated immediately before the lock is generated, and then on the cadence approved under D6 and D-DB8.

## Python 3.13 compatibility

| Package | Declared support | Evidence |
|---|---|---|
| pg8000 1.31.6 | `requires-python >=3.9`; classifier 3.13 | Declared |
| scramp 1.5.0 | `requires-python >=3.11` | Declared; uses only the standard library plus asn1crypto |
| asn1crypto 1.5.1 | No `requires-python`; classifiers up to 3.10 | Not declared for 3.13. All 23 source files at the tag parse under Python 3.13.5 and import no module removed in 3.12 or 3.13. Static evidence only |
| python-dateutil 2.9.0.post0 | `>=2.7` | Widely used on current Python. Run 3.13 deprecation warnings as errors in CA-P2-003b |
| six 1.17.0 | `>=2.7` (excluding 3.0–3.2) | Pure Python shim |

**Runtime compatibility on 3.13 is not yet demonstrated.** CA-P2-003b must import and exercise the tree on the CI interpreter, with `-W error::DeprecationWarning` for these packages, before relying on it.

## Why not python-dateutil 4.0.0 (or 3.0.0)

- **They are very new.** 4.0.0 was released on 2026-11-01, two days before this evaluation, and 3.0.0 eleven days earlier. Both are authentic releases by the long-time maintainer (GitHub release author `pganssle`), but this cadence is unusual for the project.
- **They change behavior and the dependency tree:**
  - 3.0 rewrote `tz.tzfile` (changing offsets for nonexistent times) and adds a `tzdata` dependency (Apache-2.0, 2026.6), with time-zone data that varies by installed version;
  - 4.0 requires Python 3.11 or later, removes `six`, and makes `isoparse` stricter.
- **Their metadata disagrees with their license.** 4.0.0 declares `License-Expression: BSD-3-Clause`, but its `LICENSE` file is byte-identical to 2.9.0.post0's dual Apache-2.0 and BSD text. Taking the metadata at face value would understate the obligations. This is reported for the licensing reviewer.
- **pg8000 barely depends on it.** pg8000 1.31.6 calls only `dateutil.parser.parse`, as a fallback in `timestamp_in` and `timestamptz_in` when `strptime` fails. It doesn't use `isoparse` or `tz`. Our contract times are stored as `bigint` epoch milliseconds (I6), so dateutil affects only volatile receipt timestamps.
- **Recommendation:** pin 2.9.0.post0 now. Re-evaluate 4.x after a cooling-off period (at least 30 days with no advisories and no yanks) and after the pg8000 maintainers confirm compatibility. Treat a move to 4.x as an inventory change with full review.

## pg8000 versus psycopg 3 for this architecture

| Criterion | pg8000 1.31.6 | psycopg 3.3.7 (latest on PyPI as of 2026-11-03) |
|---|---|---|
| License (metadata) | BSD-3-Clause; dependencies MIT, MIT-0, Apache-2.0 and BSD, MIT | `LGPL-3.0-only` (both `psycopg` and `psycopg-binary`) |
| Native code | None | `psycopg-binary` bundles libpq and its native dependencies (for example OpenSSL); `psycopg-c` needs a compiler and system libpq; the pure-Python option also needs system libpq |
| SBOM size | 5 pure-Python packages | Fewer Python packages, but native libraries inside wheels, each to inventory |
| Fit with our design | DB-API, explicit transactions, server-side parameters; enough for bounded synthetic runs | More features (pipelines, COPY, async) and faster. Not needed at current scale |
| Policy status | Permissive; only `MIT-0` needs a policy decision | **Blocked by our conservative policy** until an approved specialist review |

**Our internal policy versus actual LGPL obligations.** These are separate questions and have to be kept apart.
- **Our policy** is deliberately conservative: any non-permissive license needs an approved review before it can appear in the inventory at all. That is a project rule, not a legal conclusion.
- **Actual LGPL-3.0 obligations**, as understood in engineering terms and pending legal confirmation:
  - **Unmodified library used through a normal import:** the obligations attach mainly to **conveying** the library. That means providing the LGPL and GPL texts, preserving notices, offering the library's corresponding source (including any modifications), and not preventing users from replacing it with a modified version, which normal Python imports satisfy.
  - **Use only within a hosted service** generally doesn't convey the library. LGPL-3.0 has no network clause, unlike AGPL.
  - **Shipping `psycopg-binary` wheels** would also convey the bundled native libraries under their own licenses.

  Whether these hold for our distribution model (D2) is for the licensing reviewer. Nothing here claims they are satisfied.

**Switching cost later:** low. SQL lives in the repository, and the adapter is the only importer of the driver.

## Open questions for an independent licensing reviewer

1. Approve `MIT-0` (scramp) for the permissive set, or record a per-package approval.
2. Confirm the SPDX expression for python-dateutil 2.9.0.post0 (`Apache-2.0 AND BSD-3-Clause`, or another reading of the dual-license text), and record the 4.0.0 metadata-versus-file discrepancy.
3. Confirm that BSD-3-Clause (pg8000) and Apache-2.0 attribution (dateutil) can be met by a third-party license file if the tree is ever redistributed, and that nothing is needed while it is only used in tests.
4. If psycopg 3 is reconsidered: LGPL-3.0 obligations for our distribution and service model (D2), and the licenses of every native library inside `psycopg-binary` for the exact wheel and platform.
5. Whether the upstream move of pg8000 and scramp from GitHub to Codeberg changes any provenance requirement (the release tags and PyPI artifacts were consistent on 2026-11-03).

## Conditions before CA-P2-003b may rely on this disposition

1. **Licensing:** the licensing reviewer records outcomes for all five packages (questions 1–3). Approvals for scramp (`MIT-0`) and python-dateutil (compound expression) are required for the supply-chain check to pass.
2. **Product:** confirmation of D-DB2 (pg8000), and of dateutil 2.9.0.post0 over 4.0.0.
3. **Lock generation:** D5 and D-DB3 approval of the lock-file tool and one-time package-index access. The lock must reproduce exactly the hashes above, or the difference must be investigated.
4. **Advisories:** a fresh OSV/PyPI check (or the approved D6 tool) on the day the lock is created, with no new advisories or yanks.
5. **Supply-chain tool 0.2:** an import allowlist for `pg8000` limited to `src/cloud_autopsy/db/`, inventory entries (scope `build-and-test`, review state as recorded) and a regenerated SBOM.
6. **Runtime compatibility on Python 3.13:** demonstrated in CA-P2-003b CI with deprecation warnings treated as errors.
