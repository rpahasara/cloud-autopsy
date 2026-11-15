# CA-P2-007c: independent evaluation of the product engine (plan)

**Status:** a documentation-only plan for product-owner approval. Nothing here is implemented, and PR #14 is not changed by it.

**Why it is needed.** The CA-P2-007a/b evaluations ([closeout](ca-p2-007-closeout.md)) were authored, run and scored by the engine's developer. They are development-set evidence only, and they are **not independent**.

**Sources:**
- PR #14's held-out kit, `ca-heldout-kit/0.3`, branch `eval/heldout-authoring-kit` at `890a03d`;
- the [corpus plan](../../scenarios/corpus-plan.md);
- the [benchmark plan](../../reviews/phase1d/benchmark-plan.md);
- [CA-DEC-006](../../architecture/adr/CA-DEC-006.md).

## 1. What PR #14 gives and what ties it to the prototype

**Reusable as it is:**
- strict JSON;
- freeze and verify records (`ca-heldout-freeze/0.1`);
- salted truth commitments (`ca-heldout-truth-commitment/0.1`, never overwritten);
- the seal (`ca-heldout-seal/0.2`);
- the metadata schema;
- the rule that truth and salt never enter a Git work tree;
- the seven custody rules;
- the `not_run` / `scoring_failed` classes and the every-variant-in-every-denominator rule;
- the "cannot evaluate" and "not independent" reporting.

**Tied to the prototype, so it must change for the product:**

| Kit part | Prototype assumption | Product reality |
|---|---|---|
| Inputs | Hand-written `ca-fixture/0.1` observations, overlay variants, source plan, synthesis stubs | Live collection from a disposable kind cluster (recordings 0.4–0.7), converted to bundles |
| Engine adapter (`_import_engine`) | Imports `prototype/ca_spike` and `ca_eval` | `src/cloud_autopsy`: collector → converter → engine (rule profiles 1–3) → PostgreSQL with verify-on-read |
| Output | `run.json`, `bundle.json` ledger, `evidence.json`, `baseline.json`, `synthesis.json` | A result document (`ca-investigation-result/0.2`) plus a run record |
| Scorer | `prototype/ca_eval/scorer.py` (`ca-scorer/0.2-spike`) with truth pins | A product scorer is needed. `tools/eval/score.py` keeps its truth **inside the repository**, which violates custody rule 1 |
| Mechanism vocabulary | `config_value_change`, `deployment_rollout` | `rollout_limit_reduction`, `config_limit_reduction` (catalog 0.1) |
| Candidate | One commit (`c21b50d`) | A commit plus rule profile, engine and catalog, contract profile 4, recording 0.7, migrations 0001–0009, kind node image and workload image |
| Author restrictions | Prototype paths only | Must also cover `src/cloud_autopsy`, `tools/eval` (including **all CA-P2-007 scenarios and results**), `tests/engine`, `tests/collector`, `deploy/kind` and the Phase 2 docs |
| Adjudication | The reviewer scores; the author confirms the truth hash | The benchmark plan needs two independent scorers and a pre-appointed adjudicator |

**Mechanical facts.** PR #14 still conflicts with `main` in `.github/workflows/spike-ci.yml` and `.gitignore`, and both conflicts are additive. Integrating #42–#47 will make the `spike-ci.yml` conflict larger, though not harder.

## 2. Plan

### 2.1 People, before anything else

The roles follow the kit and the benchmark plan:
- **Scenario author:** independent of the engine.
- **Truth custodian and reviewer:** independent of both the author and the engine.
- **Two scorers.**
- **A pre-appointed adjudicator.**
- **An executor:** may be anyone, including the engine's developer. The executor never sees truth.

**Neither this session nor anyone who built or tuned the engine may author scenarios, hold truth or adjudicate.**

The author restriction list grows to include the product code, `tools/eval`, every CA-P2-007 scenario, record and result, and these Phase 2 records. An exposed author's family is reported as "not independent". **Appointing these people is the gating step, and only the product owner can do it.**

### 2.2 The product kit, as a new kit version

The product kit is `ca-heldout-kit/0.4-product`, built **on a new branch from PR #14's head with a merge commit, never a rebase**. PR #14's history and the frozen prototype path stay intact, and the prototype mode keeps working.

**Scenario form.** A family is an **injection specification**:
- initial workload and namespace settings;
- the injected actions and their timing;
- RBAC and collection bounds;
- an optional workload variant from a reviewed catalog.

Its truth is separate: the cause (mechanism, namespace and Deployment, the typed change) or none; distractors; required evidence; and expected outcome, gaps and abstention reason. The specification and the truth are frozen, committed with a salt, and sealed with the kit's existing records. **The truth never appears in the specification, and no file in the repository ever holds it.** This replaces the inline truth that `tools/eval` uses.

**Candidate pin.** The seal's `candidate` names:
- the commit;
- the rule profile (3) and the engine, catalog and timeline-rule versions;
- contract profile 4;
- recording 0.7 and collector mode;
- the migration set (0001–0009 checksums);
- the kind node and workload image digests;
- the scorer version.

`run` refuses a dirty work tree or any mismatch.

**Execution.** The executor runs the sealed specifications with the existing driver approach: a fresh cluster per repetition, an append-only attempt log, exclusive records and integrity before scoring. The executor never receives truth. The engine sees only what the collector records.

### 2.3 Metrics and thresholds, pre-registered before the seal

The metrics are those of the benchmark plan:
- causal-attribution accuracy (the mechanism rubric; the right entity alone is not enough);
- false-cause selection over assessable traps, with every selected distractor exposed;
- correct abstention over designated unresolvable cases, and unnecessary abstention over resolvable ones;
- required-evidence recall;
- citation validity;
- unsupported confirmed causes;
- deterministic equivalence;
- leaks.

The targets are CA-DEC-006's, which are still **Proposed**. They must be approved and frozen before the seal:
- 100% valid citations;
- zero unsupported confirmed causes;
- zero false-cause selections;
- 100% correct abstention on designated gap cases;
- 100% deterministic equivalence;
- zero secret-canary propagation.

The kit's current rule of no thresholds would then apply only to measured-only metrics. Families the candidate cannot evaluate (no mechanism in catalog 0.1) are reported separately, never dropped.

### 2.4 Replay, integrity and leaks

Every run gets:
- offline replay twice;
- PostgreSQL storage with verify-on-read, byte-identical to offline;
- a later second database replay by the reviewer.

The records, attempt logs, reports and their checksums are archived durably (as proposed in the closeout). The author plants their own canaries, unknown to the engine's developer, and the scan uses them.

### 2.5 Scoring and adjudication

- Two scorers score blinded outputs independently, with the product scorer adapted to opened truth.
- Disagreements go to the adjudicator, and the disagreement, ruling and reasons are recorded.
- One primary class applies per run:
  - correct attribution;
  - incorrect attribution;
  - change identity unverifiable;
  - justified abstention;
  - unnecessary abstention;
  - resolved when abstention was expected;
  - execution failed;
  - not run;
  - scoring failed.
- False-cause selection is also flagged.
- Publishing results retires the families as held-out.

### 2.6 Delivery steps (each needs approval)

1. **Appoint the people** (§2.1).
2. **Approve CA-DEC-006 targets** as frozen thresholds for this evaluation.
3. **Build kit 0.4-product** on a branch merged from PR #14: the adapter, the injection-spec and truth schemas, the candidate pin and the product scorer adapter. Tests use developer-authored *example* families only, never held-out ones.
4. **Independent authoring and sealing** outside the repository.
5. **Freeze the candidate** (tag) and **execute**.
6. **Score, adjudicate and report.** Every family and run is reported, including failures.

**Until step 6 is complete, no independent accuracy claim is made.**
