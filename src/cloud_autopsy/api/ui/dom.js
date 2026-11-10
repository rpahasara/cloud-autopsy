// DOM construction without HTML strings. Every value, including untrusted evidence text, becomes
// a text node or an attribute value; the page's CSP also enforces Trusted Types, so no string can
// reach an HTML sink.

const SVG_NS = "http://www.w3.org/2000/svg";

function apply(el, attrs) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.setAttribute("class", Array.isArray(value) ? value.filter(Boolean).join(" ") : value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "text") el.textContent = String(value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

export function replace(el, ...children) {
  clear(el);
  append(el, children);
  return el;
}

// Small line icons (24px grid, 1.6 stroke), drawn as SVG elements.
const ICONS = {
  grid: [["rect", { x: 4, y: 4, width: 6.5, height: 6.5, rx: 2 }], ["rect", { x: 13.5, y: 4, width: 6.5, height: 6.5, rx: 2 }],
         ["rect", { x: 4, y: 13.5, width: 6.5, height: 6.5, rx: 2 }], ["rect", { x: 13.5, y: 13.5, width: 6.5, height: 6.5, rx: 2 }]],
  runs: [["path", { d: "M5 7h14M5 12h14M5 17h9" }]],
  refresh: [["path", { d: "M19 12a7 7 0 1 1-2.05-4.95" }], ["path", { d: "M19 4.5V8h-3.5" }]],
  lock: [["rect", { x: 5.5, y: 10.5, width: 13, height: 9, rx: 2.5 }], ["path", { d: "M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" }]],
  close: [["path", { d: "M7 7l10 10M17 7L7 17" }]],
  back: [["path", { d: "M14.5 6.5L9 12l5.5 5.5" }]],
  check: [["path", { d: "M6.5 12.5l3.5 3.5 7.5-8" }]],
  cross: [["path", { d: "M8 8l8 8M16 8l-8 8" }]],
  question: [["path", { d: "M9.5 9.5a2.6 2.6 0 1 1 3.7 2.4c-.8.4-1.2 1-1.2 1.8v.6" }], ["circle", { cx: 12, cy: 17.4, r: 0.6 }]],
  blocked: [["circle", { cx: 12, cy: 12, r: 6.5 }], ["path", { d: "M7.5 16.5l9-9" }]],
  shield: [["path", { d: "M12 4l6.5 2.5v5c0 4-2.8 6.8-6.5 8.5-3.7-1.7-6.5-4.5-6.5-8.5v-5z" }], ["path", { d: "M9 12l2.2 2.2L15.5 10" }]],
  flask: [["path", { d: "M10 4.5h4M10.5 4.5v5L6 17.5a1.6 1.6 0 0 0 1.4 2.4h9.2a1.6 1.6 0 0 0 1.4-2.4L13.5 9.5v-5" }]],
  alert: [["path", { d: "M12 5l7.5 13h-15z" }], ["path", { d: "M12 10.5v3.2" }], ["circle", { cx: 12, cy: 16, r: 0.5 }]],
  plug: [["path", { d: "M9 4v4M15 4v4M7 8h10v3a5 5 0 0 1-10 0zM12 16v4" }]],
  clock: [["circle", { cx: 12, cy: 12, r: 7.5 }], ["path", { d: "M12 8v4.3l2.8 1.7" }]],
  doc: [["path", { d: "M7 4.5h7l4 4V19a.5.5 0 0 1-.5.5h-10.5a.5.5 0 0 1-.5-.5V5a.5.5 0 0 1 .5-.5z" }], ["path", { d: "M9.5 12.5h5M9.5 15.5h5" }]],
  keyboard: [["rect", { x: 3.5, y: 7, width: 17, height: 10, rx: 2.5 }], ["path", { d: "M7 10.5h.01M10 10.5h.01M13 10.5h.01M16 10.5h.01M8.5 13.5h7" }]],
};

export function icon(name, extra) {
  const parts = (ICONS[name] || []).map(([tag, attrs]) => s(tag, attrs));
  return s("svg", { viewBox: "0 0 24 24", class: ["icon", extra], "aria-hidden": "true", focusable: "false" }, parts);
}

// ---- formatting (all output is plain text) ----

export function shortDigest(value, n = 8) {
  if (typeof value !== "string") return "\u2014";
  const tail = value.includes(":") ? value.slice(value.lastIndexOf(":") + 1) : value;
  return tail.length > n * 2 ? `${tail.slice(0, n)}\u2026${tail.slice(-4)}` : tail;
}

export function hexOf(evidenceId) {
  return typeof evidenceId === "string" ? evidenceId.slice(evidenceId.lastIndexOf(":") + 1).split("#")[0] : "";
}

export function shortRun(runId) {
  return typeof runId === "string" ? runId.slice(0, 8) : "";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtTime(ms, withSeconds = true) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "\u2014";
  const d = new Date(ms);
  const p = (x) => String(x).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}${withSeconds ? ":" + p(d.getUTCSeconds()) : ""}`;
}

export function fmtDate(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "\u2014";
  const d = new Date(ms);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function fmtDuration(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "\u2014";
  const a = Math.abs(ms);
  if (a < 1000) return `${Math.round(a)} ms`;
  if (a < 60_000) return `${(a / 1000).toFixed(a < 10_000 ? 1 : 0)} s`;
  if (a < 3_600_000) return `${Math.round(a / 60_000)} min`;
  const hrs = Math.floor(a / 3_600_000), mins = Math.round((a % 3_600_000) / 60_000);
  return mins ? `${hrs} h ${mins} min` : `${hrs} h`;
}

const WORDS = {
  // mechanisms
  config_limit_reduction: "Config limit reduction",
  rollout_limit_reduction: "Rollout limit reduction",
  // statuses
  supported: "Supported", contradicted: "Contradicted", unresolved: "Unresolved", blocked: "Blocked by gaps",
  resolved: "Resolved", abstained: "Abstained",
  satisfied: "Satisfied", unsatisfied: "Not satisfied", unknown: "Unknown", blocked_by_gap: "Blocked by a gap",
  // outcome reasons
  contradicting_evidence_present: "Contradicting evidence is present",
  limiting_evidence_gaps: "Evidence gaps limit the analysis",
  no_supported_hypothesis: "No hypothesis is supported",
  unresolved_hypotheses_present: "Some hypotheses remain unresolved",
  ordering_unknown: "Event ordering cannot be established",
  no_symptom_observed: "No symptom was observed",
  // prerequisites
  rollout_observed: "Rollout observed", change_observed: "Change observed",
  changed_field_lowers_mapped_limit: "Changed field lowers a mapped limit",
  symptom_on_new_revision_after_rollout: "Symptom on new revision after rollout",
  symptom_precedes_rollout: "Symptom precedes the rollout",
  // gaps
  source_unavailable: "Source unavailable", failed: "Acquisition failed",
  mandatory_acquisition_incomplete: "Mandatory acquisition incomplete",
  // orderings
  before: "before", after: "after", unordered: "unordered",
};

export function words(key) {
  if (key === null || key === undefined) return "\u2014";
  if (Object.prototype.hasOwnProperty.call(WORDS, key)) return WORDS[key];
  const text = String(key).replace(/[_.-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "\u2014";
}

export function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many || one + "s"}`;
}
