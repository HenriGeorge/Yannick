// recolor.mjs — set solid fills on a frame's DIRECT children by name/regex selector.
// Reads each frame once (get_node_info depth:0 — the bulk-read sever gotcha) and streams
// set_fill_color SERIALLY over one socket, so the plugin never drops mid-run.
//
//   node figma.mjs recolor <frameId...> --set=<sel>=<hex> [...] [--white=<sel>=<hex>] [--other=<sel>=<hex>]
//
//   --set=<sel>=<hex>     recolor every direct child matching <sel> to <hex> (unconditional)
//   --white=<sel>=<hex>   recolor matches whose CURRENT fill is ~white (r,g,b each >0.9)
//   --other=<sel>=<hex>   recolor matches whose CURRENT fill is NOT ~white
//                         (NB: --white/--other key off CURRENT fill, so they are ONE-SHOT —
//                          re-running on an already-recolored frame re-tests the new colors)
//   <sel>                 exact child name, or a /regex/ tested against the name
//   --dry-run             print what would change, set nothing
//   --channel=<id>        talk-to-figma channel (repeatable); auto-resolved otherwise
//   --file-key=<k>        disambiguate live channels by file fingerprint
//
// Example (admin nav rail dark→light):
//   node figma.mjs recolor 21379:588609 --set=nav=#f4f4f4 --set=logo=#0a0a0a \
//     --set=sub=#707070 --set=activebar=#0a0a0a \
//     --white='/^nav\d+$/'=#0a0a0a --other='/^nav\d+$/'=#707070
//
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";

export function hexToColor(hex) {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) throw new Error(`recolor: bad hex "${hex}" (want #rrggbb)`);
  const h = m[1];
  return { r: parseInt(h.slice(0, 2), 16) / 255, g: parseInt(h.slice(2, 4), 16) / 255, b: parseInt(h.slice(4, 6), 16) / 255, a: 1 };
}

// A selector is an exact name, or /regex/ matched against the name.
export function makeMatcher(sel) {
  if (sel.length > 1 && sel.startsWith("/") && sel.endsWith("/")) {
    const re = new RegExp(sel.slice(1, -1));
    return (name) => re.test(name);
  }
  return (name) => name === sel;
}

export function isWhite(color) {
  return !!color && color.r > 0.9 && color.g > 0.9 && color.b > 0.9;
}

// Parse a repeatable `<sel>=<hex>` flag into {match, color, raw}. Splits on the LAST '=' so a
// /regex/ selector may itself contain '='.
function parseRules(list, cond) {
  return list.map((v) => {
    const i = v.lastIndexOf("=");
    if (i < 1) throw new Error(`recolor: --${cond} needs <sel>=<hex>, got "${v}"`);
    const sel = v.slice(0, i), hex = v.slice(i + 1);
    return { cond, match: makeMatcher(sel), color: hexToColor(hex), raw: `${sel}→${hex}` };
  });
}

function parseFlags(args) {
  const flags = {};
  const channels = [], set = [], white = [], other = [], frames = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) {
      if (m[1] === "channel") channels.push(m[2]);
      else if (m[1] === "set") set.push(m[2]);
      else if (m[1] === "white") white.push(m[2]);
      else if (m[1] === "other") other.push(m[2]);
      else flags[m[1]] = m[2];
    } else if (a.startsWith("--")) flags[a.slice(2)] = true;
    else frames.push(a);
  }
  return { flags, channels, set, white, other, frames };
}

export async function run(args) {
  const { flags, channels, set, white, other, frames } = parseFlags(args);
  if (!frames.length) throw new Error("recolor: pass one or more frame node ids");
  const rules = [...parseRules(set, "set"), ...parseRules(white, "white"), ...parseRules(other, "other")];
  if (!rules.length) throw new Error("recolor: pass at least one --set/--white/--other rule");
  const dryRun = !!flags["dry-run"];

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  join(conn, channel);
  try {
    let total = 0;
    for (const frameId of frames) {
      const info = await rpc(conn, "get_node_info", { nodeId: frameId });
      const kids = info.children || [];
      let n = 0;
      for (const c of kids) {
        const color = c.fills && c.fills[0] && c.fills[0].color;
        for (const r of rules) {
          if (!r.match(c.name)) continue;
          if (r.cond === "white" && !isWhite(color)) continue;
          if (r.cond === "other" && isWhite(color)) continue;
          if (dryRun) { process.stdout.write(`  ${frameId} ${c.id.padEnd(16)} ${c.name.padEnd(12)} ${r.raw}\n`); n++; break; }
          try { await rpc(conn, "set_fill_color", { nodeId: c.id, color: r.color }); n++; }
          catch (e) { process.stderr.write(`  err ${c.id}: ${String(e).slice(0, 50)}\n`); }
          break; // first matching rule wins for this child
        }
      }
      process.stderr.write(`[${channel}] ${frameId}: ${dryRun ? "would recolor" : "recolored"} ${n} nodes\n`);
      total += n;
    }
    console.log(`${dryRun ? "dry-run: " : ""}recolor ${total} nodes across ${frames.length} frame(s) [${channel}]`);
  } finally {
    close(conn);
  }
}
