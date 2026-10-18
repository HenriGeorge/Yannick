// snapshot.mjs — save a page's top-level frame positions to JSON (snapshot), and move them back
// (restore). The undo net for any move command (arrange, a manual drag, a mirror run). Restore
// matches by node id; name is a human label. Zero-dep.
import { readFileSync, writeFileSync } from "node:fs";
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";
import { readFrames } from "./read-frames.mjs";

function parseFlags(args) {
  const flags = {}, channels = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) { if (m[1] === "channel") channels.push(m[2]); else flags[m[1]] = m[2]; }
    else if (a.startsWith("--")) flags[a.slice(2)] = true;
  }
  return { flags, channels };
}
const slug = (s) => (s || "page").replace(/[/\s]+/g, "-").replace(/[^a-zA-Z0-9._-]/g, "").toLowerCase() || "page";
const asObj = (r) => (typeof r === "string" ? JSON.parse(r) : r);

export function toSnapshot({ fileKey, page, channel, frames, now }) {
  return { fileKey, page, channel, savedAt: now, frames: frames.map((f) => ({ id: f.id, name: f.name, x: f.ox, y: f.oy })) };
}

export async function run(args) { // snapshot
  const { flags, channels } = parseFlags(args);
  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const conn = await connect(process.env.FIGMA_WS_URL ?? "ws://localhost:3055");
  join(conn, channel);
  try {
    const frames = await readFrames(conn, { page: flags.page });
    // Don't write a useless 0-frame "undo net" and report it as success — fail loud (an empty page,
    // a wrong --page, or an unexpected reply all surface here instead of at restore time).
    if (!frames.length) throw new Error("snapshot: no frames with bounds on this page — nothing to save");
    const doc = asObj(await rpc(conn, "get_document_info", {}, 30000));
    const pageName = flags.page ?? doc?.currentPage?.name ?? "page";
    const snap = toSnapshot({ fileKey: flags["file-key"] ?? null, page: pageName, channel, frames, now: new Date().toISOString() });
    const out = flags.out ?? `./figma-snapshot-${slug(pageName)}.json`;
    writeFileSync(out, JSON.stringify(snap, null, 2));
    console.log(`snapshot: ${snap.frames.length} frames → ${out}`);
  } finally { close(conn); }
}

export async function runRestore(args) { // restore
  const { flags, channels } = parseFlags(args);
  const file = flags.in ?? flags.file;
  if (!file) throw new Error("restore: --in=<file> is required");
  const snap = JSON.parse(readFileSync(file, "utf8"));
  if (!snap?.frames?.length) throw new Error(`restore: ${file} has no frames`);
  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const conn = await connect(process.env.FIGMA_WS_URL ?? "ws://localhost:3055");
  join(conn, channel);
  try {
    // Operate on the CURRENT page (the plugin is already on it). The bridge's set_current_page is
    // unreliable (times out), and ids are unique file-wide, so a page switch isn't needed to match.
    const live = new Set((await readFrames(conn, {})).map((f) => f.id));
    let moved = 0, skipped = 0;
    for (const f of snap.frames) {
      if (!live.has(f.id)) { skipped++; process.stderr.write(`  skip ${f.name} (${f.id} not on page)\n`); continue; }
      await rpc(conn, "move_node", { nodeId: f.id, x: f.x, y: f.y }, 30000);
      moved++;
    }
    if (moved === 0) throw new Error(`restore: 0 of ${snap.frames.length} frames matched — stale or wrong-page snapshot`);
    console.log(`restore: moved ${moved}, skipped ${skipped} [${channel}]`);
  } finally { close(conn); }
}
