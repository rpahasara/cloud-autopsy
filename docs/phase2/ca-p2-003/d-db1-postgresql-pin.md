# D-DB1 — PostgreSQL 18 minor and container-image pin (proposed)

Date: 2026-11-03. Status: **proposed for the disposable synthetic test environment only, not approved**. No container was launched, no image layer was pulled and nothing was installed. Evidence came from the PostgreSQL project's website, the Docker official-images definition and the Docker Hub registry API. Only manifests, configuration and the provenance attestation (small JSON documents) were read, and every one was hash-checked locally. Needs DB-reviewer and security-reviewer approval (D-DB1, D-DB7).

## Recommendation

| Item | Value |
|---|---|
| PostgreSQL release | **18.6**, the current minor of the 18 line |
| Image | Docker official image `postgres`, tag **`18.6-trixie`** (Debian 13 `trixie-slim` base, glibc) |
| Pin (multi-platform index) | **`postgres@sha256:3a4264520e121176619f54ff867d12774bc81e95e7b84db58d63bccdb6144b81`** |
| linux/amd64 manifest (GitHub-hosted runners and typical development machines) | `sha256:f4b419e350fd98d4a8429603295208976dea4c8fb8326d818d346d3e29f1db6f` |
| linux/arm64/v8 manifest | `sha256:9a74990a5c776ff210361b67616b347750c66c36ea0dfbb4f575d19fcc3d8437` |
| Debian package inside | `PG_VERSION=18.6-1.pgdg13+2` (PGDG `trixie-pgdg` repository) |
| Use | Disposable, loopback-only, synthetic-only test database; never shipped |

Reference it **by digest only**, for example `postgres:18.6-trixie@sha256:3a42…4b81`. Tags move: on 2026-11-03 `18.6`, `18`, `18-trixie`, `18.6-trixie` and `latest` all resolved to this same index, and each will move when the image is rebuilt or 18.7 is published.

**Why trixie:**
- It's the default variant (the `18` and `latest` tags) and the current Debian stable release, with glibc.
- **bookworm** (`18.6-bookworm`, index `sha256:5c4783a8cc3f0074912164f94dfa1be4e043438f0f707cf968d7af9a0d31a2c8`) is the older Debian release, with fewer architectures.
- **alpine** uses musl and other locale and collation libraries, which would make text-ordering behavior differ from typical glibc deployments.

## Release and support status (postgresql.org, 2026-11-03)

| Fact | Value | Source |
|---|---|---|
| Line | 18, supported | [Versioning policy](https://www.postgresql.org/support/versioning/): "Current minor 18.6, Supported Yes" |
| First release of 18 | 2025-09-25 | Versioning policy |
| Final release (end of life) for 18 | **2030-11-14** | Versioning policy |
| 18.6 release date | **2026-08-13** | [18.6 release notes](https://www.postgresql.org/docs/release/18.6/) |
| 18.5 | **Never released** ("18.5 was never released, due to a regression discovered post-wrap"); its release-notes URL redirects to 18.6 | 18.6 release notes |
| Security content | 18.6 fixes, among others, CVE-2025-8714 and CVE-2026-14662/14663/14664/14666/14668/14669/14670; some need configuration or data clean-up after upgrade (none affects a fresh disposable database) | 18.6 release notes |
| Source tarball | `postgresql-18.6.tar.bz2` SHA-256 `555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f` (published `.sha256`; for reference only, since we use the packaged image) | ftp.postgresql.org |
| Next scheduled minor | The second Thursday of February, May, August and November. **18.7 is expected on 2026-11-12**, nine days after this evaluation, and may contain security fixes | [Roadmap](https://www.postgresql.org/developer/roadmap/) |
| License | PostgreSQL License (permissive) | [postgresql.org/about/licence](https://www.postgresql.org/about/licence/) |

## Image provenance and verification evidence

| Check | Result |
|---|---|
| Official definition | `docker-library/official-images` `library/postgres` (last changed 2026-10-16, commit `1b851c6`): `Tags: 18.6, 18, latest, 18.6-trixie, 18-trixie, trixie`, `GitCommit: e00e1bd34ec5c8a8e7ad89b273b3d42efaf6d5bc`, `Directory: 18/trixie` |
| Packaging source | `docker-library/postgres@e00e1bd` (2026-08-13, "Update 18 to 18.6, trixie 18.6-1.pgdg13+2, bookworm 18.6-1.pgdg12+2"); MIT-licensed packaging repository |
| Dockerfile (`18/trixie` at that commit) | `FROM debian:trixie-slim`; `PG_MAJOR 18`; `PG_VERSION 18.6-1.pgdg13+2`; PGDG apt repository with signing key `B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`; `gosu 1.19`, verified with a GPG signature; `EXPOSE 5432`; `STOPSIGNAL SIGINT` |
| Registry index | `Docker-Content-Digest` equals the locally computed SHA-256 of the index bytes; OCI index with 8 platform images, each with an attestation manifest |
| amd64 manifest | Bytes hash to its digest. 13 layers, about 162.5 MB. OCI annotations: `image.version 18.6`, `image.revision e00e1bd…`, `image.source …postgres.git#e00e1bd…:18/trixie`, `image.base.name debian:trixie-slim`, `image.base.digest sha256:1e1a22175fbf1b32157ddaf0219e1db4e5401fab2b94ed285add64d18587cd2d`, `image.created 2026-10-28T01:30:07Z` |
| amd64 config | Digest `sha256:a1be1c8380f5c8ca80b4ad72f6be191f8a283e0ecb2e9496b1ee67dc0022d0f1`, verified. `PG_VERSION=18.6-1.pgdg13+2`. Runs as root, then the entrypoint drops to `postgres` via `gosu` |
| Attestations (amd64) | SPDX SBOM (`application/vnd.in-toto+json`, predicate `https://spdx.dev/Document`, about 6.0 MB, not downloaded) and SLSA provenance v0.2 (about 52 KB, read and hash-verified) |
| SLSA provenance | Subjects `pkg:docker/postgres@18.6` and `@18` (linux/amd64) with digest `f4b419e3…`. `builder.id https://github.com/docker-library`. BuildKit build type. Config source `postgres.git#e00e1bd…:18/trixie`. Base-image material `1e1a2217…`, matching the annotation. Built 2026-10-28T01:30:09–01:30:39Z. `reproducible: false` |

## Limitations of this evidence

- **Attestations are not signed.** They're bound to the index by content address, but carry no cryptographic signature that was verified. Trust rests on the Docker Hub official-images pipeline, the TLS connection to the registry and the published official-images definition. Verifying signed provenance, if adopted, needs D6 tool approval.
- **No vulnerability scan** of the image's Debian packages was run (D6 and D-DB8). The SPDX SBOM exists but was not downloaded or analyzed.
- **The image ages.** A digest pin is immutable, but its Debian base accumulates advisories. Old digests stay addressable on Docker Hub today, but retention isn't guaranteed. Anonymous pulls in CI are rate-limited.
- **The build is not reproducible** (`reproducible: false`), so the image can't be rebuilt bit-for-bit from source.

## Conditions before CA-P2-003b uses this pin

1. **Re-check at the start of CA-P2-003b.** If 18.7 (expected 2026-11-12) or a later minor is out, repeat this procedure for it rather than starting on 18.6, because minors carry security fixes. Record the new index and platform digests, the provenance check and the release notes. Never use a tag alone.
2. **D-DB1 approval** of the exact digest by the DB reviewer and security reviewer, and **D-DB7 approval** of a disposable, loopback-only, synthetic-only container locally and as a CI `services:` container.
3. **Supply-chain tool 0.2:** a `container-image` inventory type that requires an `@sha256:` pin, and workflow `image:`/`services:` checks.
4. **Vulnerability-scan decision (D6, D-DB8):** scan the image SBOM, or record an accepted limitation for a disposable test database holding only synthetic data.
5. **Refresh policy:** the upgrade owner (D7) re-pins on each scheduled minor release (quarterly) or on any PostgreSQL security release, using the same evidence steps.

## <a id="how-to-repeat-this-verification"></a>How to repeat this verification

1. Read the [versioning policy](https://www.postgresql.org/support/versioning/), the release notes and the roadmap.
2. Read `library/postgres` in `docker-library/official-images` and note the tag's `GitCommit` and `Directory`.
3. Read that Dockerfile at that commit.
4. Request a pull-only registry token, then fetch the tag's manifest with the OCI index `Accept` header. Hash the bytes and compare them with `Docker-Content-Digest`.
5. Fetch the platform manifest, its config and the attestation manifest, and hash each.
6. Read the SLSA provenance and confirm its subject, builder, source revision and base-image material against the annotations.
