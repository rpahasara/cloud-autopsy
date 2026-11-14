// Card, focus and inspector views. Every value shown comes from the run's API responses; text is
// inserted as text nodes only. An abstained outcome is never presented as a cause.

import { fmtDate, fmtDuration, fmtTime, h, hexOf, icon, plural, s, shortDigest, words } from "./dom.js";
import { entityKey, timeScale } from "./model.js";

const STATUS_ICON = { supported: "check", contradicted: "cross", unresolved: "question", not_supported: "blocked" };
const PREREQ_ICON = { satisfied: "check", unsatisfied: "cross", unknown: "question", blocked_by_gap: "blocked" };

const MORE_WORDS = {
  not_supported: "Not supported", limit_reduced: "Limit reduced",
  loaded_by_mounting_pod_after_change: "Loaded by a mounting pod after the change",
  symptom_after_load: "Symptom after load", reference_interval: "reference intervals",
  same_domain: "same clock domain", same_domain_overlap: "overlapping intervals in one clock domain",
  continuity_unknown: "clock continuity unknown", no_mechanism_maps_changed_fields: "No mechanism maps the changed fields",
  no_symptom_on_new_revision: "No symptom on the new revision", change_evidence_may_be_missing: "Change evidence may be missing",
  declared_continuous: "declared continuous", fixture_declared: "declared by fixture", declared: "Declared",
};
export const say = (k) => (Object.prototype.hasOwnProperty.call(MORE_WORDS, k) ? MORE_WORDS[k] : words(k));

const chip = (text, cls) => h("span", { class: ["chip", cls] }, text);
const head = (title, right, sub) => h("header", { class: "card-head" },
  h("div", null, h("h2", { class: "card-title" }, title), sub ? h("p", { class: "card-sub" }, sub) : null), right || null);

function statusPill(status) {
  return h("span", { class: ["status", `st-${status}`] }, icon(STATUS_ICON[status] || "question"), say(status));
}

function evidenceButton(model, id, ctx, label) {
  const ev = model.evidence.get(id);
  return h("button", { type: "button", class: "ev-chip", onclick: (e) => { e.stopPropagation(); ctx.openEvidence(id); },
                       title: id },
    h("span", { class: "ev-dot" }), label || (ev ? `${say(ev.kind)} \u00b7 ${ev.entity ? ev.entity.name : ev.source}` : shortDigest(id, 6)));
}

// ---------------------------------------------------------------- overview cards

export function outcomeCard(model) {
  const o = model.outcome;
  const resolved = model.resolved;
  const badge = model.meta.verified ? chip("Verified", "chip-glass")
    : chip(model.meta.preview ? "Synthetic preview" : "Not verified", "chip-glass chip-warn");
  return h("div", { class: "outcome-body" },
    head("Outcome", badge),
    h("div", { class: "outcome-hero" },
      h("span", { class: "outcome-word" }, resolved ? "Resolved" : "Abstained"),
      h("span", { class: "outcome-of" }, resolved ? "cause supported" : "no cause asserted")),
    h("p", { class: "outcome-line" }, resolved ? say(o.mechanism)
      : (o.reasons.length ? say(o.reasons[0]) : "The engine did not assert a cause")),
    h("dl", { class: "outcome-stats" },
      h("div", null, h("dt", null, "Hypotheses"), h("dd", null, String(model.hypotheses.length))),
      h("div", null, h("dt", null, "Supported"), h("dd", null, String(model.counts.supported))),
      h("div", null, h("dt", null, "Cited evidence"), h("dd", null, String(o.evidence_ids.length)))));
}

export function verifyCard(model, ctx) {
  const m = model.meta;
  const title = m.verified ? "Byte-identical replay" : (m.preview ? "Preview only" : "Not verified");
  const sub = m.verified ? "Re-executed from the sealed run on this request"
    : "Computed in memory from synthetic fixtures \u2014 not from a sealed database run";
  return h("div", { class: "verify-body" },
    head("Verification", chip(m.verified ? "on read" : "preview", m.verified ? "chip-soft" : "chip-soft chip-warn")),
    h("p", { class: "verify-title" }, title),
    h("p", { class: "verify-sub" }, sub),
    h("p", { class: "verify-digest mono", title: m.digest }, `result ${shortDigest(m.digest, 10)}`),
    h("div", { class: "verify-actions" },
      h("button", { type: "button", class: "btn btn-ink", onclick: (e) => { e.stopPropagation(); ctx.go("hypotheses"); } }, "Review hypotheses"),
      h("button", { type: "button", class: "btn btn-soft", onclick: (e) => { e.stopPropagation(); ctx.go("evidence"); } }, "Open evidence")));
}

export function coverageCard(model, ctx) {
  const max = Math.max(1, ...model.sources.map((x) => x.records + x.gaps.length));
  const complete = model.meta.manifestStatus === "complete";
  return h("div", { class: "coverage-body" },
    head("Evidence coverage", h("span", { class: "legend-inline" },
      h("span", { class: "dot dot-ink" }), "cited", h("span", { class: "dot dot-mist" }), "recorded", h("span", { class: "dot dot-gap" }), "gap")),
    h("p", { class: ["manifest", complete ? "is-ok" : "is-warn"] },
      complete ? "Manifest complete" : `Manifest ${say(model.meta.manifestStatus).toLowerCase()} \u00b7 ${model.meta.manifestLimitations.map(say).join(", ")}`),
    // CA-P2-004g: an explicit plan choice, stated as such; coverage of what was collected is in the bars and gaps.
    model.meta.kubernetesEvents === "not_collected"
      ? h("p", { class: ["manifest", "is-warn", "events-scope"] }, "Kubernetes Events: Not collected")
      : model.meta.kubernetesEvents === "collected"
        ? h("p", { class: ["manifest", "events-scope"] }, "Kubernetes Events: Collected") : null,
    h("ul", { class: "bars" }, model.sources.map((src) => h("li", null,
      h("button", { type: "button", class: "bar-row", onclick: (e) => { e.stopPropagation(); ctx.go("evidence", { source: src.id }); } },
        h("span", { class: "bar-label" }, src.id),
        h("span", { class: "bar-track" },
          h("span", { class: "bar-fill bar-recorded", dataset: { w: (src.records / max).toFixed(3) } }),
          h("span", { class: "bar-fill bar-cited", dataset: { w: (src.cited / max).toFixed(3) } }),
          src.gaps.length ? h("span", { class: "bar-gap", dataset: { x: (src.records / max).toFixed(3), w: (src.gaps.length / max).toFixed(3) } }) : null),
        h("span", { class: "bar-value" }, h("span", { class: "muted" }, String(src.records)),
          src.gaps.length ? h("span", { class: "gap-text" }, ` +${src.gaps.length} gap`) : null))))));
}

export function hypsCompact(model) {
  const prereqs = model.hypotheses.flatMap((hyp) => hyp.prerequisites.map((p) => p.result));
  return h("div", { class: "hyps-body" },
    head("Hypotheses", h("span", { class: "card-count" }, `${model.counts.supported} of ${model.hypotheses.length} supported`)),
    h("div", { class: "segments", "aria-label": "Prerequisite results" },
      prereqs.map((r) => h("span", { class: ["seg", `seg-${r}`], title: say(r) }))),
    h("ul", { class: "hyp-list" }, model.hypotheses.map((hyp) => h("li", null,
      h("span", { class: ["hyp-mark", `st-${hyp.status}`] }, icon(STATUS_ICON[hyp.status] || "question")),
      h("span", { class: "hyp-name" }, say(hyp.mechanism)),
      h("span", { class: "hyp-meta" }, hyp.entity ? hyp.entity.name : say(hyp.status))))));
}

function laneTrack(model, entries, lanes, laneOf, { selectable, ctx, selected, compact }) {
  const scale = timeScale(entries, 1000);
  const track = h("div", { class: ["lanes", compact ? "is-compact" : null] });
  if (!scale) {
    track.append(h("p", { class: "empty-note" }, "No entry has a reference time; ordering cannot be shown on a time axis."));
    return track;
  }
  const pct = (x) => `${(x / 10).toFixed(3)}%`;
  for (const br of scale.breaks) {
    const mark = h("div", { class: "lane-break", title: `${fmtDuration(br.skipped)} without entries` },
      h("span", null, `\u2248 ${fmtDuration(br.skipped)}`));
    mark.style.setProperty("--x", (br.x / 1000).toFixed(4));
    track.append(mark);
  }
  lanes.forEach((lane, i) => {
    const row = h("div", { class: "lane" }, compact ? null : h("span", { class: "lane-label", title: lane.title || lane.label },
      lane.kind ? h("small", null, `${lane.kind} `) : null, lane.label));
    const rail = h("div", { class: "lane-rail" });
    for (const e of entries.filter((x) => x.reference_ms && laneOf(x) === lane.key)) {
      const x0 = scale.at(e.reference_ms.lower), x1 = scale.at(e.reference_ms.upper);
      const cited = model.citedBy.has(e.evidence_id) || model.outcomeEvidence.has(e.evidence_id);
      const isChange = model.outcome.change_evidence_id === e.evidence_id;
      const attrs = { class: ["tick", cited ? "is-cited" : null, isChange ? "is-change" : null,
                              selected === e.entry_id ? "is-selected" : null, `k-${e.observation_kind}`],
                      title: `${say(e.observation_kind)} \u00b7 ${e.raw} (${e.clock_domain_id})` };
      const el = selectable
        ? h("button", { ...attrs, type: "button", dataset: { entry: e.entry_id },
                        "aria-label": `${say(e.observation_kind)} on ${e.entity ? e.entity.name : e.source_id} at ${e.raw}`,
                        onclick: (ev) => { ev.stopPropagation(); ctx.selectEntry(e); } })
        : h("span", attrs);
      el.style.left = pct(x0);
      el.style.width = `max(${compact ? 6 : 10}px, ${((x1 - x0) / 10).toFixed(3)}%)`;
      rail.append(el);
    }
    row.append(rail);
    track.append(row);
    if (i === 0) row.classList.add("is-first");
  });
  const axis = h("div", { class: "axis" });
  for (const seg of scale.segs) {
    const a = h("span", { class: "axis-tick" }, fmtTime(seg.a, !compact));
    a.style.left = pct(seg.x0);
    axis.append(a);
  }
  const end = h("span", { class: "axis-tick is-end" }, fmtTime(scale.hi, !compact));
  end.style.left = pct(scale.segs[scale.segs.length - 1].x1);
  axis.append(end);
  track.append(axis);
  return track;
}

export function timelineCompact(model, ctx) {
  const sources = [...new Set(model.entries.map((e) => e.source_id))].sort();
  const placed = model.entries.length - model.unplaceable.length;
  return h("div", { class: "timeline-body" },
    head("Timeline", h("span", { class: "card-count" }, `${model.domains.length} clock domains`),
      model.meta.window ? `Window ${fmtTime(model.meta.window.start, false)}\u2013${fmtTime(model.meta.window.end, false)} UTC \u00b7 ${fmtDate(model.meta.window.start)}` : null),
    h("dl", { class: "kpis" },
      h("div", null, h("dt", null, "Time marks"), h("dd", null, String(model.entries.length))),
      h("div", null, h("dt", null, "Placed"), h("dd", null, String(placed))),
      h("div", null, h("dt", null, "Unordered"), h("dd", { class: model.unordered.length ? "is-amber" : null }, String(model.unordered.length))),
      h("div", null, h("dt", null, "Max clock \u00b1"), h("dd", null, fmtDuration(model.maxUncertainty)))),
    laneTrack(model, model.entries, sources.map((x) => ({ key: x, label: x })), (e) => e.source_id, { compact: true, ctx }));
}

export function evidenceCompact(model) {
  return h("div", { class: "evidence-body" },
    head("Evidence", h("span", { class: "card-count" }, `${model.evidence.size} records`)),
    h("ul", { class: "measure-list" }, model.kinds.map((k) => h("li", null,
      h("span", { class: "measure-label" }, say(k.kind)),
      h("span", { class: "measure-value" }, String(k.records), h("small", null, k.records === 1 ? "record" : "records")),
      h("span", { class: ["delta", k.cited ? "is-cited" : null] }, k.cited ? `${k.cited} cited` : "not cited")))));
}

export function gapsCompact(model) {
  const rows = [
    ["Evidence gaps", model.gaps.length, model.gaps.filter((g) => g.mandatory).length ? `${model.gaps.filter((g) => g.mandatory).length} mandatory` : ""],
    ["Contradictions", model.contradictions.length, ""],
    ["Unordered pairs", model.unordered.length, `of ${model.orderings.length}`],
    ["Unplaced time marks", model.unplaceable.length, `of ${model.entries.length}`],
  ];
  const scaleMax = Math.max(4, ...rows.map((r) => r[1]));
  const note = model.resolved
    ? (model.contradictions.length ? `Supported with ${plural(model.counts.contradicted, "contradicted alternative")} recorded alongside.` : "No limiting gaps or contradictions recorded.")
    : `Abstained: ${model.outcome.reasons.map((r) => say(r).toLowerCase()).join("; ")}.`;
  return h("div", { class: "gaps-body" },
    head("Gaps & uncertainty", h("span", { class: "card-count" }, model.resolved ? "resolved" : "abstained")),
    h("ul", { class: "blocks-list" }, rows.map(([label, n, extra]) => h("li", null,
      h("div", { class: "blocks-head" }, h("span", null, label), h("span", { class: "blocks-n" }, String(n), extra ? h("small", null, ` ${extra}`) : null)),
      h("div", { class: "blocks" }, Array.from({ length: scaleMax }, (_, i) => h("span", { class: i < n ? "on" : null })))))),
    h("div", { class: ["insight", model.resolved ? null : "is-abstained"] },
      h("span", { class: "insight-icon" }, icon(model.resolved ? "shield" : "alert")),
      h("div", null, h("strong", null, model.resolved ? "Basis" : "Why no cause"), h("p", null, note))));
}

// ---------------------------------------------------------------- focus (expanded) views

export function timelineExpanded(model, ctx) {
  const ents = [...model.entities.values()].filter((e) => e.evidence.length).sort((a, b) => a.tier - b.tier || a.name.localeCompare(b.name));
  const lanes = ents.map((e) => ({ key: e.key, label: e.name, kind: e.kind, title: `${e.kind} ${e.namespace}/${e.name}` }));
  const ordered = model.entries.filter((e) => e.reference_ms);
  const relAfter = new Map(model.orderings.map((o) => [o.a, o]));
  const seq = h("ol", { class: "sequence" }, ordered.map((e) => {
    const rel = relAfter.get(e.entry_id);
    return h("li", null,
      h("button", { type: "button", class: ["seq-item", ctx.state.entry === e.entry_id ? "is-selected" : null], dataset: { entry: e.entry_id },
                    onclick: (ev) => { ev.stopPropagation(); ctx.selectEntry(e); } },
        h("span", { class: "seq-time mono" }, e.raw),
        h("span", { class: "seq-what" }, h("span", { class: "seq-kind" }, say(e.observation_kind), h("small", null, ` \u00b7 ${say(e.timestamp_kind)}`)),
          h("span", { class: "seq-entity" }, e.entity ? e.entity.name : e.source_id)),
        h("span", { class: "seq-clock" }, e.clock_domain_id)),
      rel ? h("div", { class: ["seq-rel", rel.order === "before" ? "is-before" : "is-unordered"] },
        rel.order === "before" ? `before \u00b7 ${say(rel.basis)}` : `order unknown \u00b7 ${say(rel.basis)}`) : null);
  }));
  return h("div", { class: "expanded timeline-expanded" },
    head("Timeline", h("span", { class: "card-count" }, `${ordered.length} placed \u00b7 ${model.unplaceable.length} unplaced`),
      "Bars span each mark's reference-time interval; width is clock and precision uncertainty."),
    h("p", { class: "fineprint" }, model.timeline.ordering_note),
    laneTrack(model, model.entries, lanes, (e) => entityKey(e.entity), { selectable: true, ctx, selected: ctx.state.entry }),
    model.unplaceable.length ? h("section", { class: "tray" },
      h("h3", { class: "section-title" }, "Unplaced \u2014 no reference time"),
      h("div", { class: "tray-items" }, model.unplaceable.map((e) => h("button", {
        type: "button", class: "tray-item", onclick: (ev) => { ev.stopPropagation(); ctx.selectEntry(e); } },
        h("span", { class: "mono" }, e.raw), " ", say(e.observation_kind), " \u00b7 ", e.clock_domain_id,
        h("small", null, ` (${say(e.clock_status)}, ${say(e.clock_continuity)})`))))) : null,
    h("div", { class: "split" },
      h("section", null, h("h3", { class: "section-title" }, "Sequence"), seq),
      h("section", null, h("h3", { class: "section-title" }, "Clock domains"),
        h("ul", { class: "domains" }, model.domains.map((d) => h("li", null,
          h("span", { class: "mono" }, d.clock_domain_id),
          h("span", null, d.status === "declared" ? `offset ${d.offset_ms} ms \u00b1 ${d.offset_uncertainty_ms} ms` : say(d.status)),
          h("small", null, `${say(d.continuity)} \u00b7 ${say(d.offset_provenance)}`)))))));
}

function hypothesisCard(model, hyp, ctx) {
  const gapsById = new Map(model.gaps.map((g) => [g.gap_id, g]));
  return h("article", { class: ["hyp-card", `st-${hyp.status}`] },
    h("header", null,
      h("div", null, h("h3", null, say(hyp.mechanism)),
        h("p", { class: "muted" }, hyp.entity ? `${hyp.entity.kind} ${hyp.entity.namespace}/${hyp.entity.name}` : "No entity identified")),
      statusPill(hyp.status)),
    h("ol", { class: "prereqs" }, hyp.prerequisites.map((p) => h("li", { class: `pr-${p.result}` },
      h("span", { class: "pr-mark" }, icon(PREREQ_ICON[p.result] || "question")),
      h("div", { class: "pr-body" },
        h("div", { class: "pr-title" }, say(p.key), h("span", { class: "pr-result" }, say(p.result))),
        p.reason ? h("p", { class: "pr-reason" }, say(p.reason)) : null,
        p.evidence_ids.length || p.gap_ids.length ? h("div", { class: "chips" },
          p.evidence_ids.map((id) => evidenceButton(model, id, ctx)),
          p.gap_ids.map((id) => h("button", { type: "button", class: "ev-chip is-gap", onclick: (e) => { e.stopPropagation(); ctx.openGap(gapsById.get(id)); } },
            h("span", { class: "ev-dot" }), `Gap \u00b7 ${gapsById.get(id) ? gapsById.get(id).query_id : shortDigest(id, 6)}`))) : null,
        p.orderings.length ? h("ul", { class: "orderings" }, p.orderings.map((o) => h("li", null,
          `${say((model.evidence.get(o.a.split("#")[0]) || {}).kind)} ${o.order === "before" ? "before" : "unordered with"} ${say((model.evidence.get(o.b.split("#")[0]) || {}).kind)}`,
          h("small", null, ` \u00b7 ${say(o.basis)}`)))) : null)))),
    hyp.contradictions.length ? h("div", { class: "contradictions" },
      h("h4", null, "Contradictions"),
      hyp.contradictions.map((c) => h("div", { class: "contra" }, h("span", null, say(c.key)),
        h("div", { class: "chips" }, c.evidence_ids.map((id) => evidenceButton(model, id, ctx)))))) : null,
    hyp.limiting_gap_ids.length ? h("p", { class: "fineprint" }, `${plural(hyp.limiting_gap_ids.length, "limiting gap")}`) : null);
}

export function hypsExpanded(model, ctx) {
  return h("div", { class: "expanded hyps-expanded" },
    head("Hypotheses", h("span", { class: "card-count" }, `${model.counts.supported} supported \u00b7 ${model.counts.contradicted} contradicted \u00b7 ${model.counts.unresolved} unresolved \u00b7 ${model.counts.notSupported} not supported`),
      "Each conclusion links to the evidence and gaps it rests on."),
    h("div", { class: "hyp-grid" }, model.hypotheses.map((hyp) => hypothesisCard(model, hyp, ctx))));
}

export function evidenceExpanded(model, ctx) {
  const filter = ctx.state.evidenceFilter || "all";
  const items = [...model.evidence.values()].filter((ev) => filter === "all"
    || (filter === "cited" && model.citedBy.has(ev.id)) || (filter.startsWith("source:") && ev.source === filter.slice(7))
    || (filter.startsWith("kind:") && ev.kind === filter.slice(5)));
  const filters = [["all", "All"], ["cited", "Cited"], ...model.sources.filter((x) => x.records).map((x) => [`source:${x.id}`, x.id])];
  return h("div", { class: "expanded evidence-expanded" },
    head("Evidence", h("span", { class: "card-count" }, `${items.length} of ${model.evidence.size}`), "Sealed members of this run. Select a record to inspect it."),
    h("div", { class: "segmented", role: "tablist" }, filters.map(([key, label]) => h("button", {
      type: "button", role: "tab", class: filter === key ? "is-on" : null, "aria-selected": String(filter === key),
      onclick: (e) => { e.stopPropagation(); ctx.setEvidenceFilter(key); } }, label))),
    h("ul", { class: "ev-table" }, items.map((ev) => {
      const first = ev.entries[0];
      return h("li", null, h("button", { type: "button", class: ["ev-row", ctx.state.evidence === ev.id ? "is-selected" : null],
                                         onclick: (e) => { e.stopPropagation(); ctx.openEvidence(ev.id); } },
        h("span", { class: ["ev-kind", `k-${ev.kind}`] }, say(ev.kind)),
        h("span", { class: "ev-entity" }, ev.entity ? ev.entity.name : "\u2014", h("small", null, ev.entity ? ` ${ev.entity.kind}` : "")),
        h("span", { class: "ev-source mono" }, ev.source),
        h("span", { class: "ev-time mono" }, first ? first.raw : "\u2014"),
        h("span", { class: ["ev-cov", ev.coverage === "verified" ? "is-ok" : "is-warn"] }, say(ev.coverage)),
        h("span", { class: "ev-cited" }, model.citedBy.has(ev.id) ? `${model.citedBy.get(ev.id).length} cited` : "")));
    })));
}

export function gapsExpanded(model, ctx) {
  return h("div", { class: "expanded gaps-expanded" },
    head("Gaps & uncertainty", h("span", { class: "card-count" }, model.resolved ? "resolved" : "abstained"),
      "What the run could not observe or order. None of it is filled in."),
    !model.resolved ? h("div", { class: "insight is-abstained" }, h("span", { class: "insight-icon" }, icon("alert")),
      h("div", null, h("strong", null, "The engine abstained"),
        h("ul", { class: "reasons" }, model.outcome.reasons.map((r) => h("li", null, say(r), h("small", { class: "mono" }, ` ${r}`)))))) : null,
    h("section", null, h("h3", { class: "section-title" }, `Evidence gaps \u00b7 ${model.gaps.length}`),
      model.gaps.length ? h("div", { class: "gap-grid" }, model.gaps.map((g) => h("button", {
        type: "button", class: "gap-card", onclick: (e) => { e.stopPropagation(); ctx.openGap(g); } },
        h("span", { class: "gap-type" }, say(g.gap_type), g.mandatory ? chip("mandatory", "chip-warn") : null),
        h("strong", null, `${g.source_id} \u00b7 ${g.query_id}`),
        h("span", { class: "muted" }, g.reasons.map(say).join(", ")),
        h("small", null, g.interval_ms ? `${fmtTime(g.interval_ms.start)}\u2013${fmtTime(g.interval_ms.end)} UTC` : `subject: ${g.subject}`)))) : h("p", { class: "empty-note" }, "No evidence gaps were recorded for this run.")),
    h("section", null, h("h3", { class: "section-title" }, `Contradictions \u00b7 ${model.contradictions.length}`),
      model.contradictions.length ? model.contradictions.map((c) => h("div", { class: "contra" },
        h("span", null, say(c.key), h("small", { class: "muted" }, ` \u00b7 against ${say((model.hypById.get(c.hypothesisId) || {}).mechanism)}`)),
        h("div", { class: "chips" }, c.evidence_ids.map((id) => evidenceButton(model, id, ctx))))) : h("p", { class: "empty-note" }, "No contradictions recorded.")),
    h("section", null, h("h3", { class: "section-title" }, `Unordered pairs \u00b7 ${model.unordered.length}`),
      model.unordered.length ? h("ul", { class: "unordered" }, model.unordered.map((o) => h("li", null,
        evidenceButton(model, o.a.split("#")[0], ctx), h("span", { class: "approx" }, "\u2248"), evidenceButton(model, o.b.split("#")[0], ctx),
        h("small", { class: "muted" }, say(o.basis))))) : h("p", { class: "empty-note" }, "Every adjacent pair is ordered.")),
    model.unplaceable.length ? h("section", null, h("h3", { class: "section-title" }, `Unplaced time marks \u00b7 ${model.unplaceable.length}`),
      h("p", { class: "fineprint" }, "These marks have no reference time, so they are not positioned on the timeline.")) : null);
}

// ---------------------------------------------------------------- inspector

const kv = (label, value, cls) => h("div", { class: ["kv", cls] }, h("dt", null, label), h("dd", null, value === null || value === undefined || value === "" ? "\u2014" : value));

export function inspectSummary(model, ctx) {
  const o = model.outcome;
  const ents = [...model.entities.values()].sort((a, b) => a.tier - b.tier || a.name.localeCompare(b.name));
  return h("div", { class: "insp-body" },
    h("p", { class: "eyebrow" }, "Investigation"),
    h("h3", { class: "insp-title" }, model.resolved ? say(o.mechanism) : "No cause asserted"),
    h("p", { class: "insp-lead" }, model.resolved
      ? `Supported by ${plural(o.evidence_ids.length, "cited evidence record")}.`
      : `Abstained \u2014 ${o.reasons.map((r) => say(r).toLowerCase()).join("; ")}.`),
    h("dl", { class: "kvs" },
      kv("Status", h("span", { class: ["status", model.resolved ? "st-supported" : "st-abstained"] }, say(o.status))),
      kv("Plan", h("span", { class: "mono" }, model.meta.planId)),
      kv("Namespaces", model.namespaces.join(", ")),
      kv("Result", h("span", { class: "mono", title: model.meta.digest }, shortDigest(model.meta.digest, 10))),
      kv("Data", model.meta.verified ? "Verified on read" : (model.meta.preview ? "Synthetic preview, not verified" : "Not verified"))),
    h("h4", { class: "insp-section" }, "Entities"),
    h("ul", { class: "insp-list" }, ents.map((e) => h("li", null, h("button", { type: "button", class: "insp-row", onclick: () => ctx.select({ entity: e }) },
      h("span", { class: "row-kind" }, e.kind), h("span", { class: "row-name" }, e.name), h("span", { class: "row-n" }, String(e.evidence.length)))))),
    model.gaps.length ? h("h4", { class: "insp-section" }, "Missing evidence") : null,
    model.gaps.length ? h("ul", { class: "insp-list" }, model.gaps.map((g) => h("li", null, h("button", { type: "button", class: "insp-row is-gap", onclick: () => ctx.openGap(g) },
      h("span", { class: "row-kind" }, say(g.gap_type)), h("span", { class: "row-name" }, `${g.source_id} \u00b7 ${g.query_id}`), h("span", { class: "row-n" }, g.subject))))) : null);
}

export function inspectEntity(model, ent, ctx) {
  const hyps = model.hypotheses.filter((hyp) => entityKey(hyp.entity) === ent.key
    || (model.hypCites.get(hyp.hypothesis_id) || []).some((id) => (model.evidence.get(id) || {}).entityKey === ent.key));
  return h("div", { class: "insp-body" },
    h("p", { class: "eyebrow" }, ent.kind),
    h("h3", { class: "insp-title" }, ent.name),
    h("p", { class: "insp-lead mono" }, ent.namespace),
    h("h4", { class: "insp-section" }, `Evidence \u00b7 ${ent.evidence.length}`),
    ent.evidence.length ? h("ul", { class: "insp-list" }, ent.evidence.map((id) => {
      const ev = model.evidence.get(id);
      return h("li", null, h("button", { type: "button", class: "insp-row", onclick: () => ctx.openEvidence(id) },
        h("span", { class: "row-kind" }, say(ev.kind)), h("span", { class: "row-name mono" }, ev.entries[0] ? ev.entries[0].raw : ""),
        h("span", { class: ["row-n", model.citedBy.has(id) ? "is-cited" : null] }, model.citedBy.has(id) ? "cited" : "")));
    })) : h("p", { class: "empty-note" }, "No evidence record names this entity. It appears because a hypothesis names it."),
    h("h4", { class: "insp-section" }, `Hypotheses \u00b7 ${hyps.length}`),
    hyps.length ? h("ul", { class: "insp-list" }, hyps.map((hyp) => h("li", null, h("button", { type: "button", class: "insp-row", onclick: () => ctx.go("hypotheses") },
      h("span", { class: ["row-kind", `st-${hyp.status}`] }, say(hyp.status)), h("span", { class: "row-name" }, say(hyp.mechanism)))))) : h("p", { class: "empty-note" }, "No hypothesis involves this entity."));
}

export function inspectGap(model, gap) {
  const affected = (gap.affects_hypothesis_ids || []).map((id) => model.hypById.get(id)).filter(Boolean);
  return h("div", { class: "insp-body" },
    h("p", { class: "eyebrow" }, "Evidence gap"),
    h("h3", { class: "insp-title" }, `${gap.source_id} \u00b7 ${gap.query_id}`),
    h("p", { class: "insp-lead" }, gap.reasons.map(say).join(", ")),
    h("dl", { class: "kvs" },
      kv("Type", say(gap.gap_type)), kv("Mandatory", gap.mandatory ? "Yes" : "No"), kv("Subject", gap.subject),
      kv("Interval", gap.interval_ms ? `${fmtTime(gap.interval_ms.start)}\u2013${fmtTime(gap.interval_ms.end)} UTC` : "Whole acquisition"),
      kv("Gap ID", h("span", { class: "mono", title: gap.gap_id }, shortDigest(gap.gap_id, 8)))),
    h("h4", { class: "insp-section" }, `Affects \u00b7 ${affected.length}`),
    h("ul", { class: "insp-list" }, affected.map((hyp) => h("li", { class: "insp-row is-static" },
      h("span", { class: ["row-kind", `st-${hyp.status}`] }, say(hyp.status)), h("span", { class: "row-name" }, say(hyp.mechanism))))),
    h("p", { class: "fineprint" }, "Missing evidence is reported as a gap; the engine does not infer what it would have shown."));
}

function valueNode(value) {
  if (value === null || value === undefined) return h("span", { class: "muted" }, "null");
  if (typeof value === "object") {
    return h("dl", { class: "kvs nested" }, Object.entries(value).map(([k, v]) => kv(k, valueNode(v), v && typeof v === "object" ? "is-block" : null)));
  }
  return h("span", { class: "untrusted" }, String(value));
}

export function inspectEvidence(model, envelope, ctx) {
  const d = envelope.data;
  const rec = d.record;
  const attrs = rec.attributes || {};
  const { message, ...rest } = attrs;
  return h("div", { class: "insp-body" },
    h("p", { class: "eyebrow" }, `${rec.evidence_class} \u00b7 ${say(rec.observation_kind)}`),
    h("h3", { class: "insp-title" }, rec.entity ? rec.entity.name : rec.source_id),
    h("p", { class: "insp-lead" }, rec.entity ? `${rec.entity.kind} \u00b7 ${rec.entity.namespace}` : ""),
    h("div", { class: "badges" },
      chip(say(d.coverage), d.coverage === "verified" ? "chip-ok" : "chip-warn"),
      chip(say(rec.origin), "chip-soft"),
      envelope.verified === true ? chip("Served after verification", "chip-ok") : chip("Preview \u2014 not verified", "chip-warn")),
    typeof message === "string" ? h("figure", { class: "source-text" },
      h("figcaption", null, "Source text \u2014 untrusted, shown as plain text"), h("pre", null, message)) : null,
    h("h4", { class: "insp-section" }, "Provenance"),
    h("dl", { class: "kvs" },
      kv("Source", h("span", { class: "mono" }, rec.source_id)), kv("Reference", h("span", { class: "mono untrusted" }, rec.source_ref)),
      kv("Source UID", h("span", { class: "mono" }, rec.source_uid)), kv("Version", h("span", { class: "mono" }, rec.source_version)),
      kv("Cluster", h("span", { class: "mono" }, rec.cluster_id)), kv("Namespace", h("span", { class: "mono" }, rec.namespace))),
    h("h4", { class: "insp-section" }, "Time"),
    h("ul", { class: "times" }, (rec.times || []).map((t) => h("li", null,
      h("span", { class: "mono" }, t.raw), h("span", null, say(t.timestamp_kind)),
      h("small", null, `${t.clock_domain_id} \u00b7 ${say(t.parse_status)} \u00b7 precision ${fmtDuration((t.effective_precision_ns || 0) / 1e6)}`)))),
    Object.keys(rest).length ? h("h4", { class: "insp-section" }, "Record content") : null,
    Object.keys(rest).length ? h("dl", { class: "kvs" }, Object.entries(rest).map(([k, v]) => kv(k, valueNode(v), v && typeof v === "object" ? "is-block" : null))) : null,
    h("h4", { class: "insp-section" }, `Cited by \u00b7 ${d.cited_by_hypothesis_ids.length}`),
    d.cited_by_hypothesis_ids.length ? h("ul", { class: "insp-list" }, d.cited_by_hypothesis_ids.map((id) => {
      const hyp = model.hypById.get(id);
      return h("li", null, h("button", { type: "button", class: "insp-row", onclick: () => ctx.go("hypotheses") },
        h("span", { class: ["row-kind", hyp ? `st-${hyp.status}` : null] }, hyp ? say(hyp.status) : ""), h("span", { class: "row-name" }, hyp ? say(hyp.mechanism) : shortDigest(id, 6))));
    })) : h("p", { class: "empty-note" }, "No hypothesis cites this record."),
    h("h4", { class: "insp-section" }, "Integrity"),
    h("dl", { class: "kvs" },
      kv("Evidence ID", h("span", { class: "mono", title: rec.evidence_id }, shortDigest(rec.evidence_id, 10))),
      kv("Content", h("span", { class: "mono", title: rec.content_digest }, shortDigest(rec.content_digest, 10))),
      kv("Binding", h("span", { class: "mono", title: rec.source_binding_digest }, shortDigest(rec.source_binding_digest, 10))),
      kv("Contract", h("span", { class: "mono" }, rec.contract_version))));
}

export function inspectMessage(kind, title, text) {
  return h("div", { class: ["insp-body", "insp-state", kind] },
    h("span", { class: "state-icon" }, icon(kind === "is-loading" ? "clock" : "alert")),
    h("h3", { class: "insp-title" }, title), h("p", { class: "insp-lead" }, text));
}

export { evidenceButton, hexOf, s };
