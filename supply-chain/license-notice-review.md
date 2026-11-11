# License and NOTICE review record (Proposed)

Status (synchronized with the inventory on 2026-11-11): no review is complete. Each is pending, or provisional where the product owner recorded a provisional disposition for the synthetic-only test environment, which is not legal clearance. No licensing reviewer is named yet (decision D7). The SPDX values below are engineering observations taken from the referenced license files. They are not legal clearance. Policy: [dependency and SSDLC policy](../docs/phase2/ca-p2-001/dependency-policy.md). Machine-readable source: [dependency inventory](dependency-inventory.json).

| Component | Pin | Scope | Observed license | Source | Redistributed | NOTICE obligation | Review |
|---|---|---|---|---|---|---|---|
| CPython | 3.13 line | build-and-test | PSF-2.0 | [docs.python.org](https://docs.python.org/3.13/license.html) | No | None while not shipped | Pending |
| actions/checkout | `11bd71901bbe5b1630ceea73d27597364c9af683` (v4.2.2) | ci-only | MIT | [LICENSE at pin](https://github.com/actions/checkout/blob/11bd71901bbe5b1630ceea73d27597364c9af683/LICENSE) | No | None (not redistributed) | Pending |
| actions/setup-python | `a26af69be951a213d495a4c3e4e4022e16d87065` (v5.6.0) | ci-only | MIT | [LICENSE at pin](https://github.com/actions/setup-python/blob/a26af69be951a213d495a4c3e4e4022e16d87065/LICENSE) | No | None (not redistributed) | Pending |
| GitHub-hosted runner `ubuntu-24.04` | Mutable label | ci-only | MIT (image definitions only) | [runner-images](https://github.com/actions/runner-images/blob/main/LICENSE) | No | None; preinstalled software is never shipped | Pending; mutable-label exception D10 |
| pg8000 | `1.31.6` (hash-locked, `requirements-db.txt`) | build-and-test | BSD-3-Clause | [LICENSE at tag](https://codeberg.org/tlocke/pg8000/raw/tag/1.31.6/LICENSE); [copy](licenses/pg8000-1.31.6-LICENSE.txt) | No | None (not redistributed) | Pending |
| scramp | `1.5.0` (hash-locked) | build-and-test | MIT-0 | [LICENSE at tag](https://codeberg.org/tlocke/scramp/raw/tag/1.5.0/LICENSE); [copy](licenses/scramp-1.5.0-LICENSE.txt) | No | None (not redistributed) | [Provisional](../docs/phase2/ca-p2-003/ca-p2-003b-1.md#provisional-license-dispositions) |
| asn1crypto | `1.5.1` (hash-locked) | build-and-test | MIT | [LICENSE at tag](https://github.com/wbond/asn1crypto/blob/1.5.1/LICENSE); [copy](licenses/asn1crypto-1.5.1-LICENSE.txt) | No | None (not redistributed) | Pending |
| python-dateutil | `2.9.0.post0` (hash-locked) | build-and-test | BSD-3-Clause AND (Apache-2.0 OR BSD-3-Clause) | [LICENSE at tag](https://github.com/dateutil/dateutil/blob/2.9.0.post0/LICENSE); [copy](licenses/python-dateutil-2.9.0.post0-LICENSE.txt) | No | None (not redistributed) | [Provisional](../docs/phase2/ca-p2-003/ca-p2-003b-1.md#provisional-license-dispositions) |
| six | `1.17.0` (hash-locked) | build-and-test | MIT | [LICENSE at tag](https://github.com/benjaminp/six/blob/1.17.0/LICENSE); [copy](licenses/six-1.17.0-LICENSE.txt) | No | None (not redistributed) | Pending |
| postgres (container image) | `18.6-trixie@sha256:e3d24f6906d0760bf4da0dae872415391ededefad23fd471c47dc53b0ddf3c42` | ci-only | PostgreSQL | [licence](https://www.postgresql.org/about/licence/); [copy](licenses/postgresql-18.6-COPYRIGHT.txt) | No (pulled at test time, never shipped) | None (not redistributed) | [Provisional](../docs/phase2/ca-p2-003/ca-p2-003b-1.md#provisional-license-dispositions) |

## NOTICE status

No third-party code, binary, container image or model artifact is redistributed by this repository, so no NOTICE file is required yet. The project's own license is undecided (D2). When the first `runtime-shipped` component is approved, add a `NOTICE` file with the attributions its license requires, and link it from this record.

## Not bundled and not reviewed here

The [technology evaluation](../docs/reviews/phase1d/technology-evaluation.md) lists candidates such as Prometheus, Loki, OpenTelemetry Collector and comparators. None of them is a dependency of this repository, and none appears in the inventory. PostgreSQL is now a dependency, as the disposable test image above; the server is never redistributed. Loki and Grafana (AGPL) and Vector (MPL) would fail the policy check until a licensing reviewer records an approval.
