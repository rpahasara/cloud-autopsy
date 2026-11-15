# CA-P2-007 evaluation evidence archive

This folder is a durable copy of the sanitized evidence from the three CA-P2-007 development evaluations. GitHub keeps Actions logs for 90 days, so this evidence would otherwise expire around 2027-02-12.

- **Content.** Each run is copied unchanged from its job log and is not re-run. The [CA-P2-007a](../ca-p2-007a.md#results) and [CA-P2-007b](../ca-p2-007b.md#results) records report the results. The closeout is `docs/phase2/ca-p2-007/ca-p2-007-closeout.md` in PR #48.
- **Independence.** These are developer-authored evaluations. They are **not independent** accuracy certification.

| Run | Evaluation | Baseline (tag) | Scenario file and digest | Records | `attempts.log` | `SHA256SUMS` SHA-256 |
|---|---|---|---|---|---|---|
| [43585433667](43585433667/provenance.json) | v0.1, original and untuned | `45bcebd` (`ca/eval-007a-run1-baseline-45bcebd`) | `scenarios.json`, `sha256:970f12fc…` | 41 | none (the run predates it; not reconstructed) | `346a2ade73e14b6b95c1aaa16f393c648bf65b61144db97d5967ec67118e1ad4` |
| [43609551810](43609551810/provenance.json) | v0.2, window at +10 s | `3499bbb` (`ca/eval-007b-v02-run1-baseline-3499bbb`) | `scenarios-0.2.json`, `sha256:fecb7c20…` | 41 | 41 lines | `9e6767b8849242b3f8e4835de20533387b8433db92660ec18bc96e2e21871f73` |
| [43609551789](43609551789/provenance.json) | timing matrix 0.1 | `3499bbb` (`ca/eval-007b-matrix-run1-baseline-3499bbb`) | `timing-matrix-0.1.json`, `sha256:27e43de2…` | 45 | 45 lines | `e54979ec6e1fbdde8df5108e8e819a670810f3901c133e31dacbc66511804a11` |

## What each run folder holds

| File | Content |
|---|---|
| `<scenario>-<nn>.json` | Each run record, exactly as the job printed it |
| `attempts.log` | The append-only attempt log (007b runs only) |
| `report.md` | The scored report, exactly as the job printed it |
| `baseline.txt` | The baseline lines from the job summary |
| `provenance.json` | The run ID, the baseline commit and tag, the scenario digest, the SHA-256 of the raw job log, and the SHA-256 of the extraction script |
| `SHA256SUMS` | Checksums over every other file in the folder |

The raw logs and the extraction script are kept in a restricted backup outside the repository. They are not published.

## Verification (2026-11-15, before publishing)

- **Records:** all 127 are present (41 + 41 + 45). Each file name matches its record's IDs, and each scenario digest matches its frozen scenario file.
- **Integrity:** the v0.2 and matrix records pass the scorer's pre-registration integrity gate. They are exactly the pre-registered run set, and each run was attempted once.
- **Re-scoring:** each run was re-scored offline with its own original scorer, in a clean worktree of its baseline commit, and reproduced its archived `report.md` exactly. All criteria were met in all three.
  - v0.1 used `ca-eval-scorer/0.1-provisional` at `45bcebd`.
  - v0.2 and the matrix used `ca-eval-scorer/0.2-provisional` at `3499bbb`.
- **Checksums:** every `SHA256SUMS` verifies.
- **Leak scan:** all 141 files were scanned. There were zero hits for the kind checks' planted values and log needles, and none for generic credential patterns (`Bearer`, `PRIVATE KEY`, `eyJ`, `ghp_`, `Authorization`, `password`, `secret`, `token`).

**How to verify again:** in each run folder, run `sha256sum -c SHA256SUMS`. To re-score a run, check out its baseline commit and run `python -I tools/eval/score.py <a copy of the records and attempts.log> [--scenarios <file>]`. The output must equal `report.md`.
