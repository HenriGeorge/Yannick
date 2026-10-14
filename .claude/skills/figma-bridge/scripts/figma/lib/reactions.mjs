// reactions.mjs — wire ClaudeTalkToFigma PROTOTYPE reactions (ON_CLICK → NAVIGATE / OPEN URL) from a
// flow-map JSON. The bridge has no prototype support otherwise, so this is the one place the
// set_reactions wire-schema lives.
//
//   --map=<file.json>   the flow map (required)
//   --channel=<id>      talk-to-figma channel (repeatable); auto-resolved otherwise (FIGMA_CHANNEL)
//   --file-key=<k>      disambiguate live channels by file fingerprint
//   --dry-run           print the planned writes, touch nothing
//   --verify            after EACH write, do ONE spaced get_reactions read-back. OFF by default:
//                       batched/looped reads (get_reactions, scan_text_nodes) WEDGE the plugin until
//                       it is re-launched (see the skill's GOTCHAS.md "read-sever / wedge"). Write-only
//                       is the safe default; turn --verify on only for small maps.
//
// Map JSON shape:
//   {
//     "nav":    [ { "source": "<nodeId>", "dest": "<frameId>", "name": "Login→CheckEmail" } ],
//     "urls":   [ { "source": "<nodeId>", "url": "https://mail.google.com", "name": "Gmail" } ],
//     "scroll": [ "<frameId>", ... ]          // best-effort; the bridge currently does NOT apply this
//   }
//
// set_reactions REPLACES a node's reactions (idempotent). Trigger ON_CLICK, SMART_ANIMATE 0.3s.
// NOTE: Figma rejects a NAVIGATE whose destination is the SAME top-level frame as the source
// (self-nav) — the plugin errors; skip those in the map.
//
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { readFileSync } from "node:fs";
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";

// The relay sometimes returns an RPC reply as a JSON string (same convention as the sibling
// read modules); normalize before reading fields, else a string reply fails the read-back.
const asObj = (r) => (typeof r === "string" ? JSON.parse(r) : r);

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

const TRANSITION = { type: "SMART_ANIMATE", easing: { type: "EASE_IN_AND_OUT" }, duration: 0.3 };
export const navAction = (destId) => ({
  type: "NODE",
  destinationId: destId,
  navigation: "NAVIGATE",
  transition: TRANSITION,
  preserveScrollPosition: false,
});
export const urlAction = (url) => ({ type: "URL", url });

// PURE: flatten a flow map's nav + urls into the ordered write list [{source, action, label}].
// Extracted so the map→reaction-payload transform is unit-testable without a browser/relay.
export function buildItems(map) {
  return [
    ...(map.nav ?? []).map((n) => ({ source: n.source, action: navAction(n.dest), label: n.name ?? `${n.source}→${n.dest}` })),
    ...(map.urls ?? []).map((u) => ({ source: u.source, action: urlAction(u.url), label: u.name ?? `${u.source}→url` })),
  ];
}

export async function run(args) {
  const { flags, channels } = parseFlags(args);
  const mapPath = flags.map;
  if (!mapPath) throw new Error("reactions: --map=<file.json> is required");
  const map = JSON.parse(readFileSync(mapPath, "utf8"));
  const dryRun = Boolean(flags["dry-run"]);
  const verify = Boolean(flags.verify);

  const items = buildItems(map);

  if (dryRun) {
    for (const it of items) console.log(`DRY ${it.label}: set_reactions on ${it.source} → ${JSON.stringify(it.action).slice(0, 90)}`);
    for (const f of map.scroll ?? []) console.log(`DRY scroll VERTICAL on ${f} (note: bridge may not apply)`);
    console.log(`\nDRY ${items.length} reaction(s)${map.scroll?.length ? ` + ${map.scroll.length} scroll` : ""}`);
    return;
  }

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  join(conn, channel);

  let ok = 0;
  const failed = [];
  for (const it of items) {
    try {
      await rpc(conn, "set_reactions", { nodeId: it.source, reactions: [{ trigger: { type: "ON_CLICK" }, actions: [it.action] }] }, 20000);
      if (verify) {
        const back = asObj(await rpc(conn, "get_reactions", { nodeId: it.source }, 15000));
        const has = (back?.reactions ?? []).some((r) => (r.actions ?? []).length > 0);
        if (!has) throw new Error("read-back shows no actions");
      }
      ok++;
      console.log(`  ✓ ${it.label} [${channel}]`);
    } catch (e) {
      console.log(`  ✗ ${it.label}: ${e.message.slice(0, 120)}`);
      failed.push(`${it.label}: ${e.message.slice(0, 80)}`);
    }
  }

  for (const frameId of map.scroll ?? []) {
    try {
      await rpc(conn, "set_node_properties", { nodeId: frameId, properties: { overflowDirection: "VERTICAL" } }, 15000);
      console.log(`  ? scroll ${frameId} (set; bridge may not apply/echo overflowDirection)`);
    } catch (e) {
      failed.push(`scroll ${frameId}: ${e.message.slice(0, 60)}`);
    }
  }

  close(conn);
  console.log(`\n[${channel}] wired ${ok}${failed.length ? ` · FAILED ${failed.length}: ${failed.join("; ")}` : ""}`);
  // Fail loud like the sibling tools (tokens read-back throw, vars --strict exit 1): a scripted /
  // agent caller gating on exit code must not read a total relay failure as success.
  if (failed.length) process.exitCode = 1;
}
