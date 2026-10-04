// rebind.mjs — bind an imported SVG frame's literal fills to Figma VARIABLES by matching color
// (generalized from rebind-svg-vars, "pipeline C"). A captured SVG holds literal colors, not variable
// refs; this walks the tree under --root and, for every node whose SOLID fill equals a variable's value,
// binds fills/0/color → that variable. Idempotent (already-bound fills skipped). A partial bind fails loud.
//   --root=<nodeId>     subtree root to rebind (required)
//   --collection=<name> only match variables from this collection (default: all)
//   --strokes           also rebind strokes/0/color
//   --dry-run           walk + report matches, bind nothing (read-only preview)
//   --max=<N>           stop after N binds (safety cap; not a failure)
//   --channel=<id>      talk-to-figma channel (repeatable); auto-resolved otherwise (FIGMA_CHANNEL)
//   --file-key=<k>      disambiguate live channels by file fingerprint
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { connect, join, rpc, close } from "./relay-client.mjs";
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

const asObj = (r) => (typeof r === "string" ? JSON.parse(r) : r);
const rgbKey = (c) => [c.r, c.g, c.b].map((n) => Math.round(n * 255).toString(16).padStart(2, "0")).join("");
// a fill color may be "#rrggbb" OR an {r,g,b} object (0–1), depending on the node.
const colorKey = (color) =>
  typeof color === "string"
    ? color.replace("#", "").toLowerCase().slice(0, 6)
    : color && typeof color.r === "number"
      ? rgbKey(color)
      : null;

export async function run(args) {
  const { flags, channels } = parseFlags(args);
  const root = flags.root;
  if (!root) throw new Error("rebind: --root=<nodeId> is required");
  const onlyCollection = flags.collection || null;
  const doStrokes = !!flags.strokes;
  const dry = !!flags["dry-run"];
  const max = flags.max ? Number(flags.max) : Infinity;

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  join(conn, channel);

  // ── color → variable map ──
  const vars = asObj(await rpc(conn, "get_variables", {}, 15000));
  const byColor = new Map(); // "rrggbb" -> {id, name}
  for (const col of vars.collections || []) {
    if (onlyCollection && col.name !== onlyCollection) continue;
    for (const v of col.variables || []) {
      if (v.resolvedType !== "COLOR") continue;
      const val = Object.values(v.valuesByMode || {})[0];
      if (!val || typeof val.r !== "number") continue;
      const k = rgbKey(val);
      if (!byColor.has(k)) byColor.set(k, { id: v.id, name: `${col.name}/${v.name}` });
    }
  }
  console.log(`① variable color map: ${byColor.size} distinct colors${onlyCollection ? ` (collection "${onlyCollection}")` : ""}`);

  // ── walk the subtree, collect bind targets ──
  const targets = [];
  const unmatched = new Map();
  const seen = new Set();
  const consideredKeys = new Set();
  const queue = [root];

  const considerFill = (node, field, fillArrKey) => {
    const dkey = `${node.id}:${fillArrKey}`;
    if (consideredKeys.has(dkey)) return;
    consideredKeys.add(dkey);
    const arr = node[fillArrKey];
    if (!Array.isArray(arr) || !arr[0]) return;
    const f = arr[0];
    if (f.type !== "SOLID" || f.visible === false || !f.color) return;
    if (node.boundVariables?.[fillArrKey]?.[0]) return; // already bound
    const k = colorKey(f.color);
    if (!k) return;
    const hit = byColor.get(k);
    if (hit) targets.push({ id: node.id, field, varId: hit.id, varName: hit.name });
    else unmatched.set(k, (unmatched.get(k) || 0) + 1);
  };

  const visit = (node) => {
    considerFill(node, "fills/0/color", "fills");
    if (doStrokes) considerFill(node, "strokes/0/color", "strokes");
    if (!seen.has(node.id) && node._childrenTruncated) queue.push(node.id);
    const kids = Array.isArray(node.children) ? node.children : null;
    if (kids) for (const c of kids) visit(c);
  };

  while (queue.length) {
    const id = queue.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    const info = asObj(await rpc(conn, "get_node_info", { nodeId: id, depth: 6 }));
    visit(info);
  }
  console.log(`② walked ${seen.size} subtree fetches → ${targets.length} bindable fills, ${unmatched.size} unmatched colors`);
  if (unmatched.size) {
    const top = [...unmatched.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
    console.log("   unmatched (top): " + top.map(([k, n]) => `#${k}×${n}`).join("  "));
  }

  if (dry) {
    const byVar = new Map();
    for (const t of targets) byVar.set(t.varName, (byVar.get(t.varName) || 0) + 1);
    console.log("③ DRY-RUN — would bind:");
    for (const [name, n] of [...byVar.entries()].sort((a, b) => b[1] - a[1])) console.log(`   ${name.padEnd(24)} ${n}`);
    close(conn);
    return;
  }

  // ── bind (mutates the live file → a partial failure MUST fail loud) ──
  let bound = 0;
  let failures = 0;
  let capped = false;
  for (const t of targets) {
    if (bound >= max) {
      capped = true;
      break;
    }
    try {
      await rpc(conn, "apply_variable_to_node", { nodeId: t.id, variableId: t.varId, field: t.field });
      bound++;
    } catch (e) {
      failures++;
      console.error(`   ✗ ${t.id} ${t.field} → ${t.varName}: ${e.message}`);
    }
  }
  close(conn);
  const attempted = bound + failures;
  if (failures) throw new Error(`rebind: ${failures} bind(s) FAILED — bound ${bound}/${attempted} attempted (${targets.length} targets)`);
  if (capped) console.log(`③ bound ${bound}/${targets.length} fills (stopped at --max=${max}; ${targets.length - bound} left unattempted) ✓`);
  else console.log(`③ bound ${bound}/${targets.length} fills to variables ✓`);
}
