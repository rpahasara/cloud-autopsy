# Architecture diagrams and component responsibilities (Proposed)

Owner: Architecture lead. Trace: CA-FR-001 through CA-FR-014, CA-NFR-005, CA-SEC-001 through CA-SEC-012; exact mappings are in [traceability](traceability.md). All boxes and arrows are proposed, not deployed. Diagram source is Mermaid for repository review; rendered previews are in the diagrams directory.

| Diagram | Rendered preview | Vector / source |
|---|---|---|
| System components | [PNG](diagrams/system.png) | [SVG](diagrams/system.svg), [Mermaid](diagrams/system.mmd) |
| Data flows and trust boundaries | [PNG](diagrams/trust-boundaries.png) | [SVG](diagrams/trust-boundaries.svg), [Mermaid](diagrams/trust-boundaries.mmd) |
| Acquisition and freezing | [PNG](diagrams/acquisition-flow.png) | [SVG](diagrams/acquisition-flow.svg), [Mermaid](diagrams/acquisition-flow.mmd) |
| Synthesis and lifecycle | [PNG](diagrams/model-lifecycle-flow.png) | [SVG](diagrams/model-lifecycle-flow.svg), [Mermaid](diagrams/model-lifecycle-flow.mmd) |
| PostgreSQL relationships | [PNG](diagrams/data-model.png) | [SVG](diagrams/data-model.svg), [Mermaid](diagrams/data-model.mmd); details in [logical model](data-model.md) |

## System and component view

```mermaid
flowchart TB
  U[Authenticated investigator] --> API[Control API and policy]
  F[Versioned synthetic fixtures] --> C[Read-only collectors]
  K[Isolated kind namespace] --> C
  O[Allowlisted metrics and logs] --> C
  C --> N[Validate and normalize]
  N --> DB[(PostgreSQL evidence and provenance)]
  API --> W[Run coordinator]
  W --> E[Deterministic engine]
  DB --> E
  E --> B[Frozen bundle and hypothesis ledger]
  B --> DB
  B --> V[Claim and citation validator]
  B --> G[Minimization and egress guard]
  G -. disabled unless authorized .-> M[Isolated synthesis adapter]
  M -. untrusted narrative candidate .-> V
  V --> R[Validated or rejected result]
  R --> API
  B --> EV[Independent scorer]
  GT[Frozen ground truth] --> EV
  EV --> DB
  L[Lifecycle worker] --> DB
```

| Component / identity | Responsibility and owned state | Allowed access and prohibited authority |
|---|---|---|
| C1 Control API / api-reader | Authenticate investigator; validate scenario/window; enforce scopes; return filtered read models; record request audit | Can request runs through coordinator contract; cannot accept approvals, change truth or pass arbitrary URLs/SQL/model prompts |
| C2 Coordinator / run-writer | One bounded run lease; state machine, manifest versions, stage timing and idempotency | Write run state and orchestration audit; no cluster credential, arbitrary command or model-generated scheduling |
| C3 Collector / collector-reader | Fixed query registry, API TLS/source identity, cursors, acquisition status and minimized ingress | Only declared source reads; append through ingest contract; no control DB update, secret read, cluster write or model access |
| C4 Normalizer / evidence-writer | Schema/type/byte validation, source-qualified IDs, immutable evidence and timestamp provenance | Evidence insert transaction; cannot overwrite existing content or alter truth/approval records |
| C5 Engine / engine-worker | Freeze input set; deterministic timeline/relations/gaps; constrained hypothesis evaluation | Read frozen evidence and insert derived records; no live source, provider, arbitrary rule evaluation or truth access |
| C6 Store / postgres-service | Relational integrity, payload separation, fixed read models and run-manifest publication | Separate app roles; no runtime superuser; migrations belong to separately authorized maintenance |
| C7 Egress guard / egress-broker | Minimize and alias fields, enforce current signed-off policy reference and destination | No automatic enablement; only configured adapter destination after separate approval; never fetch model-supplied URLs |
| C8 Synthesis adapter / model-sandbox | Optional bounded transformation of supplied bundle into candidate claims | No Kubernetes/DB credentials, ground truth, shell, approval or general tool dispatcher; egress denied by default |
| C9 Claim validator / engine-worker | Reject unknown IDs, invalid schema, unsupported causal promotion and prohibited fields | Model never writes authoritative hypotheses; rejected output stays quarantined/minimized |
| C10 Scorer / evaluator | Compare sealed results with independently frozen truth; retain every failure | Read truth and frozen outputs; cannot change engine bundle or overwrite scored runs |
| C11 Lifecycle / lifecycle-worker | Evaluate expiry, tombstone before purge, remove payload copies, audit retries | Narrow deletion procedures and metadata view; no source/model access, risk acceptance or approval creation |

Engine, normalizer and coordinator are logical modules within the local trusted process initially; their database roles remain explicit design boundaries, not a claim of isolation against process compromise. Collector, lifecycle credentials and model process need separate execution contexts. Human fixture setup uses a different identity from all runtime components.

## Data-flow and trust boundaries

```mermaid
flowchart TB
  subgraph Z0[TB0 human and version-control boundary]
    H[Authenticated investigator]
    CFG[Reviewed scenario and policy versions]
    TRUTH[Independent ground truth]
  end
  subgraph Z1[TB1 untrusted source boundary]
    SRC[Kubernetes API and telemetry]
  end
  subgraph Z2[TB2 local acquisition boundary]
    COL[Collector identity]
    NOR[Ingress validator and minimizer]
  end
  subgraph Z3[TB3 trusted evaluation boundary]
    CTRL[API and coordinator]
    STORE[(Evidence and run store)]
    ENG[Engine and claim validator]
    SCORE[Independent scoring module]
    LIFE[Lifecycle identity]
  end
  subgraph Z4[TB4 untrusted model boundary]
    ADP[No-tool synthesis sandbox]
  end
  subgraph Z5[TB5 external provider boundary - disabled]
    EXT[Separately approved provider]
  end
  H -->|F1 scoped request| CTRL
  CFG -->|F2 versioned allowlists| CTRL
  SRC -->|F3 TLS reads - hostile content| COL
  COL -->|F4 bounded acquisition envelope| NOR
  NOR -->|F5 validated insert| STORE
  CTRL -->|F6 freeze manifest| STORE
  STORE -->|F7 frozen evidence only| ENG
  ENG -->|F8 minimized data contract| ADP
  ADP -. F9 approved broker only .-> EXT
  ADP -->|F10 untrusted claims| ENG
  ENG -->|F11 immutable results| STORE
  TRUTH -->|F12 isolated truth| SCORE
  STORE -->|F13 sealed results| SCORE
  SCORE -->|F14 versioned scores| STORE
  LIFE -->|F15 lifecycle overlay and purge| STORE
  STORE -->|F16 filtered export| CTRL
```

TB0 inputs are authorized only by authenticated role and pinned version, never by text claiming authority. TB1 TLS authenticates the endpoint, not the truth of its telemetry. TB2 ingress validation reduces disclosure but cannot make hostile text trustworthy. TB3 separates truth/scoring and lifecycle authority from reasoning. TB4 treats even a local model as untrusted computation. TB5 crosses organizational/data-retention control and is absent from the baseline network allowlist.

## Acquisition, freezing and failure flow

```mermaid
sequenceDiagram
  participant I as Investigator
  participant A as API and coordinator
  participant C as Collector
  participant S as Source API
  participant D as Evidence store
  participant E as Engine
  I->>A: F1 scenario ID, window, idempotency key
  A->>A: Authenticate, authorize, validate versions and limits
  A->>C: F2 fixed source/query plan
  C->>S: F3 scoped list then watch or bounded query
  S-->>C: observations or error
  C->>D: F4-F5 bounded records and acquisition status
  alt timeout, 410, truncation or denied source
    C->>D: explicit coverage gap and last durable cursor
  end
  A->>D: F6 atomically seal evidence membership and digest
  A->>E: immutable manifest reference
  E->>D: F7 verify integrity and availability snapshot
  E->>D: F11 deterministic bundle, gaps and hypotheses
  D-->>A: F16 complete or partial result
  A-->>I: result with limitations, no approval claim
```

## Model and lifecycle flow

```mermaid
sequenceDiagram
  participant E as Engine
  participant G as Egress guard
  participant M as Model sandbox
  participant V as Claim validator
  participant L as Lifecycle worker
  participant D as Evidence store
  E->>G: frozen bundle and policy reference
  G->>G: Disabled by default, minimize, alias, size-check
  alt approved local synthesis or separately approved external route
    G->>M: F8 bounded data-only contract
    M-->>V: F10 schema-constrained candidate claims
    V->>D: validated claims or typed rejection
  else disabled, timeout or policy denial
    G-->>E: synthesis unavailable, deterministic result retained
  end
  L->>D: F15 lock affected artifact lifecycle rows
  L->>D: append tombstone and set unavailable atomically
  L->>D: purge payload, derivatives and controlled exports
  L->>D: record purge completion or retryable failure
  E->>D: replay availability and integrity check
  D-->>E: retained inputs or explicit incomplete replay state
```

The [API contract](api.md) names envelopes for these flows; the [security coverage matrix](security.md) maps every F1–F16 flow to STRIDE threats and verification requirements.
