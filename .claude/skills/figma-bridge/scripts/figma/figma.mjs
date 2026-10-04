#!/usr/bin/env node
// figma.mjs — one CLI for the quota-free ClaudeTalkToFigma bridge (relay :3055).
//
// A THIN dispatcher, no business logic: it prints help, runs the relay preflight, then lazily
// `await import('./lib/<cmd>.mjs')` and calls its `run(args)`. The capture family (`capture`/`export`)
// are the ONLY subcommands whose module imports the heavy deps (playwright/esbuild/dom-to-svg), and
// they do so LAZILY inside run() — so dispatching a core subcommand loads zero deps and runs with no
// `npm install` (the load-bearing R5 guarantee; a static capture import at the top of THIS file or any
// core lib/ module would break it — see tests/test_figma_toolkit.sh FT2/FT2b). Do not add such imports.
//
// Node ≥21 ESM, built-in global WebSocket (no `ws` dep).

const SUBCOMMANDS = {
  // core — zero-dep (Node + built-in WebSocket only)
  tokens: "CSS custom-property hex → Figma COLOR variables (--css --prefix --collection)",
  place: "stream one SVG straight into a Figma page (set_svg)",
  rebind: "rebind an SVG's variable references to a Figma collection (--collection)",
  probe: "probe channels → the live channel's pages + fileKey",
  page: "ensure / rename / set-current a Figma page",
  png: "export a Figma selection → PNG on disk (--all --filter --channel)",
  // capture — optional deps, lazy-imported (needs `npm install --prefix <this dir>`)
  capture: "live page → sharp vector SVG (needs npm install: playwright/esbuild/dom-to-svg)",
  export: "config-driven: capture N targets → validate → distribute set_svg (needs npm install)",
};

const CORE = ["tokens", "place", "rebind", "probe", "page", "png"];
const CAPTURE = ["capture", "export"];

function printHelp(out) {
  out("figma.mjs — ClaudeTalkToFigma bridge toolkit (relay ws://localhost:3055)\n");
  out("usage: node figma.mjs <subcommand> [options]\n");
  out("subcommands:");
  for (const name of [...CORE, ...CAPTURE]) {
    out(`  ${name.padEnd(8)} ${SUBCOMMANDS[name]}`);
  }
  out("");
  out(`  core (zero-dep, no install):  ${CORE.join(" ")}`);
  out(`  capture (needs npm install):  ${CAPTURE.join(" ")}`);
  out("");
  out("Prereq: the ClaudeTalkToFigma plugin must be running & joined (Figma Command+P).");
  out("Override the relay URL with FIGMA_WS_URL; the channel with --channel or FIGMA_CHANNEL.");
}

const args = process.argv.slice(2);
const cmd = args[0];
// PO8: `-h`/`--help` anywhere, or no subcommand → print help and exit 0 WITHOUT preflight or import
// (so `tokens --help` never touches :3055 and never needs the subcommand module to exist).
const wantsHelp = args.includes("-h") || args.includes("--help");

if (wantsHelp || !cmd) {
  printHelp(console.log);
  process.exit(0);
}

if (!SUBCOMMANDS[cmd]) {
  console.error(`figma.mjs: unknown subcommand "${cmd}"\n`);
  printHelp(console.error);
  process.exit(2);
}

// RUN path: preflight the relay, then dispatch. All errors surface as the message ONLY (never a raw
// stack) so a wedged relay / dep-missing reads legibly.
const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
try {
  const { assertRelay } = await import("./lib/preflight.mjs");
  await assertRelay(socketUrl);
  const mod = await import(`./lib/${cmd}.mjs`);
  await mod.run(args.slice(1));
} catch (err) {
  console.error(err?.message ?? String(err));
  process.exit(1);
}
