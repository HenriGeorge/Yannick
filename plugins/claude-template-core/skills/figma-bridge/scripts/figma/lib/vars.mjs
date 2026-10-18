// vars.mjs — read-only CSS↔Figma variable drift check. Parses --prefix tokens from --css, reads the
// live --collection via get_variables, reports missing / extra / changed. Reuses tokens.mjs's parser
// (same stem-naming convention tokens.mjs writes with, so names line up). Zero-dep.
import { readFileSync } from "node:fs";
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";
import { parseColorTokens } from "./tokens.mjs";

function parseFlags(args) {
  const flags = {}, channels = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) { if (m[1] === "channel") channels.push(m[2]); else flags[m[1]] = m[2]; }
    else if (a.startsWith("--")) flags[a.slice(2)] = true;
  }
  return { flags, channels };
}
const asObj = (r) => (typeof r === "string" ? JSON.parse(r) : r);
const close4 = (a, b, tol) => ["r", "g", "b", "a"].every((k) => Math.abs((a[k] ?? 0) - (b[k] ?? 0)) <= tol);

// Normalize a get_variables reply to [{name, rgba}] for the named collection. The relay shape is
// {collections:[{name, variables:[{name, resolvedType, valuesByMode:{<modeId>: rgba | alias}}]}]}.
// Only COLOR variables whose first mode is a RAW {r,g,b,a} are kept — VARIABLE_ALIAS values point at
// a primitive and can't be compared to a literal hex, so they're skipped.
export function collectVars(res, collection) {
  const r = asObj(res);
  const out = [];
  for (const c of r?.collections ?? []) {
    if (collection && c.name !== collection) continue;
    for (const v of c.variables ?? []) {
      if (v.resolvedType && v.resolvedType !== "COLOR") continue;
      const modes = v.valuesByMode ?? {};
      const first = modes[Object.keys(modes)[0]];
      if (first && typeof first === "object" && "r" in first) out.push({ name: v.name, rgba: first });
    }
  }
  return out;
}

export function diffVars(cssTokens, figmaVars, tol = 1 / 255) {
  const fByName = new Map(figmaVars.map((v) => [v.name, v]));
  const cByName = new Map(cssTokens.map((t) => [t.name, t]));
  const missing = cssTokens.filter((t) => !fByName.has(t.name));
  const extra = figmaVars.filter((v) => !cByName.has(v.name));
  const changed = [];
  for (const t of cssTokens) {
    const v = fByName.get(t.name);
    if (v && !close4(t.value, v.rgba, tol)) changed.push({ name: t.name, css: t.hex, figma: v.rgba });
  }
  return { missing, extra, changed };
}

export async function run(args) {
  const { flags, channels } = parseFlags(args);
  if (!flags.css) throw new Error("vars: --css=<file> is required");
  if (!flags.collection) throw new Error("vars: --collection=<name> is required");
  const prefix = flags.prefix ?? "--";
  // Fail loud on an empty/malformed CSS parse (wrong --prefix) BEFORE touching the relay.
  const cssTokens = parseColorTokens(readFileSync(flags.css, "utf8"), prefix, flags.css);
  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const conn = await connect(process.env.FIGMA_WS_URL ?? "ws://localhost:3055");
  join(conn, channel);
  let figmaVars;
  try {
    const raw = asObj(await rpc(conn, "get_variables", {}, 15000));
    // Distinguish "collection not found" (a typo) from "collection is empty" — don't silently
    // report every CSS token as drift against an absent collection.
    const names = (raw?.collections ?? []).map((c) => c.name);
    if (!names.includes(flags.collection)) {
      throw new Error(`vars: collection "${flags.collection}" not found (have: ${names.join(", ") || "(none)"})`);
    }
    figmaVars = collectVars(raw, flags.collection);
  } finally { close(conn); }
  const d = diffVars(cssTokens, figmaVars);
  const show = (label, rows, fmt) => { console.log(`${label}: ${rows.length}`); rows.forEach((x) => console.log(`  ${fmt(x)}`)); };
  show("missing (in CSS, not Figma)", d.missing, (m) => `${m.name} ${m.hex}`);
  show("extra (in Figma, not CSS)", d.extra, (e) => e.name);
  show("changed (hex differs)", d.changed, (c) => `${c.name} css=${c.css} figma=${JSON.stringify(c.figma)}`);
  const drift = d.missing.length + d.extra.length + d.changed.length;
  console.log(`vars: ${drift} drift(s) across collection "${flags.collection}" (${cssTokens.length} css, ${figmaVars.length} figma)`);
  if (flags.strict && drift > 0) process.exit(1);
}
