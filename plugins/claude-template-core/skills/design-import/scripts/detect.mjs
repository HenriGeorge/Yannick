#!/usr/bin/env node
// detect.mjs — design-system detection stage
//
// Reads <dir>/captured.html (produced by capture.mjs), classifies the source
// design system, and writes <dir>/_detect.json with { strategy, confidence, signals }.
//
// Strategies (consumed by extract-tokens.mjs):
//   shadcn        — declares the shadcn token triad as CSS custom properties
//   tailwind-map  — uses Tailwind utility classes (resolve via tw-palette.mjs)
//   bespoke       — own custom-property system OR ad-hoc inline styles (value clustering)
//
// Usage: node detect.mjs <dir>

import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";

const dir = resolve(process.argv[2] || "captured");
const file = join(dir, "captured.html");
if (!existsSync(file)) {
  console.error(`[detect] ERROR: ${file} not found. Run capture.mjs first.`);
  process.exit(1);
}
const html = await readFile(file, "utf-8");

// ── signals ──────────────────────────────────────────────────────────────
const hasShadcnTriad =
  /--background\b/.test(html) && /--foreground\b/.test(html) && /--primary\b/.test(html);

// Count individual Tailwind utility *tokens* across all class attributes,
// not whole class="" blocks (one block can hold many utilities).
const twUtil = /\b(?:flex|grid|gap-\d+|p[xytrbl]?-\d+|m[xytrbl]?-\d+|text-(?:xs|sm|base|lg|xl|\d?xl)|bg-[a-z]+-\d{2,3}|text-[a-z]+-\d{2,3}|border-[a-z]+-\d{2,3}|rounded(?:-[a-z]+)?)\b/g;
let twClassHits = 0;
for (const m of html.matchAll(/class="([^"]*)"/g)) {
  twClassHits += (m[1].match(twUtil) || []).length;
}

const customProps = new Set(
  [...html.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)].map((m) => m[1])
);
const hasOwnVarSystem = customProps.size >= 8 && !hasShadcnTriad;

const componentLib = /\b(?:Mui[A-Z]\w+|chakra-[a-z]+|ant-[a-z]+)\b/.test(html);

// ── decide ───────────────────────────────────────────────────────────────
let strategy, confidence;
const signals = {
  shadcnTriad: hasShadcnTriad,
  tailwindClassHits: twClassHits,
  customPropCount: customProps.size,
  componentLib,
};

// A strong DECLARED custom-property system holds the source's REAL values, so it beats
// tailwind-map (which only guesses palette values from utility class names via tw-palette,
// and silently resolves 0 tokens when the names aren't in the table — e.g. a Webflow site
// whose colors live in `--_colors---*` vars but that also ships incidental utility classes).
// So check the own-var system BEFORE tailwind utilities. (Fixed: bleibtgleich.dev had 14
// declared vars but got misclassified tailwind-map → 0 tokens.)
const strongOwnVars = hasOwnVarSystem && customProps.size >= 10;

if (hasShadcnTriad) {
  strategy = "shadcn";
  confidence = 0.9;
} else if (strongOwnVars) {
  strategy = "bespoke";
  confidence = customProps.size >= 20 ? 0.8 : 0.6;
} else if (twClassHits >= 6) {
  strategy = "tailwind-map";
  confidence = Math.min(0.85, 0.4 + twClassHits / 40);
} else if (hasOwnVarSystem) {
  strategy = "bespoke";
  // declared vars → high; the more declared, the more confident the VALUES are
  confidence = customProps.size >= 20 ? 0.8 : 0.55;
} else {
  strategy = "bespoke";
  confidence = 0.3; // ad-hoc inline styles only → value clustering, low confidence
}

if (componentLib) {
  signals.warning =
    "component-library markup detected (MUI/Chakra/Ant) — output is an approximate reskin, not a translation";
}

await writeFile(
  join(dir, "_detect.json"),
  JSON.stringify({ strategy, confidence, signals }, null, 2)
);

console.error(`[detect] strategy=${strategy} confidence=${confidence.toFixed(2)}`);
if (signals.warning) console.error(`[detect] WARNING: ${signals.warning}`);
