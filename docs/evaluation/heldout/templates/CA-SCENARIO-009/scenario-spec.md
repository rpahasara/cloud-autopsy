# CA-SCENARIO-009 — <<FILL: title>>

Private specification. Keep with the ground truth outside the repository until scoring. Coverage category from the [corpus plan](../../../../scenarios/corpus-plan.md): **Unseen missing/contradictory evidence combination** (held out).

| Field | Value |
|---|---|
| Scenario version | <<FILL>> |
| Fixture ID / version | `ca-scenario-009` / <<FILL>> |
| Author / reviewer | <<FILL>> / <<FILL>> |
| Frozen candidate | `c21b50dc5edd6cd07de55d2f3e0bce6103b4d952` |

## 1. Purpose

<<FILL: what capability this family probes and why it is realistic>>

## 2. Incident narrative

<<FILL: timeline in reference time, workload, load, the real causal chain>>

## 3. Ground truth summary

<<FILL: causal change (exact source_ref) or why none; declared non-causes and why each is misleading>>

## 4. Preconditions and resource identities

<<FILL: namespaces, objects, UIDs, same-name objects and how they are distinguished>>

## 5. Clock domains and timestamp uncertainty

<<FILL: each domain, declared offset/uncertainty/precision or unknown, and which orderings are decidable>>

## 6. Evidence and provenance

<<FILL: each source query, its status, and the source_ref scheme used>>

## 7. Variants

<<FILL: one subsection per variant with overlay operations and the reasoning for its expected answer>>

## 8. Adversarial content

<<FILL: hostile telemetry, identity collisions or malformed synthesis responses, and what a safe investigator must not do>>

## 9. Expected answers

<<FILL: per-variant table mirroring ground-truth.json>>

## 10. Consistency self-check

- [ ] Every truth `source_ref` exists in the fixtures or is listed under `withheld_by_variant`
- [ ] Every variant in `variants/` has a truth entry and is listed in `eval-metadata.json`
- [ ] Every timestamp names a declared clock domain
- [ ] Variant descriptions and metadata do not reveal expected answers
- [ ] No `<<FILL` placeholders or `*.TEMPLATE.*` files remain
