// Derives everything the dashboard shows from the API responses of one run. Nothing is added:
// entities, sources and relations come only from the verified (or explicitly preview) result,
// its citations view and evidence records fetched from the API.

const TIER = { Service: 0, Ingress: 0, Pod: 1, ReplicaSet: 1, StatefulSet: 1, DaemonSet: 1, Job: 1,
               Deployment: 2, ConfigMap: 2, Secret: 2 };

export function entityKey(entity) {
  if (!entity || typeof entity !== "object") return null;
  return `${entity.kind}/${entity.namespace}/${entity.name}`;
}

function windowMs(win) {
  const start = win && Date.parse(win.start), end = win && Date.parse(win.end);
  return Number.isFinite(start) && Number.isFinite(end) ? { start, end } : null;
}

export function buildModel(resultEnvelope, citationsEnvelope) {
  const r = resultEnvelope.data;
  const cites = citationsEnvelope ? citationsEnvelope.data : null;
  const entries = r.timeline.entries || [];
  const outcome = r.outcome;
  const hypotheses = r.hypotheses || [];
  const gaps = r.gaps || [];

  const meta = {
    runId: resultEnvelope.run_id,
    digest: resultEnvelope.result_digest,
    verified: resultEnvelope.verified === true,
    preview: resultEnvelope.data_source === "synthetic-preview",
    verification: resultEnvelope.verification,
    apiVersion: resultEnvelope.api_version,
    contract: r.contract_version,
    engine: r.engine_version,
    planId: r.inputs.plan_id,
    registryId: r.inputs.registry_id,
    window: windowMs(r.inputs.window),
    manifestStatus: r.inputs.manifest_status,
    manifestLimitations: r.inputs.manifest_limitations || [],
    evidenceCount: r.inputs.evidence_count,
    unverifiedEvidence: r.inputs.unverified_evidence_ids || [],
    synthesis: r.synthesis,
  };

  // Evidence members as the timeline describes them (one record may have several time marks).
  const evidence = new Map();
  for (const e of entries) {
    let item = evidence.get(e.evidence_id);
    if (!item) {
      item = { id: e.evidence_id, entity: e.entity, entityKey: entityKey(e.entity), source: e.source_id,
               kind: e.observation_kind, coverage: e.evidence_coverage, entries: [] };
      evidence.set(e.evidence_id, item);
    }
    item.entries.push(e);
  }

  // Citations: per hypothesis (from the citations view) and for the outcome.
  const citedBy = new Map();
  const hypCites = new Map();
  for (const hc of (cites && cites.hypotheses) || []) {
    hypCites.set(hc.hypothesis_id, hc.cited_evidence_ids);
    for (const id of hc.cited_evidence_ids) {
      if (!citedBy.has(id)) citedBy.set(id, []);
      citedBy.get(id).push(hc.hypothesis_id);
    }
  }
  const outcomeEvidence = new Set(outcome.evidence_ids || []);

  // Entities observed in evidence, plus entities named by hypotheses (which may have no evidence).
  const entities = new Map();
  const ensure = (entity) => {
    const key = entityKey(entity);
    if (!key) return null;
    if (!entities.has(key)) entities.set(key, { key, kind: entity.kind, name: entity.name, namespace: entity.namespace,
                                                tier: TIER[entity.kind] ?? 1, evidence: [], hypotheses: [] });
    return entities.get(key);
  };
  for (const item of evidence.values()) {
    const ent = ensure(item.entity);
    if (ent) ent.evidence.push(item.id);
  }
  const hypById = new Map();
  for (const hyp of hypotheses) {
    hypById.set(hyp.hypothesis_id, hyp);
    const ent = ensure(hyp.entity);
    if (ent) ent.hypotheses.push(hyp.hypothesis_id);
  }

  // Relations a hypothesis tested: its entity to the entities of the evidence it cites.
  const relations = [];
  for (const hyp of hypotheses) {
    const from = entityKey(hyp.entity);
    if (!from) continue;
    const targets = new Set();
    for (const id of hypCites.get(hyp.hypothesis_id) || []) {
      const ev = evidence.get(id);
      if (ev && ev.entityKey && ev.entityKey !== from) targets.add(ev.entityKey);
    }
    for (const to of targets) relations.push({ from, to, hypothesisId: hyp.hypothesis_id, status: hyp.status,
                                               mechanism: hyp.mechanism });
  }

  // Sources: records per source, and gaps per source.
  const sources = new Map();
  const src = (id) => {
    if (!sources.has(id)) sources.set(id, { id, records: 0, cited: 0, gaps: [] });
    return sources.get(id);
  };
  for (const item of evidence.values()) {
    const s = src(item.source);
    s.records += 1;
    if (citedBy.has(item.id) || outcomeEvidence.has(item.id)) s.cited += 1;
  }
  for (const gap of gaps) if (gap.source_id) src(gap.source_id).gaps.push(gap);

  // Evidence classes (by observation kind) with cited counts.
  const kinds = new Map();
  for (const item of evidence.values()) {
    const k = kinds.get(item.kind) || { kind: item.kind, records: 0, cited: 0 };
    k.records += 1;
    if (citedBy.has(item.id)) k.cited += 1;
    kinds.set(item.kind, k);
  }

  const orderings = r.timeline.adjacent_orderings || [];
  const unordered = orderings.filter((o) => o.order !== "before");
  const contradictions = hypotheses.flatMap((h) => h.contradictions.map((c) => ({ ...c, hypothesisId: h.hypothesis_id })));
  const domains = r.inputs.clock_domains || [];
  const maxUncertainty = domains.reduce((m, d) => Math.max(m, Number(d.offset_uncertainty_ms) || 0), 0);
  const unplaceable = entries.filter((e) => !e.reference_ms);

  const statusCount = (st) => hypotheses.filter((h) => h.status === st).length;
  return {
    meta, outcome, hypotheses, hypById, gaps, timeline: r.timeline, entries, evidence, entities, relations,
    sources: [...sources.values()].sort((a, b) => a.id.localeCompare(b.id)),
    kinds: [...kinds.values()].sort((a, b) => b.records - a.records || a.kind.localeCompare(b.kind)),
    citedBy, hypCites, outcomeEvidence, orderings, unordered, contradictions, domains, maxUncertainty, unplaceable,
    counts: { supported: statusCount("supported"), contradicted: statusCount("contradicted"),
              unresolved: statusCount("unresolved"), notSupported: statusCount("not_supported") },
    namespaces: [...new Set([...entities.values()].map((e) => e.namespace).filter(Boolean))].sort(),
    resolved: outcome.status === "resolved",
  };
}

// A time scale over the placeable entries that compresses long empty stretches into a marked
// break, so dense periods stay readable without hiding that time was skipped.
export function timeScale(entries, width, { pad = 0.06, breakRatio = 0.22, breakPx = 26 } = {}) {
  const spans = entries.filter((e) => e.reference_ms).map((e) => [e.reference_ms.lower, e.reference_ms.upper])
    .sort((a, b) => a[0] - b[0]);
  if (!spans.length) return null;
  const lo = spans[0][0], hi = Math.max(...spans.map((s) => s[1]));
  const total = Math.max(hi - lo, 1);
  const clusters = [];
  for (const [a, b] of spans) {
    const last = clusters[clusters.length - 1];
    if (last && a - last[1] <= total * breakRatio) last[1] = Math.max(last[1], b);
    else clusters.push([a, b]);
  }
  const breaks = clusters.length - 1;
  const usable = width * (1 - 2 * pad) - breaks * breakPx;
  const covered = clusters.reduce((sum, [a, b]) => sum + Math.max(b - a, total * 0.02), 0);
  let x = width * pad;
  const segs = clusters.map(([a, b]) => {
    const span = Math.max(b - a, total * 0.02);
    const w = (usable * span) / covered;
    const seg = { a, b: a + span, x0: x, x1: x + w };
    x += w + breakPx;
    return seg;
  });
  const at = (ms) => {
    for (const seg of segs) if (ms <= seg.b) return seg.x0 + ((Math.max(ms, seg.a) - seg.a) / (seg.b - seg.a)) * (seg.x1 - seg.x0);
    return segs[segs.length - 1].x1;
  };
  const gapsBetween = segs.slice(1).map((seg, i) => ({ x: (segs[i].x1 + seg.x0) / 2, skipped: seg.a - segs[i].b }));
  return { at, segs, breaks: gapsBetween, lo, hi };
}
