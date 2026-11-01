# Differentiation strategy — hypotheses to validate

Status: Proposed product strategy. Owner: Product / requirements authority. Risks: CA-RISK-001/006/008/009/010. Evidence basis: proposed SRS/architecture and [technology research](technology-evaluation.md); no customer or comparative benchmark result is claimed.

## Product position

Cloud Autopsy should be an evidence reconstruction and review layer over existing telemetry, giving an investigator an inspectable account of what was observed, what supports a mechanism, what contradicts it, and what remains unknowable. The initial hypothesis is for small Kubernetes platform/SRE teams needing trustworthy incident review. “AI SRE,” generic chat, dashboard replacement and autonomous remediation are outside the proposed wedge.

| Differentiation hypothesis | Proposed product behavior | Observable proof / falsifier |
|---|---|---|
| Evidence provenance | Source-qualified immutable identities, raw-versus-derived separation, timestamp provenance and rule/input links for every derived assertion | Reviewer can trace a claim to allowed evidence and detect changed inputs; fails if provenance cannot distinguish source truth, normalization and model text |
| Deterministic reconstruction | Frozen inputs and versioned rules produce equivalent bundle/ledger outputs independent of delivery order and optional model availability | Equivalent deterministic digest across repeats/permutations; fails if narration, wall-clock metadata or live queries alter causal output |
| Constrained causal attribution | Require observable mechanism/consumption links, preserve contradiction and distinguish correlation from support; abstain under mandatory gaps | Reject correlated Deployment in scenario 001 and novel distractors; fails if removing causal evidence causes an invented substitute explanation |
| Investigation replay | Compare immutable attempts with clear version/availability differences; expiry and authorized deletion cause honest incomplete replay | Reproduce from retained inputs and distinguish missing/tampered/expired states; fails if replay silently fetches fresh evidence or rewrites scores |
| Measurable investigation accuracy | Report fact support, citation membership, false-cause selection, abstention, coverage and failure counts separately | Independent blinded scoring on held-out families; fails if only fluent narratives or aggregate citation existence are measured |

Do not assert competitors lack provenance, replay or evaluation features without testing their pinned versions. The proposed advantage is the combined, enforced contract plus demonstrated outcomes; its superiority is currently unproven. Open-source telemetry pipelines are complementary infrastructure, while HolmesGPT/K8sGPT and manual dashboard workflows are investigation comparators serving partly different tasks.

## Build, integrate and defer

Build the versioned evidence/uncertainty model, deterministic assembler, ledger, assertion checks, replay and evaluator. Integrate narrow read-only Kubernetes/Prometheus/Loki APIs; consume existing OpenTelemetry/Alloy pipelines where useful. Keep agents as isolated benchmarks. Defer broad connectors, production tenancy, graph DB/workflow infrastructure, polished UI, remediation, automated approval and external-model dependence.

## Commercial validation and claims discipline

Before a pilot proposal, show versioned investigation artifacts and observed limitations to target investigators; test whether provenance/replay improves reviewer confidence and evidence inspection time. Any later discovery study must specify participant recruitment, consent, tasks and analysis separately. Existing charter pilot/discovery targets remain unvalidated hypotheses. Do not translate citation-ID validity into causal accuracy, simulated task time into MTTR reduction, or zero observed safety failures into guaranteed safety. A claim of improved investigation accuracy needs the controlled benchmark and independent review in the [benchmark plan](benchmark-plan.md).

Revisit the wedge if deterministic baseline adds no supported-fact/false-cause/abstention benefit at comparable evidence access, if replay is not valued by investigators, or if integration/maintenance cost exceeds observed value. Product owner decides the next scope from evidence rather than a broad feature checklist.
