#!/usr/bin/env node
// extract-tokens.mjs — token extraction stage
//
// Reads <dir>/captured.html + <dir>/_detect.json, extracts the source's real
// values, maps them onto shadcn token names, and writes:
//   <dir>/tokens.css   (:root { --shadcn-name: value; ... }, low-confidence tagged)
//   <dir>/_tokens.json (structured: { strategy, tokens:{name:{value,source,confidence}} })
//
// Strategies:
//   shadcn        — direct var transfer (read declared --background etc.)
//   tailwind-map  — resolve utility classes to palette values via tw-palette.mjs
//   bespoke       — value clustering / declared-var transfer
//
// Usage: node extract-tokens.mjs <dir> [--format=oklch|hex]

import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { twColor } from "./tw-palette.mjs";

const dir = resolve(process.argv[2] || "captured");
const fmt = (process.argv.find((a) => a.startsWith("--format=")) || "--format=oklch").split("=")[1];

const htmlPath = join(dir, "captured.html");
const detPath = join(dir, "_detect.json");
for (const p of [htmlPath, detPath]) {
  if (!existsSync(p)) {
    console.error(`[extract] ERROR: ${p} not found. Run capture.mjs + detect.mjs first.`);
    process.exit(1);
  }
}
const html = await readFile(htmlPath, "utf-8");
const { strategy } = JSON.parse(await readFile(detPath, "utf-8"));

const SHADCN = [
  "background","foreground","card","card-foreground","popover","popover-foreground",
  "primary","primary-foreground","secondary","secondary-foreground","muted","muted-foreground",
  "accent","accent-foreground","destructive","border","input","ring",
  "chart-1","chart-2","chart-3","chart-4","chart-5",
];

const tokens = {}; // name -> { value, source, confidence }
const put = (name, value, source, confidence) => {
  if (value == null) return;
  tokens[name] = { value, source, confidence };
};

// ── strategy: shadcn (direct var transfer) ─────────────────────────────────
function declaredVars() {
  const out = {};
  for (const [, k, v] of html.matchAll(/(--[a-zA-Z0-9-]+)\s*:\s*([^;{}"]+)/g)) {
    if (!(k in out)) out[k] = v.trim();
  }
  return out;
}

if (strategy === "shadcn") {
  const vars = declaredVars();
  for (const name of SHADCN) {
    const v = vars[`--${name}`];
    if (v) put(name, v, `--${name}`, 1.0);
  }
}

// ── strategy: tailwind-map (utility classes → palette) ─────────────────────
else if (strategy === "tailwind-map") {
  // Intent map: which Tailwind utility prefix feeds which shadcn token.
  const intents = [
    [/\bbg-([a-z]+-\d{2,3}|white|black)\b/g, "background"],
    [/\btext-([a-z]+-\d{2,3}|white|black)\b/g, "foreground"],
    [/\bborder-([a-z]+-\d{2,3})\b/g, "border"],
    [/\b(?:bg|text)-(?:primary|blue-600|indigo-600)\b/g, "primary"], // common primary intents
  ];
  const freq = {}; // shadcnName -> Map(value -> count)
  for (const [re, name] of intents) {
    for (const m of html.matchAll(re)) {
      const colorName = m[1] || (m[0].includes("primary") ? "blue-600" : null);
      const val = twColor(colorName);
      if (!val) continue;
      (freq[name] ??= new Map()).set(val, (freq[name]?.get(val) || 0) + 1);
    }
  }
  for (const [name, m] of Object.entries(freq)) {
    const [val] = [...m.entries()].sort((a, b) => b[1] - a[1])[0];
    put(name, val, "tailwind class intent", 0.7);
  }
  // loud warning if the map produced nothing (the old silent-failure bug)
  if (Object.keys(tokens).length === 0) {
    console.error(
      "[extract] WARNING: tailwind-map produced ZERO tokens — utility classes did not " +
      "resolve against tw-palette.mjs (uncommon color names/steps?). tokens.css will be empty."
    );
  }
}

// ── strategy: bespoke (declared vars first, else value clustering) ─────────
else {
  const vars = declaredVars();
  const declared = Object.keys(vars).length;

  if (declared >= 8) {
    // declared-var system → high fidelity; map by heuristic name match.
    const pick = (re) => Object.entries(vars).find(([k]) => re.test(k))?.[1];
    put("background", pick(/--(bg|background)$/), "declared var", 1.0);
    put("foreground", pick(/--(text|fg|foreground|ink)$/), "declared var", 1.0);
    put("card", pick(/--(surface|card|panel)$/), "declared var", 0.9);
    put("muted-foreground", pick(/--(muted|muted-fg)$/), "declared var", 0.9);
    put("border", pick(/--border$/), "declared var", 1.0);
    put("destructive", pick(/--(danger|destructive|error)$/), "declared var", 0.9);
    const primary = pick(/--(primary|accent|brand|green|blue)$/);
    put("primary", primary, "declared var", 0.85);
    put("ring", pick(/--(ring|focus|.*-ring)$/), "declared var", 0.9);
  } else {
    // ad-hoc inline styles → frequency clustering (low confidence, the guess path)
    const colorRe = /#[0-9a-fA-F]{3,8}\b/g;
    const counts = new Map();
    // exclude colors inside url()/data: and svg fills to avoid skew
    const cleaned = html.replace(/url\([^)]*\)/g, "").replace(/<svg[\s\S]*?<\/svg>/g, "");
    for (const m of cleaned.matchAll(colorRe)) {
      const c = m[0].toLowerCase();
      counts.set(c, (counts.get(c) || 0) + 1);
    }
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
    if (ranked[0]) put("background", ranked[0], "most frequent color", 0.4);
    if (ranked[1]) put("foreground", ranked[1], "2nd most frequent", 0.4);
    // primary = most frequent that isn't bg/fg; border de-duped against primary
    const accent = ranked.find((c) => c !== ranked[0] && c !== ranked[1]);
    if (accent) put("primary", accent, "most frequent non-bg/fg", 0.4);
    const border = ranked.find((c) => c !== ranked[0] && c !== ranked[1] && c !== accent);
    if (border) put("border", border, "next distinct color", 0.4);
  }
}

// ── radius (best-effort, both paths) ───────────────────────────────────────
const radius = (html.match(/border-radius:\s*([\d.]+(?:px|rem|em))/i) || [])[1];
if (radius) put("radius", radius, "first border-radius", 0.5);

// ── emit ───────────────────────────────────────────────────────────────────
const lowConf = Object.entries(tokens).filter(([, t]) => t.confidence < 0.5).map(([k]) => k);
const body = Object.entries(tokens)
  .map(([k, t]) => `  --${k}: ${t.value};${t.confidence < 0.5 ? "  /* low confidence — verify */" : ""}`)
  .join("\n");

const header =
  `/* generated by design-import · strategy: ${strategy} · format target: ${fmt} */\n` +
  `/* Convert values to the repo theme's ${fmt}() if they are not already. */\n`;

await writeFile(join(dir, "tokens.css"), `${header}:root {\n${body}\n}\n`);
await writeFile(join(dir, "_tokens.json"), JSON.stringify({ strategy, tokens }, null, 2));

console.error(`[extract] wrote tokens.css · strategy=${strategy} · ${Object.keys(tokens).length} tokens`);
console.error(`[extract] low-confidence: ${lowConf.join(", ") || "none"}`);
