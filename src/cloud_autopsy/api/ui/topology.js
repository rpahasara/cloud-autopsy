// The investigation's evidence map: an isometric, layered view of the entities that appear in the
// run's evidence. Three tiers (services, workloads, changes and configuration). A line between two
// entities is drawn only where a hypothesis tested that relation, styled by the hypothesis's
// verified status; it is never an observed dependency. A source the plan needed but could not
// read appears as a hollow "missing" node. Nothing is drawn for decoration alone.

import { h, s, words } from "./dom.js";
import { entityKey } from "./model.js";

const VB = { x: 104, y: 14, w: 432, h: 492 };
const CX = 320;
const TIER_Y = [140, 264, 388];
const A = 92;            // plate half-height; half-width is 2A
const CUBE = 30, CUBE_H = 25;
const TIER_LABEL = ["Services", "Workloads", "Changes & configuration"];

const STATUS_CLASS = { supported: "rel-supported", contradicted: "rel-contradicted", unresolved: "rel-unresolved",
                       not_supported: "rel-not-supported" };

function plate(ty) {
  const pts = [[CX - 2 * A, ty], [CX, ty - A], [CX + 2 * A, ty], [CX, ty + A]];
  return pts.map((p) => p.join(",")).join(" ");
}

function point(tier, u, v) {
  return [CX + (u - v) * A, TIER_Y[tier] + ((u + v) * A) / 2];
}

function cube(x, y, cls) {
  const top = y - CUBE_H;
  const face = (pts, c) => s("polygon", { points: pts.map((p) => p.join(",")).join(" "), class: c });
  return s("g", { class: cls },
    s("ellipse", { cx: x, cy: y + CUBE / 2 + 4, rx: CUBE * 1.55, ry: CUBE * 0.62, class: "node-shadow" }),
    face([[x - CUBE, top], [x, top + CUBE / 2], [x, top + CUBE / 2 + CUBE_H], [x - CUBE, top + CUBE_H]], "face-left"),
    face([[x, top + CUBE / 2], [x + CUBE, top], [x + CUBE, top + CUBE_H], [x, top + CUBE / 2 + CUBE_H]], "face-right"),
    face([[x - CUBE, top], [x, top - CUBE / 2], [x + CUBE, top], [x, top + CUBE / 2]], "face-top"),
    s("path", { d: `M${x - CUBE * 0.55} ${top - 1}L${x} ${top - CUBE * 0.28}`, class: "face-gloss" }));
}

function layout(model) {
  const nodes = [];
  const byTier = [[], [], []];
  for (const ent of model.entities.values()) byTier[Math.min(2, Math.max(0, ent.tier))].push({ type: "entity", ent });
  // Missing sources: one hollow node per (source, query) the plan needed and could not read.
  const missing = new Map();
  for (const gap of model.gaps) {
    const key = `gap:${gap.source_id}/${gap.query_id}`;
    if (!missing.has(key)) missing.set(key, { type: "gap", key, source: gap.source_id, query: gap.query_id, gaps: [] });
    missing.get(key).gaps.push(gap);
  }
  for (const m of missing.values()) byTier[2].push(m);
  byTier.forEach((list, tier) => {
    list.sort((a, b) => (a.ent ? a.ent.key : a.key).localeCompare(b.ent ? b.ent.key : b.key));
    const n = list.length;
    list.forEach((item, i) => {
      const t = n === 1 ? 0 : -0.62 + (1.24 * i) / (n - 1);
      const [x, y] = point(tier, t * 0.92, -t * 0.5 + (tier === 1 ? 0.08 : 0));
      nodes.push({ ...item, tier, x, y, key: item.ent ? item.ent.key : item.key });
    });
  });
  return nodes;
}

function label(node, max) {
  if (node.type === "gap") return max < 20 ? "missing" : `${node.query} \u00b7 missing`;
  const name = node.ent.name;
  return name.length > max ? `\u2026${name.slice(-(max - 1))}` : name;
}

export function renderTopology(model, { onSelect }) {
  const nodes = layout(model);
  const nodeByKey = new Map(nodes.map((n) => [n.key, n]));
  const cited = new Set();
  for (const id of model.outcomeEvidence) { const ev = model.evidence.get(id); if (ev) cited.add(ev.entityKey); }
  if (!cited.size) for (const id of model.citedBy.keys()) { const ev = model.evidence.get(id); if (ev) cited.add(ev.entityKey); }
  const supportedKeys = new Set();
  for (const rel of model.relations) if (rel.status === "supported") { supportedKeys.add(rel.from); supportedKeys.add(rel.to); }

  const defs = s("defs", null,
    s("linearGradient", { id: "ca-top", x1: 0, y1: 0, x2: 1, y2: 1 },
      s("stop", { offset: "0", "stop-color": "#ffffff" }), s("stop", { offset: "1", "stop-color": "#eceae4" })),
    s("linearGradient", { id: "ca-top-sage", x1: 0, y1: 0, x2: 1, y2: 1 },
      s("stop", { offset: "0", "stop-color": "#c9d6b8" }), s("stop", { offset: "1", "stop-color": "#8fa77c" })),
    s("linearGradient", { id: "ca-left", x1: 0, y1: 0, x2: 0, y2: 1 },
      s("stop", { offset: "0", "stop-color": "#e7e5df" }), s("stop", { offset: "1", "stop-color": "#d9d6ce" })),
    s("linearGradient", { id: "ca-right", x1: 0, y1: 0, x2: 0, y2: 1 },
      s("stop", { offset: "0", "stop-color": "#d3d0c7" }), s("stop", { offset: "1", "stop-color": "#c4c0b6" })),
    s("linearGradient", { id: "ca-plate", x1: 0, y1: 0, x2: 1, y2: 1 },
      s("stop", { offset: "0", "stop-color": "#ffffff", "stop-opacity": "0.92" }),
      s("stop", { offset: "1", "stop-color": "#f1efe9", "stop-opacity": "0.55" })),
    s("radialGradient", { id: "ca-glow-sage" },
      s("stop", { offset: "0", "stop-color": "#c8d6a8", "stop-opacity": "0.85" }),
      s("stop", { offset: "1", "stop-color": "#c8d6a8", "stop-opacity": "0" })),
    s("radialGradient", { id: "ca-glow-sand" },
      s("stop", { offset: "0", "stop-color": "#efe2b3", "stop-opacity": "0.8" }),
      s("stop", { offset: "1", "stop-color": "#efe2b3", "stop-opacity": "0" })),
    s("radialGradient", { id: "ca-plate-shadow" },
      s("stop", { offset: "0", "stop-color": "#5a5440", "stop-opacity": "0.16" }),
      s("stop", { offset: "0.7", "stop-color": "#5a5440", "stop-opacity": "0.05" }),
      s("stop", { offset: "1", "stop-color": "#5a5440", "stop-opacity": "0" })),
    s("radialGradient", { id: "ca-shadow" },
      s("stop", { offset: "0", "stop-color": "#4b4636", "stop-opacity": "0.22" }),
      s("stop", { offset: "1", "stop-color": "#4b4636", "stop-opacity": "0" })));

  // Soft light behind what matters: the supported path (sage), or the missing evidence (sand).
  const focusNodes = supportedKeys.size ? [...supportedKeys].map((k) => nodeByKey.get(k)).filter(Boolean)
    : nodes.filter((n) => n.type === "gap");
  const glowAt = focusNodes.length ? focusNodes : nodes;
  const gx = glowAt.reduce((t, n) => t + n.x, 0) / Math.max(1, glowAt.length);
  const gy = glowAt.reduce((t, n) => t + n.y, 0) / Math.max(1, glowAt.length);
  const glow = s("ellipse", { cx: gx, cy: gy, rx: 230, ry: 190, class: "glow",
                              fill: supportedKeys.size ? "url(#ca-glow-sage)" : "url(#ca-glow-sand)" });

  const plates = TIER_Y.map((ty, i) => s("g", { class: "plate" },
    s("ellipse", { cx: CX, cy: ty + 22, rx: 2 * A + 10, ry: A * 0.78, class: "plate-shadow" }),
    s("polygon", { points: plate(ty + 7), class: "plate-edge" }),
    s("polygon", { points: plate(ty), class: "plate-top" }),
    s("text", { x: CX - 2 * A + 30, y: ty + 4, class: "plate-label", transform: `rotate(26.565 ${CX - 2 * A + 30} ${ty + 4})` }, TIER_LABEL[i])));

  const relations = model.relations.map((rel) => {
    const a = nodeByKey.get(rel.from), b = nodeByKey.get(rel.to);
    if (!a || !b) return null;
    const y1 = a.y - CUBE_H, y2 = b.y - CUBE_H;
    const my = (y1 + y2) / 2;
    return s("path", { d: `M${a.x} ${y1}C${a.x} ${my},${b.x} ${my},${b.x} ${y2}`,
                       class: ["rel", STATUS_CLASS[rel.status] || "rel-unresolved"],
                       dataset: { from: rel.from, to: rel.to, hyp: rel.hypothesisId } });
  });

  const nodeEls = new Map();
  const cubes = nodes.slice().sort((p, q) => p.y - q.y).map((n) => {
    const g = cube(n.x, n.y, ["node", n.type === "gap" ? "is-ghost" : null, cited.has(n.key) ? "is-cited" : null,
                              supportedKeys.has(n.key) ? "is-supported" : null]);
    g.dataset.key = n.key;
    nodeEls.set(n.key, g);
    return g;
  });

  const svg = s("svg", { viewBox: `${VB.x} ${VB.y} ${VB.w} ${VB.h}`, class: "topology-svg", role: "img",
                         "aria-label": `Evidence map: ${model.entities.size} entities across ${model.sources.length} sources` },
    defs, glow, plates, s("g", { class: "rels" }, relations), s("g", { class: "nodes" }, cubes));

  const markerEls = new Map();
  const markers = h("div", { class: "markers" }, nodes.map((n) => {
    const count = n.type === "gap" ? n.gaps.length : n.ent.evidence.length;
    const btn = h("button", { class: ["marker", n.type === "gap" ? "is-ghost" : null, cited.has(n.key) ? "is-cited" : null],
                              type: "button", dataset: { key: n.key },
                              "aria-label": n.type === "gap" ? `Missing source ${n.source} ${n.query}`
                                : `${n.ent.kind} ${n.ent.name}, ${count} evidence records`,
                              onclick: (ev) => { ev.stopPropagation(); onSelect(n.type === "gap" ? { gap: n } : { entity: n.ent }); },
                              onpointerenter: () => highlight(n.key), onpointerleave: () => highlight(null),
                              onfocus: () => highlight(n.key), onblur: () => highlight(null) },
      h("span", { class: "marker-count" }, n.type === "gap" ? "!" : String(count)),
      h("span", { class: "marker-text" }, h("span", { class: "marker-kind" }, n.type === "gap" ? n.source : n.ent.kind),
        h("span", { class: "marker-full" }, label(n, 30)), h("span", { class: "marker-short" }, label(n, 13))));
    markerEls.set(n.key, btn);
    return btn;
  }));

  const legend = h("div", { class: "topology-legend", "aria-label": "Legend" },
    h("span", { class: "lg lg-supported" }, "Tested by a supported hypothesis"),
    h("span", { class: "lg lg-contradicted" }, "Contradicted"),
    h("span", { class: "lg lg-unresolved" }, "Unresolved or not supported"),
    h("span", { class: "lg lg-ghost" }, "Missing source"),
    h("span", { class: "lg-note" }, "Lines are relations a hypothesis tested, not observed dependencies."));

  const root = h("div", { class: "topology" }, svg, markers, legend);

  function place() {
    const box = svg.getBoundingClientRect();
    const host = root.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const k = Math.min(box.width / VB.w, box.height / VB.h);
    const ox = box.left - host.left + (box.width - VB.w * k) / 2 - VB.x * k;
    const oy = box.top - host.top + (box.height - VB.h * k) / 2 - VB.y * k;
    for (const n of nodes) {
      const el = markerEls.get(n.key);
      const left = n.x < CX - 1;
      const x = ox + (left ? n.x - CUBE - 8 : n.x + CUBE + 8) * k, y = oy + (n.y - CUBE_H - CUBE * 0.1) * k;
      el.dataset.side = left ? "left" : "right";
      const w = el.offsetWidth, hostW = host.width;
      const x0 = Math.max(8, Math.min(hostW - w - 8, left ? x - w : x));
      el.style.transform = `translate3d(${x0.toFixed(1)}px, ${y.toFixed(1)}px, 0) translateY(-50%)`;
    }
  }
  const ro = new ResizeObserver(() => place());
  ro.observe(svg);

  function highlight(key) {
    root.classList.toggle("has-hover", Boolean(key));
    for (const [k, el] of nodeEls) el.classList.toggle("is-hover", k === key);
    for (const rel of relations) if (rel) rel.classList.toggle("is-hover", Boolean(key) && (rel.dataset.from === key || rel.dataset.to === key));
  }

  function setSelection(key) {
    root.classList.toggle("has-selection", Boolean(key));
    for (const [k, el] of nodeEls) el.classList.toggle("is-selected", k === key);
    for (const [k, el] of markerEls) { el.classList.toggle("is-selected", k === key); el.setAttribute("aria-pressed", String(k === key)); }
    for (const rel of relations) if (rel) rel.classList.toggle("is-active", Boolean(key) && (rel.dataset.from === key || rel.dataset.to === key));
  }

  function setFilter(filter) {
    for (const n of nodes) {
      const keep = filter === "all" || (filter === "cited" && cited.has(n.key)) || (filter === "gaps" && n.type === "gap");
      nodeEls.get(n.key).classList.toggle("is-dim", !keep);
      markerEls.get(n.key).classList.toggle("is-dim", !keep);
    }
    for (const rel of relations) if (rel) rel.classList.toggle("is-dim", filter === "gaps");
  }

  return { root, place, setSelection, setFilter, destroy: () => ro.disconnect(), counts: { cited: cited.size, missing: nodes.filter((n) => n.type === "gap").length } };
}

export { entityKey, words };
