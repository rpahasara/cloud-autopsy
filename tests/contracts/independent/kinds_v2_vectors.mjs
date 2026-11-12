// Independent computation of the CA-P2-004d test vectors (observation kinds 0.2): evidence IDs and
// content digests for k8s_event and configmap_metadata, from the *documented* identity and content
// rules (docs/phase2/ca-p2-004/ca-p2-004d.md), without the Python implementation.
//
//   node tests/contracts/independent/kinds_v2_vectors.mjs <vectors.json>
//
// Prints {name: {evidence_id, content_digest}} for every entry of "observations". The JSON
// canonicalization here is JCS restricted to what the vectors use (ASCII strings, integers, booleans,
// null, arrays, objects): keys sorted by code unit, no whitespace.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const ID_ALG = "ca-evidence-id-sha256/0.1-provisional";
const CONTENT_ALG = "ca-evidence-content-sha256/0.1-provisional";
const SET_VALUED = { configmap_metadata: ["data_key_names", "binary_key_names"], k8s_event: [] };

function jcs(v) {
  if (v === null || typeof v === "boolean") return JSON.stringify(v);
  if (typeof v === "number") { if (!Number.isInteger(v)) throw new Error("integers only"); return String(v); }
  if (typeof v === "string") { if (!/^[\x20-\x7e]*$/.test(v)) throw new Error("ASCII only"); return JSON.stringify(v); }
  if (Array.isArray(v)) return "[" + v.map(jcs).join(",") + "]";
  return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + jcs(v[k])).join(",") + "}";
}
const sha = (v) => createHash("sha256").update(jcs(v), "utf8").digest("hex");

const vectors = JSON.parse(readFileSync(process.argv[2], "utf8"));
const sources = Object.fromEntries(vectors.registry.sources.map((s) => [s.source_id, s]));
const out = {};
for (const [name, { source_id, observation: o }] of Object.entries(vectors.observations)) {
  const src = sources[source_id];
  const identity = { algorithm: ID_ALG, source_id, cluster_id: src.cluster_id, namespace: src.namespace,
                     observation_kind: o.observation_kind, source_uid: o.source_uid, source_version: o.source_version };
  const attributes = structuredClone(o.attributes);
  for (const key of SET_VALUED[o.observation_kind]) attributes[key] = [...attributes[key]].sort();
  const times = o.times.map((t) => ({ timestamp_kind: t.timestamp_kind, raw: t.raw, clock_domain_id: t.clock_domain_id,
                                      declared_precision_ns: t.declared_precision_ns }))
    .sort((a, b) => (a.timestamp_kind < b.timestamp_kind ? -1 : 1));
  const content = { algorithm: CONTENT_ALG, observation_kind: o.observation_kind, source_ref: o.source_ref,
                    source_uid: o.source_uid, source_version: o.source_version, entity: o.entity, times, attributes };
  out[name] = { evidence_id: `${ID_ALG}:${sha(identity)}`, content_digest: `${CONTENT_ALG}:${sha(content)}` };
}
console.log(JSON.stringify(out, null, 2));
