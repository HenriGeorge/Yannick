// place.mjs — stream one SVG straight into a Figma page via set_svg (generalized from svg-to-figma).
// Bypasses the MCP agent's per-turn output cap + the zod 500KB schema limit, so multi-MB vectors import.
//   --svg=<file>    the SVG to place (or a bare positional path)
//   --x --y         placement (default 0,0)   ·   --name  node name (default: file basename)
//   --channel=<id>  talk-to-figma channel (repeatable); auto-resolved otherwise (FIGMA_CHANNEL)
//   --file-key=<k>  disambiguate live channels by file fingerprint
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";

function parseFlags(args) {
  const flags = {};
  const channels = [];
  const positional = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) {
      if (m[1] === "channel") channels.push(m[2]);
      else flags[m[1]] = m[2];
    } else if (a.startsWith("--")) flags[a.slice(2)] = true;
    else positional.push(a);
  }
  return { flags, channels, positional };
}

export async function run(args) {
  const { flags, channels, positional } = parseFlags(args);
  const svgPath = flags.svg ?? positional[0];
  if (!svgPath) throw new Error("place: --svg=<file> (or a positional path) is required");
  const svg = readFileSync(svgPath, "utf8");
  const x = Number(flags.x ?? 0);
  const y = Number(flags.y ?? 0);
  if (!Number.isFinite(x)) throw new Error(`place: invalid --x "${flags.x}" — must be a number`);
  if (!Number.isFinite(y)) throw new Error(`place: invalid --y "${flags.y}" — must be a number`);
  const name = flags.name ?? basename(svgPath);

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  join(conn, channel);

  // set_svg is a CREATION command → the relay REQUIRES params.parentId (a page/frame node id).
  const pages = await rpc(conn, "get_pages", {}, 30000);
  const parentId = pages?.currentPageId ?? pages?.pages?.[0]?.id;
  if (!parentId) {
    close(conn);
    throw new Error("place: get_pages returned no page id");
  }
  const kb = Math.round(svg.length / 1024);
  process.stderr.write(`[${channel}] ${name}: ${kb}KB svg → set_svg (page ${parentId})\n`);
  const res = await rpc(conn, "set_svg", { svgString: svg, x, y, name, parentId }, Number(process.env.SET_SVG_TIMEOUT ?? 170000));
  close(conn);
  const nodeId = res?.id ?? res?.nodeId;
  if (!nodeId) throw new Error(`place: set_svg resolved without a node id (empty/odd reply) for "${name}"`);
  console.log(`placed ${name} [${channel}] → node ${nodeId} (${res.width}x${res.height}) on page ${parentId}`);
}
