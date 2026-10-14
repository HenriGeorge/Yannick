// read-frames.mjs — shared top-level-frame reader for the ClaudeTalkToFigma bridge. Lists a page's
// top-level children and reads each one's bounds with a sever-safe get_node_info depth:0 (serial).
// A whole-page / depth:1 read would return too much data and sever the plugin, so this reads one
// frame at a time. Zero-dep: Node core + the shared relay-client backbone only.
import { rpc } from "./relay-client.mjs";

// The relay returns some replies as JSON strings — normalize at the boundary (same as tokens/vars).
const asObj = (r) => (typeof r === "string" ? JSON.parse(r) : r);

// toFrame(child, info) — pure map of a get_document_info child + its get_node_info reply → a Frame.
// Returns null when the node has no bounds (skip it). Field names match arrange's layout math.
export function toFrame(child, info) {
  const b = info?.absoluteBoundingBox, lp = info?.localPosition;
  if (!b || !lp) return null;
  return { id: child.id, name: child.name, type: child.type, ax: b.x, ay: b.y, w: b.width, h: b.height, ox: lp.x, oy: lp.y };
}

// readFrames(conn, {include,exclude,page}) — current page by default; a named page is switched to first.
export async function readFrames(conn, { include = [], exclude = [], page = null } = {}) {
  if (page) {
    const pages = asObj(await rpc(conn, "get_pages", {}, 30000));
    const list = pages?.pages ?? [];
    const pg = list.find((p) => p.name === page);
    if (!pg) throw new Error(`read-frames: no page named "${page}" (have: ${list.map((p) => p.name).join(", ")})`);
    await rpc(conn, "set_current_page", { pageId: pg.id }, 30000);
  }
  const doc = asObj(await rpc(conn, "get_document_info", {}, 30000));
  // A missing `children` key means an unexpected reply shape (e.g. a stringified reply that failed to
  // normalize) — fail loud rather than silently returning an empty frame list. An empty array (a real
  // empty page) is fine and passes through.
  if (!doc || !Array.isArray(doc.children)) {
    throw new Error("read-frames: unexpected get_document_info reply (no children array) — relay shape changed?");
  }
  let kids = doc.children;
  if (include.length) kids = kids.filter((k) => include.some((s) => k.name.includes(s)));
  if (exclude.length) kids = kids.filter((k) => !exclude.some((s) => k.name.includes(s)));
  const frames = [];
  for (const k of kids) {
    const info = asObj(await rpc(conn, "get_node_info", { nodeId: k.id, depth: 0 }, 30000));
    const f = toFrame(k, info);
    if (f) frames.push(f); else process.stderr.write(`  skip ${k.name} (no bounds)\n`);
  }
  return frames;
}
