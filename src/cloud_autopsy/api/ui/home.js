// Home: an overview of the runs granted to the current token, built only from
// /v1/summaries/{page}. Every figure is computed from the runs this page actually examined, and
// says so: nothing is extrapolated to runs that were not loaded, and runs that are unverifiable,
// not found or unavailable are counted as such, never as outcomes.

import { fmtDate, fmtTime, h, icon, plural, replace, s, shortRun } from "./dom.js";
import { animate, cancelAll, finished, prefersReducedMotion, rectIn } from "./motion.js";
import { say } from "./views.js";

const AUTO_PAGES = 5;            // pages loaded without asking (each page is one bounded request)
const ATTENTION = new Set(["unverifiable", "not_found", "unavailable"]);
const HAS_RESULT = new Set(["verified", "preview"]);
const STATE_LABEL = { verified: "Verified", preview: "Preview \u00b7 not verified", unverifiable: "Unverifiable",
                      not_found: "Not found", unavailable: "Unavailable" };
const CARD_IDS = ["hero", "granted", "resolved", "abstained", "attention", "trend", "band"];

export function createHome(env) {
  const root = document.querySelector("#home");
  const st = { items: new Map(), granted: null, pages: null, loaded: 0, loading: false, error: null, preview: false,
               view: "home", filter: "all", sort: "newest", bucket: "day", transition: 0, rendered: false };
  const cards = {};
  for (const id of CARD_IDS) {
    cards[id] = h(id === "band" ? "section" : "div", { class: ["h-card", `h-${id}`], dataset: { hcard: id } });
    root.append(cards[id]);
  }

  // ---------------------------------------------------------------- data

  function reset() {
    st.items.clear();
    st.granted = st.pages = st.error = null;
    st.loaded = 0; st.loading = false; st.view = "home"; st.filter = "all"; st.sort = "newest"; st.rendered = false;
    delete root.dataset.focus;
    for (const c of Object.values(cards)) c.toggleAttribute("data-focused", false);
  }

  async function loadPage(page) {
    const res = await env.api(`/v1/summaries/${page}`);
    if (res.status !== 200 || !Array.isArray(res.body.items)) {
      const code = (res.body && res.body.error) || `http_${res.status}`;
      if (code === "invalid_token") { env.signOut(); return false; }
      st.error = code;
      return false;
    }
    st.granted = res.body.granted_total;
    st.pages = res.body.pages;
    st.loaded = Math.max(st.loaded, res.body.page);
    st.preview = res.body.data_source === "synthetic-preview";
    for (const item of res.body.items) st.items.set(item.run_id, item);
    env.onItems([...st.items.values()]);
    return true;
  }

  async function load() {
    if (st.loading) return;
    st.loading = true; st.error = null;
    render();
    let page = st.loaded + 1;
    const limit = st.loaded + AUTO_PAGES;
    while (page <= limit && (st.pages === null || page <= st.pages)) {
      if (!(await loadPage(page))) break;
      render();
      page += 1;
    }
    st.loading = false;
    render();
  }

  // ---------------------------------------------------------------- derived figures (examined runs only)

  function figures() {
    const all = [...st.items.values()];
    const results = all.filter((i) => HAS_RESULT.has(i.state));
    const group = (pred) => all.filter(pred);
    const records = results.reduce((n, i) => n + i.evidence.records, 0);
    const cited = results.reduce((n, i) => n + i.evidence.cited, 0);
    const sources = new Map();
    for (const i of results) {
      for (const [src, v] of Object.entries(i.evidence.by_source)) {
        const t = sources.get(src) || { id: src, records: 0, gaps: 0, runs: 0, gapRuns: 0 };
        t.records += v.records; t.gaps += v.gaps; t.runs += 1; if (v.gaps) t.gapRuns += 1;
        sources.set(src, t);
      }
    }
    const reasons = new Map();
    for (const i of results) for (const r of i.gaps.reasons) reasons.set(r, (reasons.get(r) || 0) + 1);
    return {
      all, results, examined: all.length, granted: st.granted ?? 0,
      verified: group((i) => i.state === "verified"),
      resolved: results.filter((i) => i.outcome.status === "resolved"),
      abstained: results.filter((i) => i.outcome.status !== "resolved"),
      unverifiable: group((i) => i.state === "unverifiable"),
      notFound: group((i) => i.state === "not_found"),
      unavailable: group((i) => i.state === "unavailable"),
      attention: group((i) => ATTENTION.has(i.state)),
      records, cited, sources: [...sources.values()].sort((a, b) => b.records - a.records || a.id.localeCompare(b.id)),
      reasons: [...reasons.entries()].sort((a, b) => b[1] - a[1]),
      partial: st.granted !== null && all.length < st.granted,
    };
  }

  const startOf = (i) => (i.window && Date.parse(i.window.start)) || null;
  const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);
  const kindOf = (i) => (!HAS_RESULT.has(i.state) ? "attention" : i.outcome.status === "resolved" ? "resolved" : "abstained");

  function sorted(list) {
    const by = {
      newest: (a, b) => (startOf(b) ?? -Infinity) - (startOf(a) ?? -Infinity) || (a.plan_id || a.run_id).localeCompare(b.plan_id || b.run_id),
      title: (a, b) => (a.plan_id || "\uffff" + a.run_id).localeCompare(b.plan_id || "\uffff" + b.run_id),
      outcome: (a, b) => ["resolved", "abstained", "attention"].indexOf(kindOf(a)) - ["resolved", "abstained", "attention"].indexOf(kindOf(b)) || by.newest(a, b),
      evidence: (a, b) => ((b.evidence || {}).records ?? -1) - ((a.evidence || {}).records ?? -1) || by.newest(a, b),
    };
    return list.slice().sort(by[st.sort]);
  }

  // ---------------------------------------------------------------- small visual primitives

  function dotStrip(f, pick) {
    return h("div", { class: "dot-strip", "aria-hidden": "true" },
      f.all.map((i) => h("span", { class: ["dot-run", pick(i) ? `is-${kindOf(i)}` : null] })));
  }

  function arcGauge(value, total, label, sub) {
    const r = 46, len = Math.PI * r, frac = total ? value / total : 0;
    const arc = s("path", { d: `M ${60 - r} 60 A ${r} ${r} 0 0 1 ${60 + r} 60`, class: "gauge-fill",
                            "stroke-dasharray": `${len} ${len}`, "stroke-dashoffset": String(len * (1 - frac)) });
    const svg = s("svg", { viewBox: "0 0 120 66", class: "gauge-svg", "aria-hidden": "true" },
      s("defs", null, s("linearGradient", { id: "ca-gauge", x1: 0, y1: 0, x2: 1, y2: 0 },
        s("stop", { offset: "0", "stop-color": "#a9bd94" }), s("stop", { offset: "1", "stop-color": "#6f8b5d" }))),
      s("path", { d: `M ${60 - r} 60 A ${r} ${r} 0 0 1 ${60 + r} 60`, class: "gauge-track" }), arc);
    if (!prefersReducedMotion()) animate(arc, [{ strokeDashoffset: String(len) }, { strokeDashoffset: String(len * (1 - frac)) }], { spring: "layout", delay: 120 });
    return h("div", { class: "gauge" }, h("p", { class: "gauge-label" }, label), svg,
      h("p", { class: "gauge-value" }, String(value), h("small", null, `/${total}`)), sub ? h("p", { class: "gauge-sub" }, sub) : null);
  }

  function lineGauge(value, total, label, sub) {
    const frac = total ? value / total : 0;
    const marker = h("span", { class: "lg-marker" });
    marker.style.left = `${(frac * 100).toFixed(1)}%`;
    const fill = h("span", { class: "lg-fill" });
    fill.style.width = `${(frac * 100).toFixed(1)}%`;
    return h("div", { class: "gauge is-line" }, h("p", { class: "gauge-label" }, label),
      h("div", { class: "lg-track" }, fill, marker),
      h("p", { class: "gauge-value" }, `${pct(value, total)}`, h("small", null, "%")), sub ? h("p", { class: "gauge-sub" }, sub) : null);
  }

  // ---------------------------------------------------------------- cards

  function heroCard(f) {
    const ring = 2 * Math.PI * 54, frac = f.granted ? f.examined / f.granted : 0;
    const prog = s("circle", { cx: 70, cy: 70, r: 54, class: "orb-progress", "stroke-dasharray": `${ring} ${ring}`,
                               "stroke-dashoffset": String(ring * (1 - frac)), transform: "rotate(-90 70 70)" });
    if (!prefersReducedMotion()) animate(prog, [{ strokeDashoffset: String(ring) }, { strokeDashoffset: String(ring * (1 - frac)) }], { spring: "layout", delay: 200 });
    const maxRec = Math.max(1, ...f.results.map((i) => i.evidence.records));
    const barcode = (list) => h("div", { class: "barcode", "aria-hidden": "true" }, list.length ? list.map((i) => {
      const bar = h("span", { class: `is-${kindOf(i)}` });
      bar.style.height = HAS_RESULT.has(i.state) ? `${Math.max(16, (100 * i.evidence.records) / maxRec).toFixed(0)}%` : "16%";
      return bar;
    }) : h("span", { class: "is-empty" }));
    const col = (label, list, hint) => h("div", { class: "hero-col" },
      h("p", null, label, " ", h("b", null, String(list.length))), barcode(list), h("small", null, hint));
    return [
      h("div", { class: "hero-blobs", "aria-hidden": "true" },
        h("span", { class: "blob blob-sage", dataset: { w: String(f.resolved.length) } }),
        h("span", { class: "blob blob-sand" }), h("span", { class: "blob blob-mist" })),
      h("header", { class: "hero-intro" },
        h("h2", null, "Investigation landscape"),
        h("p", null, st.preview ? "Synthetic preview of the runs granted to this token \u2014 not verified."
          : "The runs granted to this token, each re-verified from its sealed run when loaded.")),
      h("div", { class: "hero-gauges" },
        arcGauge(f.verified.length, f.examined, "Verified on read", st.preview ? "preview results are not verified" : "of examined runs"),
        lineGauge(f.cited, f.records, "Evidence cited", `${f.cited} of ${plural(f.records, "record")}`)),
      h("div", { class: "orb" },
        s("svg", { viewBox: "0 0 140 140", class: "orb-svg", "aria-hidden": "true" },
          s("circle", { cx: 70, cy: 70, r: 54, class: "orb-track" }), prog),
        h("p", { class: "orb-value" }, String(f.examined), h("small", null, `/${f.granted}`)),
        h("p", { class: "orb-label" }, "Examined")),
      h("div", { class: "hero-glass" },
        col("Resolved", f.resolved, "bar height: evidence records"),
        col("Abstained", f.abstained, "per run"),
        col("Needs attention", f.attention, "no result shown")),
    ];
  }

  function metricCard(kind, title, value, chip, f, pick, foot) {
    return [
      h("header", { class: "m-head" }, h("h3", null, title), chip ? h("span", { class: ["m-chip", `is-${kind}`] }, chip) : null),
      h("div", { class: "m-body" }, h("p", { class: "m-value" }, String(value)), dotStrip(f, pick)),
      foot ? h("p", { class: "m-foot" }, foot) : null,
    ];
  }

  function trendCard(f, W = 640, H = 200) {
    const dated = f.results.filter((i) => startOf(i) !== null);
    const keyOf = (ms) => {
      const d = new Date(ms);
      if (st.bucket === "day") return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
      const day = (d.getUTCDay() + 6) % 7;
      return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day);
    };
    const buckets = new Map();
    for (const i of dated) {
      const k = keyOf(startOf(i));
      const b = buckets.get(k) || { k, resolved: 0, abstained: 0 };
      b[kindOf(i)] += 1;
      buckets.set(k, b);
    }
    const list = [...buckets.values()].sort((a, b) => a.k - b.k);
    const padL = 34, padB = 26, padT = 14;
    const maxY = Math.max(1, ...list.map((b) => b.resolved + b.abstained));
    const step = list.length ? (W - padL - 16) / list.length : 0;
    const y = (v) => H - padB - ((H - padB - padT) * v) / maxY;
    const grid = [0, Math.ceil(maxY / 2), maxY].filter((v, i, a) => a.indexOf(v) === i).map((v) => s("g", null,
      s("line", { x1: padL, x2: W - 8, y1: y(v), y2: y(v), class: "tr-grid" }),
      s("text", { x: padL - 8, y: y(v) + 4, class: "tr-axis", "text-anchor": "end" }, String(v))));
    const bars = [];
    const tips = [];
    list.forEach((b, idx) => {
      const cx = padL + step * idx + step / 2, bw = Math.min(46, step * 0.42);
      const g = s("g", { class: "tr-col", tabindex: "0", role: "img",
                         "aria-label": `${st.bucket === "day" ? fmtDate(b.k) : `Week of ${fmtDate(b.k)}`}: ${b.resolved} resolved, ${b.abstained} abstained` });
      const segs = [["abstained", b.abstained, 0], ["resolved", b.resolved, b.abstained]];
      for (const [kind, n, base] of segs) {
        if (!n) continue;
        const rect = s("rect", { x: cx - bw / 2, y: y(base + n), width: bw, height: y(base) - y(base + n), rx: Math.min(10, bw / 2), class: `tr-bar is-${kind}` });
        if (!prefersReducedMotion()) animate(rect, [{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }], { spring: "layout", delay: 80 + 60 * idx });
        g.append(rect);
      }
      g.append(s("text", { x: cx, y: H - 8, class: "tr-axis", "text-anchor": "middle" }, st.bucket === "day" ? fmtDate(b.k).replace(/ \d{4}$/, "") : `wk ${fmtDate(b.k).replace(/ \d{4}$/, "")}`));
      bars.push(g);
      tips.push({ g, text: `${b.resolved + b.abstained}`, x: cx, y: y(b.resolved + b.abstained) });
    });
    // A connecting line only when there are enough points to show a direction.
    let area = null;
    if (list.length >= 3) {
      const pts = list.map((b, i) => [padL + step * i + step / 2, y(b.resolved + b.abstained)]);
      const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
      area = [s("path", { d: `${d} L${pts[pts.length - 1][0]} ${H - padB} L${pts[0][0]} ${H - padB} Z`, class: "tr-area" }),
              s("path", { d, class: "tr-line" })];
    }
    const grad = (id, top, bottom, o1 = 1, o2 = 1) => s("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 },
      s("stop", { offset: "0", "stop-color": top, "stop-opacity": String(o1) }), s("stop", { offset: "1", "stop-color": bottom, "stop-opacity": String(o2) }));
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "trend-svg", role: "img", "aria-label": "Examined runs by incident window start" },
      s("defs", null, grad("ca-trend-area", "#8fa77c", "#8fa77c", 0.32, 0), grad("ca-trend-resolved", "#b3c79c", "#7c9867"),
        grad("ca-trend-abstained", "#e3ddd1", "#c4bcad")),
      grid, area, bars);
    const tip = h("span", { class: "tr-tip", hidden: true });
    for (const t of tips) {
      const show = () => { tip.textContent = t.text; tip.hidden = false; tip.style.left = `${(100 * t.x / W).toFixed(2)}%`; tip.style.top = `${(100 * t.y / H).toFixed(2)}%`; };
      t.g.addEventListener("pointerenter", show); t.g.addEventListener("focus", show);
      t.g.addEventListener("pointerleave", () => { tip.hidden = true; }); t.g.addEventListener("blur", () => { tip.hidden = true; });
    }
    const undated = f.examined - dated.length;
    const note = !list.length ? "No examined run has a verified incident window yet."
      : list.length === 1 ? `All ${plural(dated.length, "examined run")} start${dated.length === 1 ? "s" : ""} ${st.bucket === "day" ? "on" : "in the week of"} ${fmtDate(list[0].k)} \u2014 too few points for a trend.`
        : `${plural(dated.length, "examined run")} by incident window start.`;
    return [
      h("header", { class: "m-head" },
        h("div", null, h("h3", null, "Investigation activity"), h("p", { class: "m-sub" }, "Examined runs by incident window start (UTC)")),
        h("div", { class: "segmented", role: "group", "aria-label": "Bucket" }, [["day", "Day"], ["week", "Week"]].map(([k, label]) =>
          h("button", { type: "button", class: st.bucket === k ? "is-on" : null, "aria-pressed": String(st.bucket === k),
                        onclick: (e) => { e.stopPropagation(); st.bucket = k; fill("trend"); } }, label)))),
      h("div", { class: "trend-plot" }, svg, tip),
      h("p", { class: "m-foot" }, h("span", { class: "key is-resolved" }), "Resolved ", h("span", { class: "key is-abstained" }), "Abstained \u00b7 ", note,
        undated ? ` ${plural(undated, "run")} without a verified result ${undated === 1 ? "is" : "are"} not plotted.` : ""),
    ];
  }

  function recentRow(i) {
    const has = HAS_RESULT.has(i.state);
    const total = has ? i.evidence.records + i.gaps.total : 0;
    const fillEl = h("span", { class: "rr-fill" });
    fillEl.style.width = has && total ? `${((100 * i.evidence.records) / total).toFixed(0)}%` : "0%";
    return h("li", null, h("button", { type: "button", class: ["rr", `is-${kindOf(i)}`], onclick: (e) => { e.stopPropagation(); env.openRun(i.run_id); },
                                       title: has ? i.plan_id : i.run_id },
      fillEl,
      h("span", { class: "rr-dot" }),
      h("span", { class: "rr-title" }, has ? i.plan_id : `Run ${shortRun(i.run_id)}`),
      h("span", { class: "rr-meta" }, has ? `${say(i.outcome.status)} \u00b7 ${fmtDate(startOf(i))}` : STATE_LABEL[i.state])));
  }

  function bandCompact(f) {
    const maxSrc = Math.max(1, ...f.sources.map((x) => x.records + x.gaps));
    const tile = (kind, title, list, lines) => h("div", { class: ["tile", `is-${kind}`] },
      h("p", { class: "tile-title" }, title),
      h("p", { class: "tile-value" }, String(pct(list.length, f.examined)), h("small", null, "%")),
      h("p", { class: "tile-line" }, icon("doc"), plural(list.length, "run")), lines);
    const avg = (list) => (list.length ? (list.reduce((n, i) => n + i.evidence.records, 0) / list.length).toFixed(1) : "0");
    return h("div", { class: "band-grid" },
      h("div", { class: "band-col" },
        h("h3", null, "Evidence by source"),
        h("div", { class: "band-panel" },
          f.sources.length ? h("ul", { class: "src-list" }, f.sources.map((src) => {
            const rec = h("span", { class: "src-rec" }), gap = h("span", { class: "src-gap" });
            rec.style.width = `${((100 * src.records) / maxSrc).toFixed(1)}%`;
            gap.style.width = `${((100 * src.gaps) / maxSrc).toFixed(1)}%`;
            return h("li", null, h("div", { class: "src-head" }, h("span", { class: "mono" }, src.id),
              h("span", null, String(src.records), h("small", null, " rec"), src.gaps ? h("em", null, ` +${src.gaps} gap${src.gaps === 1 ? "" : "s"}`) : null)),
              h("div", { class: "src-track" }, rec, gap));
          })) : h("p", { class: "band-empty" }, "No examined run has evidence yet."),
          f.reasons.length ? h("div", { class: "chips-dark" }, f.reasons.map(([r, n]) => h("span", null, `${say(r)} \u00b7 ${n}`))) : null)),
      h("div", { class: "band-col" },
        h("h3", null, "Outcomes"),
        h("div", { class: "tiles" },
          tile("resolved", "Resolved", f.resolved, h("p", { class: "tile-line" }, icon("clock"), `${avg(f.resolved)} evidence / run`)),
          tile("abstained", "Abstained", f.abstained, h("p", { class: "tile-line" }, icon("clock"), `${avg(f.abstained)} evidence / run`)),
          tile("attention", "Needs attention", f.attention, h("p", { class: "tile-line" }, icon("alert"),
            `${f.unverifiable.length} unverif. \u00b7 ${f.notFound.length + f.unavailable.length} missing`)))),
      h("div", { class: "band-col" },
        h("div", { class: "band-head" }, h("h3", null, "Recent investigations"),
          h("button", { type: "button", class: "link-light", onclick: (e) => { e.stopPropagation(); setView("investigations"); } }, "View all")),
        f.all.length ? h("ul", { class: "recent" }, sorted(f.all).slice(0, 3).map(recentRow))
          : h("p", { class: "band-empty" }, st.loading ? "Loading\u2026" : "No runs examined yet.")));
  }

  function bandExpanded(f) {
    const filters = [["all", "All", f.all.length], ["resolved", "Resolved", f.resolved.length], ["abstained", "Abstained", f.abstained.length],
                     ["attention", "Needs attention", f.attention.length]];
    const rows = sorted(f.all.filter((i) => st.filter === "all" || kindOf(i) === st.filter));
    const hyp = (i) => {
      const hs = i.hypotheses || {};
      return h("span", { class: "hyp-mini" }, [["supported", "S"], ["contradicted", "C"], ["unresolved", "U"], ["not_supported", "N"]].map(([k, l]) =>
        h("span", { class: [`hm-${k}`, hs[k] ? null : "is-zero"], title: `${say(k)}: ${hs[k] || 0}` }, `${l}${hs[k] || 0}`)));
    };
    return h("div", { class: "inv" },
      h("header", { class: "inv-head" },
        h("div", null, h("h2", null, "Investigations"),
          h("p", null, `${plural(f.examined, "run")} examined of ${f.granted} granted to this token, in pages of ten verified loads.`)),
        h("div", { class: "inv-controls" },
          h("div", { class: "segmented is-dark", role: "group", "aria-label": "Filter" }, filters.map(([k, label, n]) =>
            h("button", { type: "button", class: st.filter === k ? "is-on" : null, "aria-pressed": String(st.filter === k), dataset: { filter: k },
                          onclick: (e) => { e.stopPropagation(); st.filter = k; fill("band"); } }, label, h("small", null, ` ${n}`)))),
          h("div", { class: "segmented is-dark", role: "group", "aria-label": "Sort" }, [["newest", "Newest"], ["title", "Title"], ["outcome", "Outcome"], ["evidence", "Evidence"]].map(([k, label]) =>
            h("button", { type: "button", class: st.sort === k ? "is-on" : null, "aria-pressed": String(st.sort === k), dataset: { sort: k },
                          onclick: (e) => { e.stopPropagation(); st.sort = k; fill("band"); } }, label))))),
      h("div", { class: "inv-table", role: "table", "aria-label": "Investigations" },
        h("div", { class: "inv-row is-head", role: "row" }, ["Investigation", "Incident window", "Outcome", "Evidence", "Hypotheses", "Verification"].map((c) => h("span", { role: "columnheader" }, c))),
        rows.length ? rows.map((i) => {
          const has = HAS_RESULT.has(i.state);
          const total = has ? i.evidence.records + i.gaps.total : 0;
          const bar = h("span", { class: "ev-bar-fill" });
          bar.style.width = has && total ? `${((100 * i.evidence.records) / total).toFixed(0)}%` : "0%";
          return h("button", { type: "button", role: "row", class: ["inv-row", `is-${kindOf(i)}`], dataset: { run: i.run_id },
                               onclick: (e) => { e.stopPropagation(); env.openRun(i.run_id); } },
            h("span", { role: "cell", class: "inv-title" }, h("b", null, has ? i.plan_id : "\u2014"), h("small", { class: "mono" }, shortRun(i.run_id))),
            h("span", { role: "cell" }, has ? `${fmtDate(startOf(i))}, ${fmtTime(startOf(i), false)}\u2013${fmtTime(Date.parse(i.window.end), false)}` : "\u2014"),
            h("span", { role: "cell" }, has ? h("span", { class: ["pill-st", `is-${kindOf(i)}`] }, say(i.outcome.status)) : "\u2014",
              has && i.outcome.mechanism ? h("small", null, say(i.outcome.mechanism)) : null),
            h("span", { role: "cell", class: "inv-ev" }, has ? [h("span", null, `${i.evidence.records} rec`, i.gaps.total ? h("em", null, ` +${i.gaps.total} gap`) : null,
              h("small", null, ` \u00b7 manifest ${say(i.manifest.status).toLowerCase()}`)), h("span", { class: "ev-bar" }, bar)] : "\u2014"),
            h("span", { role: "cell" }, has ? hyp(i) : "\u2014"),
            h("span", { role: "cell", class: ["inv-ver", `is-${i.state}`] }, STATE_LABEL[i.state], i.reason ? h("small", { class: "mono" }, ` ${i.reason}`) : null));
        }) : h("p", { class: "band-empty" }, "No examined run matches this filter.")),
      h("footer", { class: "inv-foot" },
        h("span", null, f.partial ? `Showing ${f.examined} of ${f.granted} granted runs; figures cover examined runs only.` : `All ${f.granted} granted runs examined.`,
          " Sorting applies to examined runs."),
        st.pages !== null && st.loaded < st.pages ? h("button", { type: "button", class: "btn btn-light", disabled: st.loading,
          onclick: (e) => { e.stopPropagation(); load(); } }, st.loading ? "Verifying\u2026" : `Load more \u00b7 page ${st.loaded + 1} of ${st.pages}`) : null));
  }

  // The chart is drawn at its real pixel size (no stretched text); redraw when that size changes.
  let trendSize = "";
  let trendFrame = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(trendFrame);
    trendFrame = requestAnimationFrame(() => {
      const box = cards.trend.querySelector(".trend-plot");
      if (box && box.clientWidth > 40 && `${box.clientWidth}x${box.clientHeight}` !== trendSize) fill("trend");
    });
  }).observe(cards.trend);

  // ---------------------------------------------------------------- render

  function fill(id, { both = false } = {}) {
    const f = figures();
    const c = cards[id];
    if (id === "hero") replace(c, heroCard(f));
    else if (id === "granted") replace(c, metricCard("granted", "Granted runs", f.granted, f.partial ? `${f.examined} examined` : "all examined", f, () => true,
      `${f.verified.length} verified \u00b7 ${f.results.length - f.verified.length} preview`));
    else if (id === "resolved") replace(c, metricCard("resolved", "Resolved", f.resolved.length, `${pct(f.resolved.length, f.examined)}%`, f, (i) => kindOf(i) === "resolved",
      "a hypothesis is supported by evidence"));
    else if (id === "abstained") replace(c, metricCard("abstained", "Abstained", f.abstained.length, `${pct(f.abstained.length, f.examined)}%`, f, (i) => kindOf(i) === "abstained",
      "no cause asserted"));
    else if (id === "attention") replace(c, metricCard("attention", "Unverifiable", f.unverifiable.length, f.attention.length ? `${f.attention.length} need attention` : "none", f,
      (i) => kindOf(i) === "attention", `${f.notFound.length} not found \u00b7 ${f.unavailable.length} unavailable`));
    else if (id === "trend") {
      const box = c.querySelector(".trend-plot");
      const size = box && box.clientWidth > 40 ? [box.clientWidth, box.clientHeight] : [640, 200];
      replace(c, trendCard(f, size[0], Math.max(60, size[1])));
      trendSize = size.join("x");
    }
    else if (id === "band") {
      replace(c,
        h("button", { type: "button", class: "band-notch", "aria-label": st.view === "investigations" ? "Back to home" : "Show all investigations",
                      onclick: (e) => { e.stopPropagation(); setView(st.view === "investigations" ? "home" : "investigations"); } },
          s("svg", { viewBox: "0 0 24 24", class: "icon", "aria-hidden": "true" }, s("path", { d: st.view === "investigations" ? "M7 10l5 5 5-5" : "M7 14l5-5 5 5" }))),
        h("div", { class: "h-layer h-compact" }, bandCompact(f)),
        h("div", { class: "h-layer h-expanded" }, st.view === "investigations" || both ? bandExpanded(f) : null));
    }
  }

  function render() {
    for (const id of CARD_IDS) fill(id);
    const f = figures();
    root.classList.toggle("is-preview", st.preview);
    env.setTitle(f, st);
    if (st.error) env.toast(`Could not load runs: ${st.error}`, "is-amber");
    st.rendered = true;
  }

  // ---------------------------------------------------------------- Investigations view (the band expands)

  function setView(view, { quiet = false } = {}) {
    if (view === st.view) return;
    const next = view === "investigations" ? "band" : null;
    st.view = view;
    env.onView(view);
    const id = ++st.transition;
    const all = CARD_IDS.map((c) => cards[c]);
    const first = new Map(all.map((c) => [c, { r: rectIn(c, root), o: Number(getComputedStyle(c).opacity) }]));
    cancelAll(all);
    clearMorph();  // an interrupted morph never leaves its in-flight state behind
    if (next) root.dataset.focus = next; else delete root.dataset.focus;
    cards.band.toggleAttribute("data-focused", Boolean(next));
    fill("band", { both: true });  // both layers carry content for the crossfade
    const band = cards.band;
    const last = new Map(all.map((c) => [c, rectIn(c, root)]));
    if (quiet || prefersReducedMotion()) {
      fill("band");
      if (!quiet) animate(band.querySelector(next ? ".h-expanded" : ".h-compact"), [{ opacity: 0 }, { opacity: 1 }]);
      return;
    }
    const anims = [];
    const f0 = first.get(band).r, l0 = last.get(band);
    band.classList.add("is-lifted", "is-morphing");
    anims.push(animate(band, [{ transform: `translate(${f0.x - l0.x}px, ${f0.y - l0.y}px)`, width: `${f0.w}px`, height: `${f0.h}px` },
                              { transform: "translate(0px, 0px)", width: `${l0.w}px`, height: `${l0.h}px` }], { spring: "layout" }));
    const incoming = band.querySelector(next ? ".h-expanded" : ".h-compact");
    const outgoing = band.querySelector(next ? ".h-compact" : ".h-expanded");
    incoming.style.width = `${l0.w}px`; incoming.style.height = `${l0.h}px`;
    outgoing.style.width = `${f0.w}px`; outgoing.style.height = `${f0.h}px`;
    anims.push(animate(outgoing, [{ opacity: 1 }, { opacity: 0 }], { duration: 170, easing: "cubic-bezier(.3,0,.7,1)", fill: "forwards" }));
    anims.push(animate(incoming, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { spring: "panel", delay: 110 }));
    let k = 0;
    for (const c of all) {
      if (c === band) continue;
      const f = first.get(c).r, l = last.get(c);
      const away = `translate(${f.x - l.x}px, ${f.y - l.y - 18}px) scale(0.965)`;
      anims.push(next
        ? animate(c, [{ transform: "none", opacity: first.get(c).o, visibility: "visible" }, { transform: away, opacity: 0, visibility: "visible" }], { spring: "recede" })
        : animate(c, [{ transform: away, opacity: first.get(c).o, visibility: "visible" }, { transform: "none", opacity: 1, visibility: "visible" }], { spring: "panel", delay: 60 + 26 * k++ }));
    }
    finished(anims, 1400).then(() => {
      if (id !== st.transition) return;
      clearMorph();
      fill("band");
    });
  }

  function clearMorph() {
    const band = cards.band;
    band.classList.remove("is-lifted", "is-morphing");
    for (const l of band.querySelectorAll(".h-layer")) { l.style.width = ""; l.style.height = ""; for (const a of l.getAnimations()) a.cancel(); }
  }

  // ---------------------------------------------------------------- entrance

  function enter() {
    if (prefersReducedMotion()) return;
    CARD_IDS.forEach((id, i) => animate(cards[id], [{ opacity: 0.001, transform: "translateY(10px) scale(0.99)" }, { opacity: 1, transform: "none" }],
                                        { spring: "panel", delay: 30 * i }));
  }

  return { root, reset, load, render, setView, enter, get view() { return st.view; }, get state() { return st; }, figures };
}
