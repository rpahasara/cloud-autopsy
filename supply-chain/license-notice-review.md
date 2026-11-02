# License and NOTICE review record (Proposed)

Status: every review is pending. No licensing reviewer is named yet (decision D7). The SPDX values below are engineering observations taken from the referenced license files. They are not legal clearance. Policy: [dependency and SSDLC policy](../docs/phase2/ca-p2-001/dependency-policy.md). Machine-readable source: [dependency inventory](dependency-inventory.json).

| Component | Pin | Scope | Observed license | Source | Redistributed | NOTICE obligation | Review |
|---|---|---|---|---|---|---|---|
| CPython | 3.13 line | build-and-test | PSF-2.0 | [docs.python.org](https://docs.python.org/3.13/license.html) | No | None while not shipped | Pending |
| actions/checkout | `11bd71901bbe5b1630ceea73d27597364c9af683` (v4.2.2) | ci-only | MIT | [LICENSE at pin](https://github.com/actions/checkout/blob/11bd71901bbe5b1630ceea73d27597364c9af683/LICENSE) | No | None (not redistributed) | Pending |
| actions/setup-python | `a26af69be951a213d495a4c3e4e4022e16d87065` (v5.6.0) | ci-only | MIT | [LICENSE at pin](https://github.com/actions/setup-python/blob/a26af69be951a213d495a4c3e4e4022e16d87065/LICENSE) | No | None (not redistributed) | Pending |
| GitHub-hosted runner `ubuntu-24.04` | Mutable label | ci-only | MIT (image definitions only) | [runner-images](https://github.com/actions/runner-images/blob/main/LICENSE) | No | None; preinstalled software is never shipped | Pending; mutable-label exception D10 |

## NOTICE status

No third-party code, binary, container image or model artifact is redistributed by this repository, so no NOTICE file is required yet. The project's own license is undecided (D2). When the first `runtime-shipped` component is approved, add a `NOTICE` file with the attributions its license requires, and link it from this record.

## Not bundled and not reviewed here

The [technology evaluation](../docs/reviews/phase1d/technology-evaluation.md) lists candidates such as PostgreSQL, Prometheus, Loki, OpenTelemetry Collector and comparators. None of them is a dependency of this repository, and none appears in the inventory. Loki and Grafana (AGPL) and Vector (MPL) would fail the policy check until a licensing reviewer records an approval.
