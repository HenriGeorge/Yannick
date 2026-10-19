// png.mjs — export the current Figma selection's FRAMEs → PNG on disk (generalized from
// export-figma-light). Reads get_selection (a light id/name/type stub, never blows the socket limit),
// then export_node_as_image → decode base64 → write. No hardcoded channel and no "— light" filter.
//   --all              export every selected FRAME (default)
//   --filter=<substr>  opt-in: keep only frames whose name contains <substr>
//   --scale=<n>        export scale (default 1)   ·   --out=<dir>  output dir (default figma-export)
//   --channel=<id>     talk-to-figma channel (repeatable); auto-resolved otherwise (FIGMA_CHANNEL)
//   --file-key=<k>     disambiguate live channels by file fingerprint
// One writer per channel: exports run STRICTLY sequentially. Select frames in Figma (Cmd+A) first.
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { connect, join as joinChannel, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";

function parseFlags(args) {
  const flags = {};
  const channels = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) {
      if (m[1] === "channel") channels.push(m[2]);
      else flags[m[1]] = m[2];
    } else if (a.startsWith("--")) flags[a.slice(2)] = true;
  }
  return { flags, channels };
}

function slugFor(name) {
  let s = (name || "").replace(/^\//, "") || "frame";
  s = s.replace(/[/\s]+/g, "-").replace(/[^a-zA-Z0-9._-]/g, "").toLowerCase();
  return s || "frame";
}

export async function run(args) {
  const { flags, channels } = parseFlags(args);
  const scale = Number(flags.scale ?? 1);
  if (!Number.isFinite(scale)) throw new Error(`png: invalid --scale "${flags.scale}" — must be a number`);
  const out = flags.out ?? "figma-export";
  const filter = typeof flags.filter === "string" ? flags.filter : null; // opt-in substring; else all
  mkdirSync(out, { recursive: true });

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  joinChannel(conn, channel);
  console.log(`[png] joined channel ${channel}`);

  const sel = await rpc(conn, "get_selection", {}, 15000);
  const frames = (sel.selection || []).filter((n) => n.type === "FRAME" && (!filter || n.name.includes(filter)));
  console.log(`[png] selection=${sel.selectionCount}, matching frames=${frames.length}`);
  if (frames.length === 0) {
    close(conn);
    throw new Error("png: NO matching FRAMEs selected. In Figma: click the canvas, Cmd+A, then re-run" + (filter ? ` (filter="${filter}")` : ""));
  }

  const report = [];
  const usedSlugs = new Map();
  for (const f of frames) {
    let slug = slugFor(f.name);
    const n = (usedSlugs.get(slug) || 0) + 1;
    usedSlugs.set(slug, n);
    if (n > 1) slug = `${slug}-${n}`;
    const file = join(out, `${slug}.png`);
    try {
      const res = await rpc(conn, "export_node_as_image", { nodeId: f.id, format: "PNG", scale }, 120000);
      const buf = Buffer.from(res?.imageData ?? "", "base64");
      // An empty/absent imageData base64-decodes to a 0-byte buffer with no throw — that would write a
      // 0-byte PNG reported "ok". Treat an empty export as a failed one.
      if (buf.length === 0) throw new Error("export_node_as_image returned empty imageData (0 bytes)");
      writeFileSync(file, buf);
      console.log(`[png] OK  ${f.name}  ->  ${file}  (${Math.round(buf.length / 1024)}KB)`);
      report.push({ name: f.name, id: f.id, file, bytes: buf.length, status: "ok" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`[png] FAIL ${f.name} (${f.id}): ${msg}`);
      report.push({ name: f.name, id: f.id, file, status: "FAILED", error: msg });
    }
  }
  close(conn);
  console.log("\n[png] REPORT:\n" + JSON.stringify(report, null, 2));
  if (report.some((r) => r.status !== "ok")) throw new Error(`png: ${report.filter((r) => r.status !== "ok").length} export(s) FAILED`);
}
