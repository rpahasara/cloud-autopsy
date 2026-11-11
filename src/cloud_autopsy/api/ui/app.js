// Cloud Autopsy dashboard: a read-only client of the local investigation API on this origin.
//
// - The bearer token lives only in this module's memory: never in storage, cookies or a URL.
// - Every finding shown comes from /v1 responses. If the API refuses or a result fails
//   verification, the run shows that state and nothing from the result.
// - Requests are paced to the API's concurrency gate (at most 2 in flight here); a 503
//   "overloaded" is retried after its Retry-After, then shown.

import { clear, fmtDate, fmtTime, h, hexOf, icon, plural, replace, shortDigest, shortRun } from "./dom.js";
import { createHome } from "./home.js";
import { animate, cancelAll, finished, prefersReducedMotion, rectIn } from "./motion.js";
import { buildModel } from "./model.js";
import { renderTopology } from "./topology.js";
import * as V from "./views.js";

const TOKEN_RE = /^[A-Za-z0-9_-]{43,128}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const FOCUS = { overview: null, investigation: "hero", timeline: "timeline", hypotheses: "hyps", evidence: "evidence", gaps: "gaps" };
const VIEW_OF = Object.fromEntries(Object.entries(FOCUS).filter(([, c]) => c).map(([v, c]) => [c, v]));
const CARD_IDS = ["hero", "outcome", "verify", "coverage", "hyps", "timeline", "evidence", "gaps"];
const EXPANDABLE = new Set(["hero", "hyps", "timeline", "evidence", "gaps"]);

const ERRORS = {
  invalid_token: ["Token not accepted", "The API did not accept this token, so it was cleared from memory. Enter it again to continue."],
  run_not_authorized: ["Run not granted", "This token's grant does not name this run. Grants list runs explicitly; ask for a token that covers it."],
  run_not_found: ["No stored result", "The API has no sealed, stored result for this run ID."],
  result_unverifiable: ["Result failed verification", "The stored result did not verify against its sealed run, so nothing from it is shown."],
  overloaded: ["The API is busy", "The API is at its concurrency limit and refused this request after several paced retries."],
  database_unavailable: ["Database unavailable", "The API is running but could not reach its database."],
  disconnected: ["API unreachable", "This page cannot reach the API on its own origin. Check that the local server is still running."],
  inconsistent: ["Result changed between requests", "Two responses for this run carried different result digests. Nothing is shown; reload to verify again."],
  invalid_run_id: ["Invalid run ID", "Run IDs are lowercase UUIDs."],
};

let token = null;
const state = {
  runs: [], active: null, model: null, view: "overview", entry: null, evidence: null, evidenceFilter: "all", filter: "all",
  topo: null, stack: [], current: null, evidenceCache: new Map(), transition: 0,
};

const $ = (sel) => document.querySelector(sel);
const app = $("#app"), stage = $("#stage"), inspector = $("#inspector"), inspBody = $("#insp-content"), homeEl = $("#home");
const RUN_VIEWS = new Set(["overview", "investigation", "timeline", "hypotheses", "evidence", "gaps"]);
const cards = Object.fromEntries(CARD_IDS.map((id) => [id, stage.querySelector(`[data-card="${id}"]`)]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ API client

let inFlight = 0;
const waiting = [];
function queued(fn) {
  return new Promise((resolve) => {
    const run = async () => {
      inFlight += 1;
      try { resolve(await fn()); } finally { inFlight -= 1; const next = waiting.shift(); if (next) next(); }
    };
    if (inFlight < 2) run(); else waiting.push(run);
  });
}

async function request(path, attempt = 0) {
  if (!token) return { status: 401, body: { error: "invalid_token" } };
  let res;
  try {
    res = await fetch(path, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", credentials: "omit",
                              redirect: "error", referrerPolicy: "no-referrer", mode: "same-origin" });
  } catch {
    return { status: 0, body: { error: "disconnected" } };
  }
  let body;
  try { body = await res.json(); } catch { body = { error: "unreadable_response" }; }
  if (res.status === 503 && body && body.error === "overloaded" && attempt < 4) {
    toast("API busy \u2014 retrying", "is-amber");
    const wait = (Number(res.headers.get("Retry-After")) || 1) * 1000 + 180 * (attempt + 1);
    await sleep(wait);
    return request(path, attempt + 1);
  }
  if (!body || typeof body !== "object") body = { error: "unreadable_response" };
  return { status: res.status, body };
}

const api = (path) => queued(() => request(path));

function failure(response) {
  const code = (response.body && response.body.error) || `http_${response.status}`;
  return { code, reason: response.body && response.body.reason, status: response.status };
}

async function loadRun(run, { full }) {
  run.status = "loading";
  renderRunList();
  const result = await api(`/v1/runs/${run.id}/result`);
  if (result.status !== 200 || !result.body.data) return fail(run, failure(result));
  let citations = null;
  if (full) {
    citations = await api(`/v1/runs/${run.id}/citations`);
    if (citations.status !== 200) return fail(run, failure(citations));
    if (citations.body.result_digest !== result.body.result_digest) return fail(run, { code: "inconsistent" });
  }
  run.status = "ready";
  run.result = result.body;
  run.citations = citations ? citations.body : run.citations;
  run.error = null;
  renderRunList();
  return run;
}

function fail(run, error) {
  run.status = "error";
  run.error = error;
  run.result = null;
  run.citations = null;
  renderRunList();
  if (error.code === "invalid_token") signOut("The API did not accept the token. It has been cleared from memory.");
  return run;
}

// ------------------------------------------------------------------ connect / sign-out

const form = $("#connect-form"), tokenInput = $("#token"), runsInput = $("#run-ids"), connectError = $("#connect-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const candidate = tokenInput.value.trim();
  const ids = [...new Set(runsInput.value.toLowerCase().split(/[\s,]+/).filter(Boolean))];
  if (!TOKEN_RE.test(candidate)) return showConnectError("That does not look like an API token (43\u2013128 URL-safe characters).");
  const bad = ids.filter((id) => !UUID_RE.test(id));
  if (bad.length) return showConnectError(`Not a run ID: ${bad[0].slice(0, 40)}`);
  if (ids.length > 50) return showConnectError("At most 50 run IDs at a time.");
  token = candidate;
  tokenInput.value = "";
  showConnectError("");
  state.runs = ids.map((id) => ({ id, status: "pending" }));
  state.evidenceCache.clear();
  home.reset();
  app.dataset.state = "loading";
  hideSheet();
  if (!ids.length) {
    // No run named: open Home, which lists and verifies the token's own runs page by page.
    setPage("home");
    app.dataset.state = "ready";
    state.view = "home";
    syncNav("home");
    home.render();
    home.enter();
    await home.load();
    return;
  }
  setPage("run");
  await selectRun(state.runs[0].id, { first: true });
  // The other named runs for the switcher, paced through the queue; then the Home overview.
  for (const id of ids.slice(1)) {
    const run = state.runs.find((r) => r.id === id);
    if (token && run && run.status === "pending") await loadRun(run, { full: false });
  }
  if (token) home.load();
});

function showConnectError(text) {
  connectError.textContent = text;
  connectError.hidden = !text;
  if (text) animate(connectError, [{ transform: "translateX(-6px)" }, { transform: "translateX(5px)" }, { transform: "none" }], { spring: "micro" });
}

function hideSheet() {
  const sheet = $("#connect");
  const a = animate(sheet.querySelector(".sheet-card"), [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(10px) scale(0.985)" }], { spring: "recede" });
  animate(sheet, [{ opacity: 1 }, { opacity: 0 }], { spring: "recede" });
  finished([a], 650).then(() => { if (token) { sheet.hidden = true; setInert(false); } });
}

function setInert(on) {
  for (const el of [document.querySelector(".rail"), document.querySelector(".main")]) el.inert = on;
}

function showSheet(message) {
  const sheet = $("#connect");
  sheet.hidden = false;
  setInert(true);
  animate(sheet, [{ opacity: 0 }, { opacity: 1 }], { spring: "recede" });
  animate(sheet.querySelector(".sheet-card"), [{ opacity: 0, transform: "translateY(14px) scale(0.98)" }, { opacity: 1, transform: "none" }], { spring: "panel" });
  showConnectError(message || "");
  setTimeout(() => tokenInput.focus(), 60);
}

function signOut(message) {
  token = null;
  state.evidenceCache.clear();
  app.dataset.state = "signed-out";
  showSheet(message);
}

// ------------------------------------------------------------------ pages: Home and the run workspace

const home = createHome({
  api,
  openRun: (runId) => openRun(runId),
  signOut: () => signOut("The API did not accept the token. It has been cleared from memory."),
  toast: (text, cls) => toast(text, cls),
  onView: (view) => { if (app.dataset.page === "home") { state.view = view; syncNav(view); } },
  onItems: (items) => {
    for (const item of items) {
      const run = state.runs.find((r) => r.id === item.run_id);
      if (run) run.summary = item; else state.runs.push({ id: item.run_id, status: "pending", summary: item });
    }
    renderRunList();
  },
  setTitle: (f, hs) => { if (app.dataset.page === "home") renderHomeTitle(f, hs); },
});

let pageTransition = 0;
function setPage(page) {
  app.dataset.page = page;
  stage.hidden = page !== "run";
  homeEl.hidden = page !== "home";
}

function showPage(page, then) {
  const current = app.dataset.page;
  closePopover();
  if (page === current) { if (page === "home") home.render(); if (then) then(); return; }
  const id = ++pageTransition;
  const out = page === "home" ? stage : homeEl, inn = page === "home" ? homeEl : stage;
  const a = animate(out, [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(6px) scale(0.985)" }],
                    { spring: "recede", fill: "forwards" });
  finished([a], 420).then(() => {
    if (id !== pageTransition) return;
    if (a) a.cancel();
    setPage(page);
    if (page === "home") { home.render(); state.view = home.view; syncNav(state.view); } else refreshRunHeader();
    animate(inn, [{ opacity: 0, transform: "translateY(10px) scale(0.985)" }, { opacity: 1, transform: "none" }], { spring: "panel" });
    if (page === "run" && state.topo) requestAnimationFrame(() => state.topo && state.topo.place());
    if (then) then();
  });
}

function openRun(runId) {
  if (!state.runs.find((r) => r.id === runId)) state.runs.push({ id: runId, status: "pending" });
  showPage("run", () => selectRun(runId));
}

function refreshRunHeader() {
  const run = state.runs.find((r) => r.id === state.active);
  if (state.model) { renderTitle(state.model); updateModeChip(state.model); } else { renderTitle(null, run); updateModeChip(null); }
  if (state.view === "home" || state.view === "investigations") state.view = stage.dataset.focus ? state.view : "overview";
  syncNav(state.view);
}

function renderHomeTitle(f, hs) {
  $("#run-title").textContent = "Cloud Autopsy";
  $("#run-sub").textContent = hs.granted === null
    ? (hs.loading ? "Verifying the runs granted to this token\u2026" : "Investigations granted to this token")
    : `${plural(hs.granted, "investigation")} granted to this token`;
  replace($("#run-meta"),
    h("div", null, h("dt", null, "Examined"), h("dd", null, hs.granted === null ? "\u2014" : `${f.examined} of ${hs.granted}`)),
    h("div", null, h("dt", null, "Pages"), h("dd", null, hs.pages ? `${hs.loaded} of ${hs.pages}` : "\u2014")),
    h("div", null, h("dt", null, "Order"), h("dd", null, "Run ID")),
    h("div", null, h("dt", null, "Data"), h("dd", null, hs.preview ? "Preview" : f.verified.length ? "Verified" : "\u2014")));
  const chip = $("#mode-chip");
  chip.className = "mode-chip";
  if (hs.preview) { chip.textContent = "Synthetic preview \u00b7 not verified"; chip.classList.add("is-preview"); }
  else if (f.verified.length) { chip.textContent = "Verified on read"; chip.classList.add("is-verified"); }
  else { chip.textContent = "No data"; chip.classList.add("is-muted"); }
}

// ------------------------------------------------------------------ run selection and rendering

async function selectRun(runId, { first = false, reverify = false } = {}) {
  const run = state.runs.find((r) => r.id === runId);
  if (!run) return;
  state.active = runId;
  closePopover();
  if (!first && state.view !== "overview") setView("overview", { quiet: true });
  if (reverify || run.status !== "ready" || !run.citations) {
    stage.classList.add("is-loading");
    await loadRun(run, { full: true });
    stage.classList.remove("is-loading");
  }
  if (!token || state.active !== runId) return;  // signed out (401) or another run was chosen meanwhile
  if (run.status === "error") return renderError(run);
  state.model = buildModel(run.result, run.citations);
  state.entry = null; state.evidence = null; state.evidenceFilter = "all"; state.stack = []; state.current = null;
  renderRun(!first);
  app.dataset.state = "ready";
  if (reverify) toast(`Verified again \u00b7 ${shortDigest(run.result.result_digest, 6)}`, run.result.verified ? "is-ok" : "is-amber");
}

function renderError(run) {
  const err = run.error || { code: "unknown" };
  const [title, text] = ERRORS[err.code] || ["Unexpected response", `The API answered with code ${err.code}.`];
  app.dataset.state = "ready";
  stage.dataset.error = err.code;
  if (stage.dataset.focus) setView("overview", { quiet: true });
  state.model = null;
  // Nothing from any other run stays on screen behind a refusal.
  if (state.topo) { state.topo.destroy(); state.topo = null; }
  for (const l of stage.querySelectorAll(".layer")) clear(l);
  app.classList.remove("is-abstained", "is-preview");
  cards.outcome.classList.remove("is-sage", "is-stone");
  renderTitle(null, run);
  const panel = $("#state-panel");
  replace(panel, h("div", { class: "state-card" },
    h("span", { class: ["state-icon", err.code === "overloaded" ? "is-amber" : null] }, icon(err.code === "disconnected" ? "plug" : "alert")),
    h("p", { class: "eyebrow" }, `Run ${shortRun(run.id)}`),
    h("h2", null, title),
    h("p", null, text),
    err.reason ? h("p", { class: "mono reason" }, `reason: ${err.reason}`) : null,
    h("div", { class: "state-actions" },
      h("button", { type: "button", class: "btn btn-ink", onclick: () => selectRun(run.id, { reverify: true }) }, "Try again"),
      state.runs.length > 1 ? h("button", { type: "button", class: "btn btn-soft", onclick: openPopover }, "Other runs") : null)));
  panel.hidden = false;
  animate(panel.firstChild, [{ opacity: 0, transform: "translateY(12px) scale(0.985)" }, { opacity: 1, transform: "none" }], { spring: "panel" });
  updateModeChip(null);
  syncNav(state.view);
}

function renderTitle(model, run) {
  const title = $("#run-title"), sub = $("#run-sub"), meta = $("#run-meta");
  if (!model) {
    title.textContent = run ? `Run ${shortRun(run.id)}` : "Cloud Autopsy";
    sub.textContent = "No verified result to show";
    clear(meta);
    return;
  }
  const m = model.meta;
  title.textContent = m.planId;
  sub.textContent = m.window ? `Run ${shortRun(m.runId)} \u00b7 ${fmtDate(m.window.start)}, ${fmtTime(m.window.start, false)}\u2013${fmtTime(m.window.end, false)} UTC` : `Run ${shortRun(m.runId)}`;
  replace(meta,
    h("div", null, h("dt", null, "Namespace"), h("dd", null, model.namespaces.join(", ") || "\u2014")),
    h("div", null, h("dt", null, "Sources"), h("dd", null, String(model.sources.length))),
    h("div", null, h("dt", null, "Evidence"), h("dd", null, `${m.evidenceCount} records`)),
    h("div", null, h("dt", null, "Engine"), h("dd", null, m.engine.replace("ca-engine/", ""))));
}

function updateModeChip(model) {
  const chip = $("#mode-chip");
  chip.className = "mode-chip";
  if (!model) { chip.textContent = "No data"; chip.classList.add("is-muted"); return; }
  if (model.meta.verified) { chip.textContent = "Verified on read"; chip.classList.add("is-verified"); }
  else { chip.textContent = model.meta.preview ? "Synthetic preview \u00b7 not verified" : "Not verified"; chip.classList.add("is-preview"); }
}

const ctx = {
  state,
  go: (view, opts = {}) => {
    if (opts.source) state.evidenceFilter = `source:${opts.source}`;
    setView(view);
  },
  select: (sel) => select(sel),
  openEvidence: (id) => openEvidence(id),
  openGap: (gap) => { if (!gap) return; ensureFocus(); showInspector({ type: "gap", gap }); },
  selectEntry: (entry) => {
    state.entry = entry.entry_id;
    for (const el of stage.querySelectorAll("[data-entry]")) el.classList.toggle("is-selected", el.dataset.entry === entry.entry_id);
    openEvidence(entry.evidence_id);
  },
  setEvidenceFilter: (key) => { state.evidenceFilter = key; fillExpanded("evidence", true); },
};

function layer(card, name) { return card.querySelector(`.layer-${name}`); }

function renderRun(animated) {
  const model = state.model;
  delete stage.dataset.error;
  $("#state-panel").hidden = true;
  renderTitle(model);
  updateModeChip(model);
  app.classList.toggle("is-abstained", !model.resolved);
  app.classList.toggle("is-preview", !model.meta.verified);

  if (state.topo) state.topo.destroy();
  state.topo = renderTopology(model, { onSelect: (sel) => select(sel) });
  replace(layer(cards.hero, "compact"),
    h("div", { class: "hero-head" },
      h("p", { class: "hero-label" }, `Evidence map \u00b7 ${model.namespaces.join(", ") || "no namespace"}`),
      h("span", { class: "chip chip-soft" }, `${model.evidence.size} records`)),
    state.topo.root,
    h("div", { class: "hero-foot" },
      h("div", { class: "segmented", role: "group", "aria-label": "Highlight" }, [["all", "All"], ["cited", "Cited"], ["gaps", "Gaps"]].map(([key, label]) =>
        h("button", { type: "button", class: state.filter === key ? "is-on" : null, "aria-pressed": String(state.filter === key), dataset: { filter: key },
                      onclick: (e) => { e.stopPropagation(); setFilter(key); } }, label))),
      h("p", { class: "hero-stats" }, h("span", null, "Entities ", h("b", null, String(model.entities.size))),
        h("span", null, "Sources ", h("b", null, String(model.sources.length))),
        h("span", null, "Missing ", h("b", null, String(state.topo.counts.missing))))));
  state.topo.setFilter(state.filter);
  segmentedSync(cards.hero, state.filter);

  replace(layer(cards.outcome, "compact"), V.outcomeCard(model));
  replace(layer(cards.verify, "compact"), V.verifyCard(model, ctx));
  replace(layer(cards.coverage, "compact"), V.coverageCard(model, ctx));
  replace(layer(cards.hyps, "compact"), V.hypsCompact(model, ctx));
  replace(layer(cards.timeline, "compact"), V.timelineCompact(model, ctx));
  replace(layer(cards.evidence, "compact"), V.evidenceCompact(model, ctx));
  replace(layer(cards.gaps, "compact"), V.gapsCompact(model, ctx));
  for (const id of ["hyps", "timeline", "evidence", "gaps"]) clear(layer(cards[id], "expanded"));
  applyBars(stage);
  cards.outcome.classList.toggle("is-sage", model.resolved);
  cards.outcome.classList.toggle("is-stone", !model.resolved);

  if (animated) {
    CARD_IDS.forEach((id, i) => animate(cards[id], [{ opacity: 0.001, transform: "translateY(8px) scale(0.99)" }, { opacity: 1, transform: "none" }],
                                          { spring: "panel", delay: 30 * i }));
  }
  requestAnimationFrame(() => state.topo && state.topo.place());
  syncNav(state.view);  // run-level pills become available once a run is shown
}

function applyBars(root) {
  for (const el of root.querySelectorAll("[data-w]")) el.style.width = `${(Number(el.dataset.w) * 100).toFixed(2)}%`;
  for (const el of root.querySelectorAll("[data-x]")) el.style.left = `${(Number(el.dataset.x) * 100).toFixed(2)}%`;
}

function segmentedSync(root, key) {
  for (const b of root.querySelectorAll("[data-filter]")) {
    b.classList.toggle("is-on", b.dataset.filter === key);
    b.setAttribute("aria-pressed", String(b.dataset.filter === key));
  }
}

function setFilter(key) {
  state.filter = key;
  segmentedSync(cards.hero, key);
  if (state.topo) state.topo.setFilter(key);
}

// ------------------------------------------------------------------ focus transitions

function fillExpanded(cardId, keepScroll) {
  const model = state.model;
  if (!model || cardId === "hero") return;
  const target = layer(cards[cardId], "expanded");
  const scroll = keepScroll ? target.scrollTop : 0;
  const make = { hyps: V.hypsExpanded, timeline: V.timelineExpanded, evidence: V.evidenceExpanded, gaps: V.gapsExpanded }[cardId];
  replace(target, make(model, ctx));
  applyBars(target);
  target.scrollTop = scroll;
}

function directionFrom(origin, r) {
  const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
  const dx = cx - (origin.x + origin.w / 2), dy = cy - (origin.y + origin.h / 2);
  const len = Math.hypot(dx, dy) || 1;
  return [(dx / len) * 26, (dy / len) * 18];
}

function narrow() { return window.matchMedia("(max-width: 1179px)").matches; }

function setView(view, { quiet = false } = {}) {
  if (!state.model && view !== "overview") return;
  const next = FOCUS[view] ?? null;
  const prev = stage.dataset.focus || null;
  state.view = view;
  syncNav(view);
  if (next === prev) { if (next) defaultInspector(view, true); return; }

  const id = ++state.transition;
  const all = CARD_IDS.map((c) => cards[c]);
  const first = new Map(all.map((c) => [c, { r: rectIn(c, stage), o: Number(getComputedStyle(c).opacity) }]));
  const inspOpacity = Number(getComputedStyle(inspector).opacity);
  const layers = [...stage.querySelectorAll(".layer")];
  cancelAll([...all, inspector, ...layers, inspBody]);
  for (const c of all) c.classList.remove("is-morphing", "is-lifted");
  for (const l of layers) { l.style.width = ""; l.style.height = ""; }

  // Last: the new layout.
  if (next) stage.dataset.focus = next; else delete stage.dataset.focus;
  for (const c of all) c.toggleAttribute("data-focused", c.dataset.card === next);
  app.dataset.view = view;
  if (next) { fillExpanded(next); defaultInspector(view, false); }
  const last = new Map(all.map((c) => [c, rectIn(c, stage)]));

  if (quiet || prefersReducedMotion()) {
    if (!quiet && prefersReducedMotion()) {
      for (const c of all) animate(c, [{ opacity: c.dataset.card === next || !next ? 0.4 : 1 }, { opacity: 1 }]);
      if (next) animate(inspector, [{ opacity: 0 }, { opacity: 1 }]);
    }
    afterTransition(next);
    return;
  }

  const anims = [];
  const nextCard = next && cards[next], prevCard = prev && cards[prev];
  const origin = nextCard ? last.get(nextCard) : first.get(prevCard).r;
  let k = 0;
  for (const c of all) {
    const f = first.get(c).r, l = last.get(c);
    const dx = f.x - l.x, dy = f.y - l.y;
    if (c === nextCard || (c === prevCard && !next)) {
      c.classList.add("is-lifted");
      anims.push(animate(c, [
        { transform: `translate(${dx}px, ${dy}px)`, width: `${f.w}px`, height: `${f.h}px`, opacity: Math.max(first.get(c).o, 0.001), visibility: "visible" },
        { transform: "translate(0px, 0px)", width: `${l.w}px`, height: `${l.h}px`, opacity: 1, visibility: "visible" }], { spring: "layout" }));
      morphLayers(c, c === nextCard, f, l, anims);
    } else if (!prev || c === prevCard) {
      // Visible before, hidden after: make way, away from the expanding card.
      const [mx, my] = directionFrom(origin, f);
      anims.push(animate(c, [
        { transform: `translate(${dx}px, ${dy}px)`, opacity: first.get(c).o, visibility: "visible" },
        { transform: `translate(${dx + mx}px, ${dy + my}px) scale(0.955)`, opacity: 0, visibility: "visible" }], { spring: "recede" }));
    } else if (!next) {
      // Hidden before, visible after: return to place with a light stagger.
      const [mx, my] = directionFrom(origin, l);
      anims.push(animate(c, [
        { transform: `translate(${mx}px, ${my}px) scale(0.955)`, opacity: first.get(c).o, visibility: "visible" },
        { transform: "none", opacity: 1, visibility: "visible" }], { spring: "panel", delay: 70 + 28 * k++ }));
    }
  }
  const off = narrow() ? "translateY(36px)" : "translateX(calc(100% + 28px))";
  if (next && !prev) {
    anims.push(animate(inspector, [{ transform: off, opacity: inspOpacity, visibility: "visible" }, { transform: "none", opacity: 1, visibility: "visible" }],
                       { spring: "panel", delay: 60 }));
  } else if (!next && prev) {
    anims.push(animate(inspector, [{ transform: "none", opacity: inspOpacity, visibility: "visible" }, { transform: off, opacity: 0, visibility: "visible" }],
                       { spring: "recede" }));
  }
  finished(anims, 1400).then(() => { if (id === state.transition) afterTransition(next); });
  if (state.topo) trackMarkers(anims);
}

function morphLayers(card, expanding, f, l, anims) {
  if (card.dataset.card === "hero") {
    const chrome = card.querySelector(".topology-legend");
    if (chrome) anims.push(animate(chrome, expanding ? [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }]
                                                     : [{ opacity: 1 }, { opacity: 0 }], { spring: "panel", delay: expanding ? 140 : 0 }));
    return;
  }
  const compact = layer(card, "compact"), expanded = layer(card, "expanded");
  card.classList.add("is-morphing");
  const [incoming, outgoing, inSize, outSize] = expanding ? [expanded, compact, l, f] : [compact, expanded, l, f];
  incoming.style.width = `${inSize.w}px`; incoming.style.height = `${inSize.h}px`;
  outgoing.style.width = `${outSize.w}px`; outgoing.style.height = `${outSize.h}px`;
  // The outgoing layer stays displayed until the whole morph ends, so its fade must hold at 0
  // ("forwards"); with no fill it would snap back to full opacity over the incoming layer.
  anims.push(animate(outgoing, [{ opacity: 1 }, { opacity: 0 }], { duration: 170, easing: "cubic-bezier(.3,0,.7,1)", fill: "forwards" }));
  anims.push(animate(incoming, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { spring: "panel", delay: 110 }));
}

function trackMarkers(anims) {
  let running = true;
  finished(anims, 1400).then(() => { running = false; state.topo && state.topo.place(); });
  const tick = () => { if (!running || !state.topo) return; state.topo.place(); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}

function afterTransition(next) {
  for (const c of CARD_IDS.map((x) => cards[x])) c.classList.remove("is-morphing", "is-lifted");
  for (const l of stage.querySelectorAll(".layer")) {
    l.style.width = ""; l.style.height = "";
    for (const a of l.getAnimations()) a.cancel();  // no held (filled) layer state outlives its transition
  }
  if (state.topo) state.topo.place();
  if (next) {
    const heading = inspector.querySelector(".insp-title");
    if (narrow()) cards[next].scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    if (heading && document.activeElement === document.body) heading.focus({ preventScroll: true });
  } else {
    state.stack = []; state.current = null;
    if (state.topo) state.topo.setSelection(null);
  }
}

function ensureFocus() {
  if (!stage.dataset.focus) setView("evidence");
}

// ------------------------------------------------------------------ inspector

function defaultInspector(view, animated) {
  const model = state.model;
  if (!model) return;
  if (state.current && state.current.type !== "summary" && state.current.view === view) return;
  state.stack = [];
  if (view === "evidence" && !state.evidence) showInspector({ type: "hint", title: "Select a record", text: "Choose an evidence record to see its provenance, content, coverage and citations." }, { animated, push: false });
  else if (view === "timeline" && !state.entry) showInspector({ type: "hint", title: "Select a time mark", text: "Each bar is one time mark of one evidence record. Its width is the clock and precision uncertainty." }, { animated, push: false });
  else showInspector({ type: "summary" }, { animated, push: false });
}

function showInspector(desc, { animated = true, push = true } = {}) {
  const model = state.model;
  if (!model) return;
  if (push && state.current && state.current.type !== "hint") state.stack.push(state.current);
  state.current = { ...desc, view: state.view };
  let body;
  if (desc.type === "summary") body = V.inspectSummary(model, ctx);
  else if (desc.type === "entity") body = V.inspectEntity(model, desc.entity, ctx);
  else if (desc.type === "gap") body = V.inspectGap(model, desc.gap);
  else if (desc.type === "evidence") body = V.inspectEvidence(model, desc.envelope, ctx);
  else if (desc.type === "loading") body = V.inspectMessage("is-loading", "Verifying\u2026", "The API re-verifies the run before serving this record.");
  else if (desc.type === "error") body = V.inspectMessage("is-error", desc.title, desc.text);
  else body = V.inspectMessage("is-hint", desc.title, desc.text);
  replace(inspBody, body);
  inspBody.scrollTop = 0;
  $("#insp-back").hidden = !state.stack.length;
  $("#insp-eyebrow").textContent = { summary: "Summary", entity: "Entity", gap: "Gap", evidence: "Evidence", loading: "Evidence", error: "Evidence" }[desc.type] || "Inspector";
  if (state.topo) state.topo.setSelection(desc.type === "entity" ? desc.entity.key : desc.type === "gap" && desc.gap.key ? desc.gap.key : null);
  if (animated) animate(inspBody, [{ opacity: 0, transform: "translateX(14px)" }, { opacity: 1, transform: "none" }], { spring: "panel" });
  if (push && narrow() && desc.type !== "hint") inspector.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

function select(sel) {
  if (sel.entity) {
    if (state.view !== "investigation") setView("investigation");
    showInspector({ type: "entity", entity: sel.entity });
  } else if (sel.gap) {
    if (state.view !== "investigation") setView("investigation");
    showInspector({ type: "gap", gap: { ...sel.gap.gaps[0], key: sel.gap.key } });
  }
}

async function openEvidence(id) {
  const model = state.model, run = state.runs.find((r) => r.id === state.active);
  if (!model || !run) return;
  state.evidence = id;
  for (const el of stage.querySelectorAll(".ev-row")) el.classList.toggle("is-selected", false);
  if (!stage.dataset.focus) setView("evidence");
  const key = `${run.id}/${model.meta.digest}/${hexOf(id)}`;
  let envelope = state.evidenceCache.get(key);
  if (!envelope) {
    showInspector({ type: "loading" }, { push: true });
    const res = await api(`/v1/runs/${run.id}/evidence/${hexOf(id)}`);
    if (state.evidence !== id || state.active !== run.id) return;
    if (res.status !== 200 || !res.body.data) {
      const f = failure(res);
      state.current = state.stack.pop() || null;
      if (f.code === "invalid_token") return signOut(ERRORS.invalid_token[1]);
      const [title, text] = ERRORS[f.code] || ["Record unavailable", `The API answered with code ${f.code}.`];
      return showInspector({ type: "error", title, text: f.reason ? `${text} (reason: ${f.reason})` : text });
    }
    if (res.body.result_digest !== model.meta.digest) {
      state.current = state.stack.pop() || null;
      return showInspector({ type: "error", title: ERRORS.inconsistent[0], text: ERRORS.inconsistent[1] });
    }
    envelope = res.body;
    state.evidenceCache.set(key, envelope);
    state.current = state.stack.pop() || null;
  }
  showInspector({ type: "evidence", envelope });
}

$("#insp-back").addEventListener("click", () => {
  const prev = state.stack.pop();
  if (!prev) return;
  state.current = null;
  showInspector(prev, { push: false });
});
$("#insp-close").addEventListener("click", () => setView("overview"));

// ------------------------------------------------------------------ nav, rail, popover, keyboard

const nav = $("#nav"), navPill = $("#nav-pill");
function syncNav(view) {
  for (const b of nav.querySelectorAll("[data-view]")) {
    if (RUN_VIEWS.has(b.dataset.view)) b.setAttribute("aria-disabled", String(!state.model));
  }
  const target = nav.querySelector(`[data-view="${view}"]`) || nav.querySelector('[data-view="gaps"]');
  for (const b of nav.querySelectorAll("[data-view]")) {
    const on = b === target;
    b.classList.toggle("is-on", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  }
  if (!target || !target.offsetParent) { navPill.style.opacity = "0"; return; }
  const n = nav.getBoundingClientRect(), r = target.getBoundingClientRect();
  const from = { x: navPill.dataset.x, w: navPill.dataset.w };
  const x = r.left - n.left + nav.scrollLeft, w = r.width;
  navPill.style.opacity = "1";
  navPill.style.transform = `translateX(${x}px)`;
  navPill.style.width = `${w}px`;
  if (from.x !== undefined && !prefersReducedMotion()) {
    animate(navPill, [{ transform: `translateX(${from.x}px)`, width: `${from.w}px` }, { transform: `translateX(${x}px)`, width: `${w}px` }], { spring: "panel" });
  }
  navPill.dataset.x = String(x); navPill.dataset.w = String(w);
}

nav.addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]");
  if (!b || b.getAttribute("aria-disabled") === "true" || app.dataset.state !== "ready") return;
  const view = b.dataset.view;
  if (view === "home" || view === "investigations") return goHome(view);
  if (!state.model) return;
  if (app.dataset.page !== "run") return showPage("run", () => setView(view));
  setView(view);
});

function goHome(view = "home") {
  showPage("home", () => { home.setView(view); state.view = view; syncNav(view); });
}

for (const id of EXPANDABLE) {
  cards[id].addEventListener("click", (e) => {
    if (!state.model || stage.dataset.focus || e.target.closest("button, a, input, textarea")) return;
    setView(VIEW_OF[id]);
  });
  const expand = cards[id].querySelector(".expand");
  if (expand) expand.addEventListener("click", (e) => { e.stopPropagation(); if (state.model) setView(stage.dataset.focus === id ? "overview" : VIEW_OF[id]); });
}

const popover = $("#runs-popover");
function renderRunList() {
  const list = $("#run-list");
  replace(list, state.runs.map((run) => {
    const sum = run.summary && run.summary.outcome ? run.summary : null;
    const outcome = run.result ? run.result.data.outcome.status : sum ? sum.outcome.status : null;
    const label = run.status === "ready" || (run.status === "pending" && sum) ? (outcome === "resolved" ? "Resolved" : "Abstained")
      : run.status === "error" ? (ERRORS[run.error.code] || ["Error"])[0] : run.status === "loading" ? "Verifying\u2026"
        : run.summary ? ({ unverifiable: "Unverifiable", not_found: "Not found", unavailable: "Unavailable" }[run.summary.state] || "Not loaded") : "Not loaded";
    return h("li", null, h("button", { type: "button", class: ["run-item", run.id === state.active ? "is-on" : null], dataset: { run: run.id }, onclick: () => (app.dataset.page === "run" ? selectRun(run.id) : openRun(run.id)) },
      h("span", { class: ["run-dot", outcome ? `is-${outcome}` : run.summary ? "is-error" : `is-${run.status}`] }),
      h("span", { class: "run-id mono" }, shortRun(run.id)),
      h("span", { class: "run-plan" }, run.result ? run.result.data.inputs.plan_id.replace(/^ca-scenario-001-/, "") : sum ? sum.plan_id.replace(/^ca-scenario-001-/, "") : ""),
      h("span", { class: "run-state" }, label)));
  }));
  const active = state.runs.find((r) => r.id === state.active);
  $("#run-pill-label").textContent = active ? `Run ${shortRun(active.id)}` : "Runs";
  $("#run-pill").dataset.status = active ? (active.status === "ready" ? active.result.data.outcome.status : active.status) : "";
}

function openPopover() {
  if (!state.runs.length) return;
  popover.hidden = false;
  animate(popover, [{ opacity: 0, transform: "translateY(-6px) scale(0.98)" }, { opacity: 1, transform: "none" }], { spring: "panel" });
  const on = popover.querySelector(".is-on") || popover.querySelector("button");
  if (on) on.focus();
}
function closePopover() {
  if (popover.hidden) return;
  const a = animate(popover, [{ opacity: 1 }, { opacity: 0, transform: "translateY(-4px) scale(0.985)" }], { spring: "micro" });
  finished([a]).then(() => { popover.hidden = true; });
}
$("#run-pill").addEventListener("click", (e) => { e.stopPropagation(); popover.hidden ? openPopover() : closePopover(); });
$("#rail-runs").addEventListener("click", (e) => { e.stopPropagation(); popover.hidden ? openPopover() : closePopover(); });
$("#rail-overview").addEventListener("click", () => { if (app.dataset.state === "ready") goHome("home"); });
$("#rail-refresh").addEventListener("click", () => { if (state.active && token) selectRun(state.active, { reverify: true }); });
$("#rail-lock").addEventListener("click", () => {
  if (!token) return showSheet("");
  state.runs = []; state.active = null; state.model = null;
  if (stage.dataset.focus) setView("overview", { quiet: true });
  home.reset();
  renderRunList();
  signOut("Token cleared from memory.");
});
document.addEventListener("click", (e) => { if (!popover.hidden && !popover.contains(e.target)) closePopover(); });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!popover.hidden) return closePopover();
  if (app.dataset.page === "home") { if (home.view === "investigations") goHome("home"); return; }
  if (state.stack.length) return $("#insp-back").click();
  if (stage.dataset.focus) setView("overview");
});

let toastTimer = null;
function toast(text, cls) {
  const t = $("#toast");
  t.textContent = text;
  t.className = ["toast", cls].filter(Boolean).join(" ");
  t.hidden = false;
  animate(t, [{ opacity: 0, transform: "translate(-50%, 10px)" }, { opacity: 1, transform: "translate(-50%, 0)" }], { spring: "panel" });
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { const a = animate(t, [{ opacity: 1 }, { opacity: 0 }], { spring: "micro" }); finished([a]).then(() => { t.hidden = true; }); }, 2400);
}

window.addEventListener("resize", () => { syncNav(state.view); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) syncNav(state.view); });

setPage("run");
syncNav("overview");
app.dataset.state = "signed-out";
showSheet("");
