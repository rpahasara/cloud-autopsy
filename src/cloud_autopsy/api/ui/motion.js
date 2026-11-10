// Spring-based motion on the Web Animations API. A damped spring is simulated once per preset
// and sampled into a CSS `linear()` easing, so layout (FLIP) transitions move like physical
// springs while the browser runs them off the main thread where it can.

const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
export const prefersReducedMotion = () => reduceQuery.matches;

const LINEAR_SUPPORTED = typeof CSS !== "undefined" && CSS.supports("animation-timing-function", "linear(0, 0.5 50%, 1)");

function simulate(stiffness, damping, mass) {
  const dt = 1 / 240;
  let x = 0, v = 0, t = 0;
  const points = [[0, 0]];
  while (t < 2.5) {
    const a = (-stiffness * (x - 1) - damping * v) / mass;
    v += a * dt;
    x += v * dt;
    t += dt;
    points.push([t, x]);
    if (Math.abs(x - 1) < 0.0008 && Math.abs(v) < 0.004) break;
  }
  return { duration: t, points };
}

function toEasing({ duration, points }) {
  if (!LINEAR_SUPPORTED) return "cubic-bezier(0.22, 0.9, 0.24, 1)";
  const stops = [];
  const n = 48;
  for (let i = 0; i <= n; i++) {
    const target = (duration * i) / n;
    let j = 0;
    while (j < points.length - 1 && points[j + 1][0] < target) j++;
    const [t0, x0] = points[j], [t1, x1] = points[Math.min(j + 1, points.length - 1)];
    const x = t1 === t0 ? x1 : x0 + ((x1 - x0) * (target - t0)) / (t1 - t0);
    stops.push(i === n ? "1" : x.toFixed(4));
  }
  return `linear(${stops.join(", ")})`;
}

function preset(stiffness, damping, mass = 1, clamp = [380, 760]) {
  const sim = simulate(stiffness, damping, mass);
  return { easing: toEasing(sim), duration: Math.round(Math.min(clamp[1], Math.max(clamp[0], sim.duration * 1000))) };
}

export const SPRINGS = {
  layout: preset(190, 27.5),          // the hero / card expansion: settled, almost no overshoot
  panel: preset(230, 25),             // inspector slide-in: a hint of overshoot
  recede: preset(260, 32, 1, [300, 520]),
  micro: preset(520, 40, 1, [160, 260]),
};

export function animate(el, keyframes, { spring = "layout", delay = 0, duration, easing, fill } = {}) {
  // A delayed animation holds its first frame while it waits, so nothing flashes in its final state.
  fill = fill || (delay > 0 ? "backwards" : "none");
  if (!el || !el.animate) return null;
  const p = SPRINGS[spring] || SPRINGS.layout;
  if (prefersReducedMotion()) {
    // Calm alternative: no movement or scaling, only a short opacity settle where it helps.
    const opacityOnly = keyframes.map((k) => ("opacity" in k ? { opacity: k.opacity } : {}));
    if (!opacityOnly.some((k) => "opacity" in k)) return null;
    return el.animate(opacityOnly, { duration: 140, easing: "linear", fill });
  }
  return el.animate(keyframes, { duration: duration || p.duration, easing: easing || p.easing, delay, fill });
}

// Resolves when the animations finish, or after a bounded time: a hidden or throttled page may
// not advance animation frames, and no state change may wait on one indefinitely.
export function finished(animations, limitMs = 1000) {
  const all = Promise.all(animations.filter(Boolean).map((a) => a.finished.catch(() => null)));
  return Promise.race([all, new Promise((resolve) => setTimeout(resolve, limitMs))]);
}

// Geometry relative to a container, read from the rendered (possibly mid-animation) state.
export function rectIn(el, container) {
  const r = el.getBoundingClientRect(), c = container.getBoundingClientRect();
  return { x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height };
}

export function cancelAll(elements) {
  for (const el of elements) for (const a of el.getAnimations()) a.cancel();
}
